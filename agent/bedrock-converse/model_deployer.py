"""Cloud-side model deployer for Zumi robots via AWS IoT Jobs.

Packages compiled model, fallback TFLite model, and label map into a
multi-artifact OTA job with ``post_action='extract_model'``.  Reuses
helpers from :mod:`ota_trigger` for SHA-256 hashing and job-document
construction, but handles the three-artifact upload and IoT Job creation
directly (the existing ``trigger_ota`` only supports a single artifact).
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

import config
from ota_trigger import OTATriggerError, _compute_sha256, build_job_document


class ModelDeployError(Exception):
    """Raised when a model deployment operation fails."""


def _get_account_id() -> str:
    """Retrieve the current AWS account ID via STS."""
    sts = boto3.client("sts")
    return sts.get_caller_identity()["Account"]


def deploy_model(
    compiled_tar_path: str,
    fallback_tflite_path: str,
    label_map_path: str,
    thing_name: str,
    target_model_dir: str = "/home/pi/models/",
) -> dict:
    """Deploy model files to device via OTA pipeline.

    Creates a multi-artifact OTA job with three artifacts (compiled model
    tar.gz, fallback TFLite model, and label map) and
    ``post_action='extract_model'``.

    Args:
        compiled_tar_path: Local path to the Neo-compiled model tar.gz.
        fallback_tflite_path: Local path to the fallback TFLite model.
        label_map_path: Local path to the label map text file.
        thing_name: AWS IoT thing name to target.
        target_model_dir: Directory on the device where model files are
            placed (default ``/home/pi/models/``).

    Returns:
        A dict with ``job_id`` and ``job_arn`` keys.

    Raises:
        FileNotFoundError: If any of the three local files do not exist.
        ModelDeployError: On S3 upload failure, presigned-URL generation
            failure, or IoT ``create_job`` API failure.
    """
    file_paths = [compiled_tar_path, fallback_tflite_path, label_map_path]

    # --- Validate all files exist ---
    for path in file_paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Model file not found: {path}")

    # --- Step 1: Compute SHA-256 for each file ---
    hashes: dict[str, str] = {}
    for path in file_paths:
        hashes[path] = _compute_sha256(path)

    # --- Prepare S3 keys ---
    timestamp = str(int(time.time()))
    s3_prefix = config.OTA_S3_PREFIX
    s3_folder = f"{s3_prefix}/{thing_name}/{timestamp}"
    bucket = config.S3_BUCKET

    s3_client = boto3.client("s3", region_name=config.S3_REGION)
    iot_client = boto3.client("iot", region_name=config.IOT_REGION)

    artifact_descriptors: list[dict] = []

    for path in file_paths:
        filename = os.path.basename(path)
        s3_key = f"{s3_folder}/{filename}"
        file_size = os.path.getsize(path)
        file_hash = hashes[path]

        # --- Step 2: Upload to S3 ---
        try:
            s3_client.upload_file(path, bucket, s3_key)
        except ClientError as exc:
            raise ModelDeployError(
                f"Failed to upload {filename} to S3: {exc}"
            ) from exc

        # --- Step 3: Generate presigned GET URL ---
        try:
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": s3_key},
                ExpiresIn=config.OTA_PRESIGN_EXPIRY,
            )
        except ClientError as exc:
            raise ModelDeployError(
                f"Failed to generate presigned URL for {filename}: {exc}"
            ) from exc

        # --- Build artifact descriptor ---
        target_path = os.path.join(target_model_dir, filename)
        artifact_descriptors.append({
            "url": presigned_url,
            "target_path": target_path,
            "file_size": file_size,
            "sha256": file_hash,
        })

    # --- Step 4 & 5: Build job document with extract_model post-action ---
    try:
        job_document = build_job_document(
            artifacts=artifact_descriptors,
            post_action="extract_model",
        )
    except ValueError as exc:
        raise ModelDeployError(
            f"Failed to build job document: {exc}"
        ) from exc

    job_document_json = json.dumps(job_document)

    # --- Upload job document to S3 ---
    job_doc_key = f"{s3_folder}/job-document.json"
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=job_doc_key,
            Body=job_document_json,
            ContentType="application/json",
        )
    except ClientError as exc:
        raise ModelDeployError(
            f"Failed to upload job document to S3: {exc}"
        ) from exc

    # --- Step 6: Create IoT Job with inline document ---
    job_id = f"model-deploy-{thing_name}-{timestamp}"
    try:
        response = iot_client.create_job(
            jobId=job_id,
            targets=[
                f"arn:aws:iot:{config.IOT_REGION}:{_get_account_id()}:thing/{thing_name}"
            ],
            document=job_document_json,
            targetSelection="SNAPSHOT",
        )
    except ClientError as exc:
        raise ModelDeployError(
            f"Failed to create IoT Job: {exc}"
        ) from exc

    return {
        "job_id": response.get("jobId", job_id),
        "job_arn": response["jobArn"],
    }
