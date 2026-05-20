"""Cloud-side model validator.

Validates TFLite models, Neo compilation output archives, and label map
files before deployment to the Zumi device. Designed to catch format
errors, shape mismatches, and missing artifacts without waiting for a
failed OTA deployment.

Python 3.11+.
"""

import logging
import os
import tarfile
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of model validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    input_shape: Optional[tuple] = None
    output_shapes: Optional[dict] = None


# ---------------------------------------------------------------------------
# TFLite model validation (Req 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------

def _load_tflite_interpreter(model_path: str):
    """Load a TFLite interpreter, trying tflite_runtime first."""
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        try:
            from tensorflow.lite import Interpreter
        except ImportError:
            try:
                import tensorflow as tf
                Interpreter = tf.lite.Interpreter
            except (ImportError, AttributeError):
                raise ImportError(
                    "Neither tflite_runtime nor tensorflow is installed. "
                    "Install one to validate TFLite models."
                )
    return Interpreter(model_path=model_path)


def validate_tflite_model(
    model_path: str,
    expected_input_shape: tuple,
    test_image_path: str | None = None,
) -> ValidationResult:
    """Validate a TFLite model file.

    Checks: model loads, input shape matches, inference produces
    detection outputs (boxes, classes, scores).

    Args:
        model_path: Path to the ``.tflite`` model file.
        expected_input_shape: Expected input tensor shape, e.g.
            ``(1, 128, 128, 3)``.
        test_image_path: Optional path to a test image. If provided,
            the validator runs inference and checks output format.

    Returns:
        A :class:`ValidationResult` indicating whether the model is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []
    input_shape: Optional[tuple] = None
    output_shapes: Optional[dict] = None

    # --- Check file exists ---
    if not os.path.isfile(model_path):
        return ValidationResult(
            valid=False,
            errors=[f"Model file not found: {model_path}"],
        )

    # --- Load model ---
    try:
        interpreter = _load_tflite_interpreter(model_path)
        interpreter.allocate_tensors()
    except ImportError as exc:
        return ValidationResult(
            valid=False,
            errors=[str(exc)],
        )
    except Exception as exc:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to load TFLite model: {exc}"],
        )

    # --- Verify input shape (Req 9.3) ---
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

    # --- Collect output shapes ---
    output_details = interpreter.get_output_details()
    if output_details:
        output_shapes = {
            detail["name"]: tuple(detail["shape"])
            for detail in output_details
        }

    # --- Run inference on test image if provided (Req 9.2) ---
    if test_image_path is not None and not errors:
        inference_errors, inference_warnings = _run_test_inference(
            interpreter, input_details, output_details, test_image_path
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


def _run_test_inference(
    interpreter,
    input_details: list,
    output_details: list,
    test_image_path: str,
) -> tuple[list[str], list[str]]:
    """Run inference on a test image and verify detection output format.

    Returns:
        A tuple of (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        import numpy as np
    except ImportError:
        return (["numpy is required for test inference"], [])

    # Load and preprocess test image
    if not os.path.isfile(test_image_path):
        return ([f"Test image not found: {test_image_path}"], [])

    try:
        # Try PIL first, fall back to raw numpy
        try:
            from PIL import Image

            img = Image.open(test_image_path).convert("RGB")
            target_h = input_details[0]["shape"][1]
            target_w = input_details[0]["shape"][2]
            img = img.resize((target_w, target_h))
            img_array = np.array(img, dtype=np.float32) / 255.0
        except ImportError:
            warnings.append(
                "PIL not available; using random test input instead of "
                "actual image"
            )
            shape = tuple(input_details[0]["shape"])
            img_array = np.random.rand(*shape[1:]).astype(np.float32)

        # Add batch dimension if needed
        if img_array.ndim == 3:
            img_array = np.expand_dims(img_array, axis=0)

        # Match the model's expected dtype
        input_dtype = input_details[0]["dtype"]
        if input_dtype == np.uint8:
            img_array = (img_array * 255).astype(np.uint8)
        else:
            img_array = img_array.astype(input_dtype)

        # Run inference
        interpreter.set_tensor(input_details[0]["index"], img_array)
        interpreter.invoke()

        # Check output tensors for detection format
        _verify_detection_outputs(interpreter, output_details, errors, warnings)

    except Exception as exc:
        errors.append(f"Inference failed: {exc}")

    return errors, warnings


def _verify_detection_outputs(
    interpreter,
    output_details: list,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Verify that model outputs look like object detection results.

    Standard SSD detection models produce 4 output tensors:
    - detection boxes: shape [1, N, 4]
    - detection classes: shape [1, N]
    - detection scores: shape [1, N]
    - detection count: shape [1] or scalar

    We check for at least boxes, classes, and scores by shape heuristics.
    """
    import numpy as np

    if len(output_details) < 3:
        errors.append(
            f"Expected at least 3 output tensors (boxes, classes, scores), "
            f"got {len(output_details)}"
        )
        return

    found_boxes = False
    found_classes = False
    found_scores = False

    for detail in output_details:
        tensor = interpreter.get_tensor(detail["index"])
        shape = tensor.shape
        name = detail.get("name", "").lower()

        # Boxes: shape like [1, N, 4]
        if len(shape) == 3 and shape[-1] == 4:
            found_boxes = True
        # Classes or scores: shape like [1, N]
        elif len(shape) == 2 and shape[0] == 1:
            # Distinguish by value range or name
            if "class" in name:
                found_classes = True
            elif "score" in name:
                found_scores = True
            else:
                # Heuristic: if values are integers, likely classes;
                # if floats in [0,1], likely scores
                if np.issubdtype(tensor.dtype, np.floating):
                    values = tensor.flatten()
                    if len(values) > 0 and np.all(values >= 0) and np.all(values <= 1):
                        found_scores = True
                    else:
                        found_classes = True
                else:
                    found_classes = True

    if not found_boxes:
        errors.append("No detection boxes output found (expected shape [1, N, 4])")
    if not found_classes:
        warnings.append(
            "Could not identify detection classes output tensor by name or shape"
        )
    if not found_scores:
        warnings.append(
            "Could not identify detection scores output tensor by name or shape"
        )


# ---------------------------------------------------------------------------
# Neo output validation (Req 9.4)
# ---------------------------------------------------------------------------

# File extensions that indicate model definition or parameter files
_MODEL_FILE_EXTENSIONS = frozenset({
    ".json", ".params", ".sym", ".xml", ".bin", ".pb", ".pbtxt",
    ".onnx", ".cfg", ".weights", ".meta", ".index", ".data-00000-of-00001",
})


def validate_neo_output(compiled_tar_path: str) -> ValidationResult:
    """Validate a Neo compilation output tar.gz.

    Checks: tar.gz extracts, contains expected artifacts
    (shared object library, model definition, parameters).

    Args:
        compiled_tar_path: Path to the compiled model ``.tar.gz`` file.

    Returns:
        A :class:`ValidationResult` indicating whether the archive is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check file exists ---
    if not os.path.isfile(compiled_tar_path):
        return ValidationResult(
            valid=False,
            errors=[f"Compiled model archive not found: {compiled_tar_path}"],
        )

    # --- Open and inspect tar.gz ---
    try:
        with tarfile.open(compiled_tar_path, "r:gz") as tar:
            members = tar.getnames()
    except (tarfile.TarError, OSError) as exc:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to open tar.gz archive: {exc}"],
        )

    if not members:
        return ValidationResult(
            valid=False,
            errors=["Archive is empty — no files found"],
        )

    # --- Check for shared object (.so) ---
    so_files = [m for m in members if m.endswith(".so")]
    if not so_files:
        errors.append(
            "No shared object (.so) file found in archive. "
            f"Archive contains: {members}"
        )

    # --- Check for model definition/parameter files ---
    model_files = [
        m for m in members
        if any(m.endswith(ext) for ext in _MODEL_FILE_EXTENSIONS)
    ]
    if not model_files:
        errors.append(
            "No model definition or parameter files found in archive. "
            f"Expected files with extensions: "
            f"{sorted(_MODEL_FILE_EXTENSIONS)}. "
            f"Archive contains: {members}"
        )

    if so_files:
        logger.info("Found shared object files: %s", so_files)
    if model_files:
        logger.info("Found model files: %s", model_files)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Label map validation (Req 9.5)
# ---------------------------------------------------------------------------

def validate_label_map(label_map_path: str) -> ValidationResult:
    """Validate a label map file.

    Checks: file exists, non-empty, contains valid class name mappings
    (at least one non-whitespace line).

    Args:
        label_map_path: Path to the label map text file.

    Returns:
        A :class:`ValidationResult` indicating whether the label map is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check file exists ---
    if not os.path.isfile(label_map_path):
        return ValidationResult(
            valid=False,
            errors=[f"Label map file not found: {label_map_path}"],
        )

    # --- Read contents ---
    try:
        with open(label_map_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to read label map file: {exc}"],
        )

    # --- Check non-empty ---
    if not content:
        return ValidationResult(
            valid=False,
            errors=["Label map file is empty"],
        )

    # --- Check for at least one non-whitespace line ---
    lines = content.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]

    if not non_empty_lines:
        return ValidationResult(
            valid=False,
            errors=["Label map file contains only whitespace — no class names found"],
        )

    # --- Report summary ---
    logger.info(
        "Label map contains %d class names (from %d total lines)",
        len(non_empty_lines),
        len(lines),
    )

    if len(non_empty_lines) == 1:
        warnings.append(
            "Label map contains only 1 class name — "
            "most detection models have multiple classes"
        )

    return ValidationResult(
        valid=True,
        errors=errors,
        warnings=warnings,
    )
