"""Cloud-side model validator for XGO2 vision navigation.

Validates TFLite models, Neo compilation output, and label maps before
Greengrass deployment. Catches format errors, shape mismatches, and
missing artifacts without requiring a device deployment.

Python 3.11+ — runs on developer machine / cloud.
"""

from __future__ import annotations

import logging
import os
import tarfile
import tempfile
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of model validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    input_shape: tuple | None = None
    output_shapes: dict | None = None


def validate_tflite_model(
    model_path: str,
    expected_input_shape: tuple,
    test_image_path: str | None = None,
) -> ValidationResult:
    """Validate a TFLite model file.

    Checks that the model loads, the input tensor shape matches the
    expected shape, and (optionally) that inference on a test image
    produces detection outputs in the expected format (bounding boxes,
    class IDs, confidence scores).

    Args:
        model_path: Path to the .tflite model file.
        expected_input_shape: Expected input tensor shape, e.g. (1, 300, 300, 3).
        test_image_path: Optional path to a test image for inference check.

    Returns:
        ValidationResult with validation outcome and shape information.
    """
    errors: list[str] = []
    warnings: list[str] = []
    input_shape: tuple | None = None
    output_shapes: dict | None = None

    # --- Check file exists ---
    if not os.path.isfile(model_path):
        return ValidationResult(
            valid=False,
            errors=[f"Model file not found: {model_path}"],
        )

    # --- Load model ---
    try:
        interpreter = _load_tflite_interpreter(model_path)
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to load TFLite model: {e}"],
        )

    # --- Verify input shape ---
    try:
        input_details = interpreter.get_input_details()
        if not input_details:
            errors.append("Model has no input tensors")
        else:
            actual_input_shape = tuple(input_details[0]["shape"])
            input_shape = actual_input_shape
            if actual_input_shape != expected_input_shape:
                errors.append(
                    f"Input shape mismatch: expected {expected_input_shape}, "
                    f"got {actual_input_shape}"
                )
    except Exception as e:
        errors.append(f"Failed to read input details: {e}")

    # --- Collect output shapes ---
    try:
        output_details = interpreter.get_output_details()
        if output_details:
            output_shapes = {
                detail["name"]: tuple(detail["shape"])
                for detail in output_details
            }
    except Exception as e:
        warnings.append(f"Failed to read output details: {e}")

    # --- Run inference on test image (if provided and no errors so far) ---
    if test_image_path is not None and not errors:
        inference_errors, inference_warnings = _run_test_inference(
            interpreter, input_details, test_image_path, expected_input_shape
        )
        errors.extend(inference_errors)
        warnings.extend(inference_warnings)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        input_shape=input_shape,
        output_shapes=output_shapes,
    )


def validate_neo_output(compiled_tar_path: str) -> ValidationResult:
    """Validate a Neo compilation output tar.gz.

    Extracts the archive to a temporary directory and checks that it
    contains at least one shared object (.so) file and at least one
    model definition or parameter file.

    Args:
        compiled_tar_path: Path to the Neo output tar.gz file.

    Returns:
        ValidationResult with validation outcome.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check file exists ---
    if not os.path.isfile(compiled_tar_path):
        return ValidationResult(
            valid=False,
            errors=[f"Compiled model archive not found: {compiled_tar_path}"],
        )

    # --- Extract and inspect ---
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(compiled_tar_path, "r:gz") as tar:
                tar.extractall(tmpdir)

            extracted_files = _list_files_recursive(tmpdir)

            if not extracted_files:
                errors.append("Archive is empty — no files extracted")
                return ValidationResult(valid=False, errors=errors)

            # Check for shared object (.so) file
            so_files = [f for f in extracted_files if f.endswith(".so")]
            if not so_files:
                errors.append(
                    "No shared object (.so) file found in archive. "
                    "Neo-compiled models should contain a compiled .so library."
                )

            # Check for model definition / parameter files
            # Common Neo output files: .json (model def), .params, .npy,
            # .meta, manifest, etc.
            model_extensions = {
                ".json", ".params", ".npy", ".meta", ".txt", ".bin",
            }
            model_files = [
                f for f in extracted_files
                if any(f.endswith(ext) for ext in model_extensions)
            ]
            if not model_files:
                errors.append(
                    "No model definition or parameter files found in archive. "
                    "Expected files with extensions: "
                    + ", ".join(sorted(model_extensions))
                )

            if not errors:
                logger.info(
                    "Neo output valid: %d .so file(s), %d model file(s)",
                    len(so_files),
                    len(model_files),
                )

    except tarfile.TarError as e:
        errors.append(f"Failed to extract tar.gz archive: {e}")
    except Exception as e:
        errors.append(f"Unexpected error inspecting archive: {e}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_label_map(label_map_path: str) -> ValidationResult:
    """Validate a label map file.

    Checks that the file exists, is non-empty, and contains valid class
    name mappings (one class name per line).

    Args:
        label_map_path: Path to the label map text file.

    Returns:
        ValidationResult with validation outcome.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check file exists ---
    if not os.path.isfile(label_map_path):
        return ValidationResult(
            valid=False,
            errors=[f"Label map file not found: {label_map_path}"],
        )

    # --- Read and validate contents ---
    try:
        with open(label_map_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to read label map file: {e}"],
        )

    if not content.strip():
        return ValidationResult(
            valid=False,
            errors=["Label map file is empty or contains only whitespace"],
        )

    lines = content.strip().splitlines()
    valid_labels: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped:
            valid_labels.append(stripped)
        else:
            warnings.append(f"Line {i + 1} is empty or whitespace-only")

    if not valid_labels:
        return ValidationResult(
            valid=False,
            errors=["Label map contains no valid class names"],
            warnings=warnings,
        )

    logger.info("Label map valid: %d class names", len(valid_labels))

    return ValidationResult(
        valid=True,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_tflite_interpreter(model_path: str):
    """Load a TFLite interpreter, trying tflite_runtime first, then tensorflow.lite."""
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        from tensorflow.lite.python.interpreter import Interpreter

    interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    return interpreter


def _run_test_inference(
    interpreter,
    input_details: list[dict],
    test_image_path: str,
    expected_input_shape: tuple,
) -> tuple[list[str], list[str]]:
    """Run inference on a test image and verify detection output format.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Load test image
    try:
        from PIL import Image

        img = Image.open(test_image_path).convert("RGB")
    except FileNotFoundError:
        errors.append(f"Test image not found: {test_image_path}")
        return errors, warnings
    except Exception as e:
        errors.append(f"Failed to load test image: {e}")
        return errors, warnings

    # Preprocess: resize to model input dimensions, normalize
    try:
        h, w = expected_input_shape[1], expected_input_shape[2]
        img_resized = img.resize((w, h))
        img_array = np.array(img_resized, dtype=np.float32) / 255.0
        img_array = np.expand_dims(img_array, axis=0)

        # Match input dtype
        input_dtype = input_details[0]["dtype"]
        if input_dtype == np.uint8:
            img_array = (img_array * 255.0).astype(np.uint8)

        interpreter.set_tensor(input_details[0]["index"], img_array)
        interpreter.invoke()
    except Exception as e:
        errors.append(f"Inference failed on test image: {e}")
        return errors, warnings

    # Verify detection output format
    output_details = interpreter.get_output_details()
    if len(output_details) < 3:
        errors.append(
            f"Expected at least 3 output tensors (boxes, classes, scores), "
            f"got {len(output_details)}"
        )
        return errors, warnings

    # Standard SSD detection model outputs:
    # - boxes: [1, N, 4] — bounding box coordinates
    # - classes: [1, N] — class IDs
    # - scores: [1, N] — confidence scores
    # (Some models also have a 4th output for detection count.)
    output_tensors = {}
    for detail in output_details:
        tensor = interpreter.get_tensor(detail["index"])
        output_tensors[detail["name"]] = tensor

    # Check that we have arrays with reasonable shapes
    has_boxes = False
    has_classes = False
    has_scores = False

    for name, tensor in output_tensors.items():
        shape = tensor.shape
        if len(shape) == 3 and shape[-1] == 4:
            has_boxes = True
        elif len(shape) >= 1:
            # Could be classes or scores — both are 1D or 2D
            flat = tensor.flatten()
            if len(flat) > 0:
                if np.all((flat >= 0) & (flat <= 1)):
                    has_scores = True
                else:
                    has_classes = True

    if not has_boxes:
        warnings.append(
            "Could not identify bounding box output tensor "
            "(expected shape [1, N, 4])"
        )
    if not has_scores:
        warnings.append(
            "Could not identify confidence scores output tensor"
        )
    if not has_classes:
        warnings.append(
            "Could not identify class IDs output tensor"
        )

    if has_boxes and has_scores:
        logger.info("Test inference produced valid detection outputs")
    elif not has_boxes and not has_scores:
        errors.append(
            "Model output does not match expected detection format "
            "(boxes, classes, scores)"
        )

    return errors, warnings


def _list_files_recursive(directory: str) -> list[str]:
    """List all files in a directory tree, returning relative paths."""
    files: list[str] = []
    for root, _dirs, filenames in os.walk(directory):
        for filename in filenames:
            rel_path = os.path.relpath(
                os.path.join(root, filename), directory
            )
            files.append(rel_path)
    return files


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Validate model artifacts for XGO2 vision navigation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # tflite sub-command
    tflite_parser = subparsers.add_parser("tflite", help="Validate a TFLite model")
    tflite_parser.add_argument("model_path", help="Path to .tflite model file")
    tflite_parser.add_argument(
        "--input-shape",
        default="1,300,300,3",
        help="Expected input shape as comma-separated ints (default: 1,300,300,3)",
    )
    tflite_parser.add_argument(
        "--test-image", default=None, help="Optional test image for inference check"
    )

    # neo sub-command
    neo_parser = subparsers.add_parser("neo", help="Validate Neo compilation output")
    neo_parser.add_argument("tar_path", help="Path to Neo output tar.gz")

    # labels sub-command
    labels_parser = subparsers.add_parser("labels", help="Validate a label map file")
    labels_parser.add_argument("label_map_path", help="Path to label map text file")

    args = parser.parse_args()

    if args.command == "tflite":
        shape = tuple(int(x) for x in args.input_shape.split(","))
        result = validate_tflite_model(args.model_path, shape, args.test_image)
    elif args.command == "neo":
        result = validate_neo_output(args.tar_path)
    elif args.command == "labels":
        result = validate_label_map(args.label_map_path)
    else:
        parser.print_help()
        sys.exit(1)

    # Print results
    status = "PASS" if result.valid else "FAIL"
    print(f"\nValidation: {status}")
    if result.input_shape:
        print(f"  Input shape: {result.input_shape}")
    if result.output_shapes:
        print(f"  Output shapes: {result.output_shapes}")
    for error in result.errors:
        print(f"  ERROR: {error}")
    for warning in result.warnings:
        print(f"  WARNING: {warning}")

    sys.exit(0 if result.valid else 1)
