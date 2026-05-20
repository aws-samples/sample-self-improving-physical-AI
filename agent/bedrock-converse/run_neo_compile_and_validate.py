"""
End-to-end Neo compilation and validation script.

Compiles a model with SageMaker Neo, downloads the result, and validates
both the Neo output and the TFLite fallback model before deployment.

Usage:
    cd robolink-zumi/chatbot
    python run_neo_compile_and_validate.py

Requires:
    - AWS credentials configured (aws configure)
    - NEO_ROLE_ARN environment variable set
    - Source model tar.gz available locally or in S3
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("neo-compile-validate")


def main():
    from neo_compiler import CompilationConfig, compile_model, upload_model_to_s3
    from model_validator import validate_tflite_model, validate_neo_output, validate_label_map

    # --- Configuration ---
    role_arn = os.environ.get("NEO_ROLE_ARN", "")
    if not role_arn:
        log.error("NEO_ROLE_ARN environment variable is not set.")
        log.error("Set it to your SageMaker execution role ARN.")
        sys.exit(1)

    s3_input_uri = os.environ.get(
        "NEO_S3_INPUT",
        "s3://zumi-chatbot-photos/models/mobilenet_ssd_v1.tar.gz",
    )
    s3_output_location = os.environ.get(
        "NEO_S3_OUTPUT",
        "s3://zumi-chatbot-photos/neo-output/",
    )

    log.info("=== Step 1: Neo Compilation ===")
    config = CompilationConfig(
        s3_input_uri=s3_input_uri,
        s3_output_location=s3_output_location,
        framework="tflite",
        framework_version="1.15",
        input_shape={"input": [1, 128, 128, 3]},
        target_device="rasp3b",
        role_arn=role_arn,
        max_runtime_seconds=900,
    )

    log.info("Compilation config:")
    log.info("  S3 input: %s", config.s3_input_uri)
    log.info("  S3 output: %s", config.s3_output_location)
    log.info("  Framework: %s %s", config.framework, config.framework_version)
    log.info("  Target device: %s", config.target_device)
    log.info("  Input shape: %s", config.input_shape)

    try:
        result = compile_model(config)
        log.info("Compilation SUCCEEDED:")
        log.info("  Job name: %s", result.job_name)
        log.info("  Status: %s", result.status)
        log.info("  Output: %s", result.s3_output_uri)
    except Exception as e:
        log.error("Compilation FAILED: %s", e)
        log.info("Continuing with validation of local files only...")

    log.info("")
    log.info("=== Step 2: Model Validation ===")

    # Validate TFLite fallback model
    tflite_path = os.environ.get("TFLITE_MODEL_PATH", "model.tflite")
    if os.path.isfile(tflite_path):
        log.info("Validating TFLite model: %s", tflite_path)
        tflite_result = validate_tflite_model(
            tflite_path, (1, 128, 128, 3)
        )
        log.info("  Valid: %s", tflite_result.valid)
        log.info("  Input shape: %s", tflite_result.input_shape)
        log.info("  Output shapes: %s", tflite_result.output_shapes)
        if tflite_result.errors:
            log.error("  Errors: %s", tflite_result.errors)
        if tflite_result.warnings:
            log.warning("  Warnings: %s", tflite_result.warnings)
    else:
        log.warning("TFLite model not found at %s — skipping validation", tflite_path)

    # Validate Neo output
    neo_tar_path = os.environ.get("NEO_TAR_PATH", "compiled_model.tar.gz")
    if os.path.isfile(neo_tar_path):
        log.info("Validating Neo output: %s", neo_tar_path)
        neo_result = validate_neo_output(neo_tar_path)
        log.info("  Valid: %s", neo_result.valid)
        if neo_result.errors:
            log.error("  Errors: %s", neo_result.errors)
        if neo_result.warnings:
            log.warning("  Warnings: %s", neo_result.warnings)
    else:
        log.warning("Neo output not found at %s — skipping validation", neo_tar_path)

    # Validate label map
    labels_path = os.environ.get("LABELS_PATH", "labels.txt")
    if os.path.isfile(labels_path):
        log.info("Validating label map: %s", labels_path)
        labels_result = validate_label_map(labels_path)
        log.info("  Valid: %s", labels_result.valid)
        if labels_result.errors:
            log.error("  Errors: %s", labels_result.errors)
        if labels_result.warnings:
            log.warning("  Warnings: %s", labels_result.warnings)
    else:
        log.warning("Label map not found at %s — skipping validation", labels_path)

    log.info("")
    log.info("=== Validation Complete ===")


if __name__ == "__main__":
    main()
