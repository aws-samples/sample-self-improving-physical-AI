"""
Deploy model files to Zumi via OTA pipeline.

Triggers a multi-artifact OTA job with the compiled model, fallback
TFLite model, and label map. Then polls for job completion.

Usage:
    cd robolink-zumi/chatbot
    python run_model_deploy.py

Requires:
    - AWS credentials configured
    - compiled_model.tar.gz, model.tflite, labels.txt in current directory
      (or set via environment variables)
"""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("model-deploy")


def main():
    from model_deployer import deploy_model
    from ota_trigger import get_job_status

    # --- Configuration ---
    compiled_tar = os.environ.get("COMPILED_TAR_PATH", "compiled_model.tar.gz")
    fallback_tflite = os.environ.get("TFLITE_MODEL_PATH", "model.tflite")
    label_map = os.environ.get("LABELS_PATH", "labels.txt")
    thing_name = os.environ.get("THING_NAME", "robolink-zumi")
    target_dir = os.environ.get("TARGET_MODEL_DIR", "/home/pi/models/")

    # Validate files exist
    for path in [compiled_tar, fallback_tflite, label_map]:
        if not os.path.isfile(path):
            log.error("File not found: %s", path)
            sys.exit(1)

    log.info("=== Model Deployment ===")
    log.info("  Compiled model: %s", compiled_tar)
    log.info("  Fallback TFLite: %s", fallback_tflite)
    log.info("  Label map: %s", label_map)
    log.info("  Thing name: %s", thing_name)
    log.info("  Target dir: %s", target_dir)

    # --- Deploy ---
    log.info("Triggering OTA deployment...")
    try:
        result = deploy_model(
            compiled_tar_path=compiled_tar,
            fallback_tflite_path=fallback_tflite,
            label_map_path=label_map,
            thing_name=thing_name,
            target_model_dir=target_dir,
        )
    except Exception as e:
        log.error("Deployment failed: %s", e)
        sys.exit(1)

    job_id = result["job_id"]
    job_arn = result["job_arn"]
    log.info("OTA Job created:")
    log.info("  Job ID: %s", job_id)
    log.info("  Job ARN: %s", job_arn)

    # --- Poll for completion ---
    log.info("Polling job status (max 150 seconds)...")
    for i in range(30):
        time.sleep(5)
        try:
            status = get_job_status(job_id, thing_name)
        except Exception as e:
            log.warning("Status poll failed: %s", e)
            continue

        job_status = status["status"]
        log.info(
            "  [%d/30] Status: %s (last_updated: %s)",
            i + 1, job_status, status.get("last_updated_at", "N/A")
        )

        if job_status in ("SUCCEEDED", "FAILED", "REJECTED", "REMOVED"):
            break

    log.info("")
    log.info("=== Final Status ===")
    log.info("  Job ID: %s", job_id)
    log.info("  Status: %s", job_status)
    if status.get("status_detail"):
        log.info("  Details: %s", status["status_detail"])

    if job_status == "SUCCEEDED":
        log.info("Model deployment SUCCEEDED!")
        log.info("")
        log.info("Verify on device:")
        log.info("  ssh pi@10.131.141.40 'ls -la /home/pi/models/'")
    else:
        log.warning("Model deployment did not succeed. Status: %s", job_status)
        log.info("Check device logs:")
        log.info("  ssh pi@10.131.141.40 'sudo journalctl -u zumi-iot --no-pager -n 50'")

    log.info("")
    log.info("To clean up the IoT Job:")
    log.info("  aws iot delete-job --job-id %s --force", job_id)


if __name__ == "__main__":
    main()
