"""Cloud-side OTA trigger for Zumi robots via AWS IoT Jobs.

This module provides utilities for building and parsing v1 job documents,
triggering OTA updates, and querying job status via the AWS IoT Jobs API.
"""

import hashlib
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

import config

# Version constant for the job document schema
JOB_DOCUMENT_VERSION = "1.0"

# Required top-level fields in a job document
_REQUIRED_TOP_LEVEL_FIELDS = {"version", "operation", "artifacts", "post_action"}

# Required fields in each artifact descriptor
_REQUIRED_ARTIFACT_FIELDS = {"url", "target_path", "file_size", "sha256"}

# Required fields in the optional codesign object
_REQUIRED_CODESIGN_FIELDS = {"signature", "signing_profile", "algorithm"}


class OTATriggerError(Exception):
    """Raised when an OTA trigger operation fails (S3, IoT, Signer)."""


def build_failed_status_detail(reason: str, step: str, timestamp: str) -> dict:
    """Build a FAILED job status detail dict.

    Args:
        reason: Non-empty string describing why the job failed.
        step: Non-empty string identifying the step that failed.
        timestamp: ISO-8601 formatted timestamp string.

    Returns:
        A status detail dict with ``reason``, ``step``, ``timestamp``,
        and ``rollback_performed`` fields.

    Raises:
        ValueError: If *reason* or *step* is empty, or *timestamp* is
            not a valid ISO-8601 string.
    """
    if not reason:
        raise ValueError("reason must be a non-empty string")
    if not step:
        raise ValueError("step must be a non-empty string")
    # Validate ISO-8601 by attempting to parse
    from datetime import datetime, timezone
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError(
            f"timestamp must be a valid ISO-8601 string, got: {timestamp!r}"
        )
    return {
        "reason": reason,
        "step": step,
        "timestamp": timestamp,
        "rollback_performed": True,
    }


def build_succeeded_status_detail(
    files_updated: list,
    artifact_sha256: str,
    timestamp: str,
) -> dict:
    """Build a SUCCEEDED job status detail dict.

    Args:
        files_updated: Non-empty list of file path strings that were updated.
        artifact_sha256: Non-empty hex-encoded SHA-256 digest string.
        timestamp: ISO-8601 formatted timestamp string.

    Returns:
        A status detail dict with ``version``, ``files_updated``,
        ``artifact_sha256``, and ``timestamp`` fields.

    Raises:
        ValueError: If *files_updated* is empty, *artifact_sha256* is empty,
            or *timestamp* is not a valid ISO-8601 string.
    """
    if not files_updated:
        raise ValueError("files_updated must be a non-empty list")
    if not artifact_sha256:
        raise ValueError("artifact_sha256 must be a non-empty string")
    from datetime import datetime, timezone
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError(
            f"timestamp must be a valid ISO-8601 string, got: {timestamp!r}"
        )
    return {
        "version": JOB_DOCUMENT_VERSION,
        "files_updated": list(files_updated),
        "artifact_sha256": artifact_sha256,
        "timestamp": timestamp,
    }


def build_job_document(
    artifacts: list,
    post_action: str = "restart_service",
) -> dict:
    """Build a v1 job document dict.

    Args:
        artifacts: List of artifact descriptor dicts. Each must contain
            ``url``, ``target_path``, ``file_size``, and ``sha256``.
            An optional ``codesign`` dict may also be present.
        post_action: Action to perform after applying the update
            (default: ``"restart_service"``).

    Returns:
        A job document dict conforming to the v1 schema.

    Raises:
        ValueError: If *artifacts* is empty or any descriptor is missing
            required fields.
    """
    if not artifacts:
        raise ValueError("artifacts list must not be empty")

    validated_artifacts = []
    for idx, artifact in enumerate(artifacts):
        missing = _REQUIRED_ARTIFACT_FIELDS - set(artifact.keys())
        if missing:
            raise ValueError(
                f"artifact[{idx}] is missing required fields: "
                f"{', '.join(sorted(missing))}"
            )
        entry: dict = {
            "url": artifact["url"],
            "target_path": artifact["target_path"],
            "file_size": artifact["file_size"],
            "sha256": artifact["sha256"],
        }
        if "codesign" in artifact:
            entry["codesign"] = artifact["codesign"]
        validated_artifacts.append(entry)

    return {
        "version": JOB_DOCUMENT_VERSION,
        "operation": "update_files",
        "artifacts": validated_artifacts,
        "post_action": post_action,
    }


def parse_job_document(raw: dict) -> dict:
    """Validate and parse a job document.

    Checks that all required top-level fields are present, that the schema
    version is supported, and that every artifact descriptor contains the
    required fields.  The optional ``codesign`` object, when present, is
    also validated for required sub-fields.

    Args:
        raw: A dict representing the job document (e.g. from ``json.loads``).

    Returns:
        The validated job document dict (same structure as *raw*).

    Raises:
        ValueError: If the document has an unsupported version, is missing
            required fields, or contains invalid artifact descriptors.
    """
    if not isinstance(raw, dict):
        raise ValueError("job document must be a dict")

    # --- top-level required fields ---
    missing_top = _REQUIRED_TOP_LEVEL_FIELDS - set(raw.keys())
    if missing_top:
        raise ValueError(
            f"job document is missing required fields: "
            f"{', '.join(sorted(missing_top))}"
        )

    # --- version check ---
    if raw["version"] != JOB_DOCUMENT_VERSION:
        raise ValueError(
            f"unsupported job document version: {raw['version']!r} "
            f"(expected {JOB_DOCUMENT_VERSION!r})"
        )

    # --- artifacts validation ---
    artifacts = raw["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("'artifacts' must be a list")
    if len(artifacts) == 0:
        raise ValueError("'artifacts' list must not be empty")

    for idx, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact[{idx}] must be a dict")

        missing_art = _REQUIRED_ARTIFACT_FIELDS - set(artifact.keys())
        if missing_art:
            raise ValueError(
                f"artifact[{idx}] is missing required fields: "
                f"{', '.join(sorted(missing_art))}"
            )

        # --- optional codesign validation ---
        if "codesign" in artifact:
            codesign = artifact["codesign"]
            if not isinstance(codesign, dict):
                raise ValueError(f"artifact[{idx}].codesign must be a dict")
            missing_cs = _REQUIRED_CODESIGN_FIELDS - set(codesign.keys())
            if missing_cs:
                raise ValueError(
                    f"artifact[{idx}].codesign is missing required fields: "
                    f"{', '.join(sorted(missing_cs))}"
                )

    return raw


def _sign_artifact(
    s3_bucket: str,
    artifact_key: str,
    signing_profile: str,
) -> dict:
    """Sign an S3 artifact using AWS Signer.

    Starts a signing job, polls until completion, and returns the
    signature metadata for inclusion in the job document's ``codesign``
    object.

    Args:
        s3_bucket: S3 bucket containing the artifact.
        artifact_key: S3 key of the artifact to sign.
        signing_profile: AWS Signer profile name.

    Returns:
        A dict with ``signature``, ``signing_profile``, and ``algorithm``
        keys suitable for the artifact descriptor's ``codesign`` field.

    Raises:
        OTATriggerError: If the signing job fails or times out.
    """
    signer_client = boto3.client("signer", region_name=config.IOT_REGION)

    # Destination prefix: place signed artifact next to the original
    dest_prefix = artifact_key.rsplit("/", 1)[0] + "/signed-"

    try:
        start_resp = signer_client.start_signing_job(
            source={
                "s3": {
                    "bucketName": s3_bucket,
                    "key": artifact_key,
                }
            },
            destination={
                "s3": {
                    "bucketName": s3_bucket,
                    "prefix": dest_prefix,
                }
            },
            profileName=signing_profile,
        )
    except ClientError as exc:
        raise OTATriggerError(
            f"Failed to start signing job: {exc}"
        ) from exc

    job_id = start_resp["jobId"]

    # Poll for signing job completion
    max_attempts = 60
    poll_interval = 2  # seconds
    for _ in range(max_attempts):
        try:
            desc_resp = signer_client.describe_signing_job(jobId=job_id)
        except ClientError as exc:
            raise OTATriggerError(
                f"Failed to describe signing job {job_id}: {exc}"
            ) from exc

        status = desc_resp.get("status")
        if status == "Succeeded":
            # Extract the signed object key to read the signature
            signed_object = desc_resp.get("signedObject", {}).get("s3", {})
            signed_key = signed_object.get("key", "")

            # Read the signature from the signed artifact metadata
            # AWS Signer stores the signature; we retrieve it from the
            # signing job description.
            signature_b64 = desc_resp.get("signature", "")

            # If the API doesn't return a top-level signature field,
            # download the .sig sidecar or use the signed object key
            # as evidence of successful signing.
            if not signature_b64:
                # Use the signed object S3 key as a reference; the
                # actual signature is embedded in the signed artifact.
                # For our job document, we record the signed key as the
                # signature reference.
                s3_client = boto3.client("s3", region_name=config.S3_REGION)
                try:
                    sig_resp = s3_client.get_object(
                        Bucket=s3_bucket,
                        Key=signed_key,
                    )
                    import base64
                    signature_bytes = sig_resp["Body"].read()
                    signature_b64 = base64.b64encode(signature_bytes).decode("utf-8")
                except ClientError as exc:
                    raise OTATriggerError(
                        f"Failed to retrieve signed artifact from S3: {exc}"
                    ) from exc

            return {
                "signature": signature_b64,
                "signing_profile": signing_profile,
                "algorithm": "RSA-SHA256",
            }
        elif status == "Failed":
            reason = desc_resp.get("statusReason", "Unknown reason")
            raise OTATriggerError(
                f"Signing job {job_id} failed: {reason}"
            )

        time.sleep(poll_interval)

    raise OTATriggerError(
        f"Signing job {job_id} timed out after {max_attempts * poll_interval}s"
    )


def _compute_sha256(file_path: str) -> str:
    """Compute the SHA-256 hex digest of a local file.

    Args:
        file_path: Path to the file on disk.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def trigger_ota(
    file_path: str,
    thing_name: str,
    target_path: str = "/home/pi/zumi-iot/zumi_iot.py",
    post_action: str = "restart_service",
    signing_profile: str | None = None,
) -> dict:
    """Upload artifact, create job document, and create an IoT Job.

    Steps:
        1. Compute SHA-256 of the local file.
        2. Upload artifact to ``s3://{bucket}/ota/{thing_name}/{ts}-{hash_prefix}/{filename}``.
        3. Generate a presigned GET URL for the artifact.
        4. If a signing profile is available, sign the artifact with AWS Signer.
        5. Build the job document JSON and upload it to S3.
        6. Call ``iot.create_job()`` with the job document URL.

    Args:
        file_path: Path to the local artifact file.
        thing_name: AWS IoT thing name to target.
        target_path: Absolute path on the device where the artifact
            should be placed.
        post_action: Action to perform after applying the update
            (default: ``"restart_service"``).
        signing_profile: Optional AWS Signer profile name. If ``None``,
            falls back to ``config.OTA_SIGNING_PROFILE``. If that is
            also empty, signing is skipped.

    Returns:
        A dict with ``job_id`` and ``job_arn`` keys.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        OTATriggerError: On S3 upload failure, signing failure, or
            ``create_job`` API failure.
    """
    # Validate local file exists
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Artifact file not found: {file_path}")

    # Step 1: Compute SHA-256
    file_hash = _compute_sha256(file_path)
    hash_prefix = file_hash[:8]
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    # Build the S3 key for the artifact
    timestamp = str(int(time.time()))
    s3_prefix = config.OTA_S3_PREFIX
    artifact_key = f"{s3_prefix}/{thing_name}/{timestamp}-{hash_prefix}/{filename}"

    bucket = config.S3_BUCKET
    s3_region = config.S3_REGION

    # Create boto3 clients
    s3_client = boto3.client("s3", region_name=s3_region)
    iot_client = boto3.client("iot", region_name=config.IOT_REGION)

    # Step 2: Upload artifact to S3
    try:
        s3_client.upload_file(file_path, bucket, artifact_key)
    except ClientError as exc:
        raise OTATriggerError(
            f"Failed to upload artifact to S3: {exc}"
        ) from exc

    # Step 3: Generate presigned GET URL
    presign_expiry = config.OTA_PRESIGN_EXPIRY
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": artifact_key},
        ExpiresIn=presign_expiry,
    )

    # Step 3.5: Sign artifact with AWS Signer if a profile is available
    # Resolve signing profile: explicit parameter > config default
    effective_signing_profile = signing_profile
    if effective_signing_profile is None:
        cfg_profile = config.OTA_SIGNING_PROFILE
        if cfg_profile:  # non-empty string
            effective_signing_profile = cfg_profile

    codesign = None
    if effective_signing_profile:
        # Sign the artifact — raises OTATriggerError on failure,
        # which prevents the IoT Job from being created (Req 12.4).
        codesign = _sign_artifact(bucket, artifact_key, effective_signing_profile)

    # Step 4: Build job document and upload to S3
    artifact_descriptor: dict = {
        "url": presigned_url,
        "target_path": target_path,
        "file_size": file_size,
        "sha256": file_hash,
    }
    if codesign is not None:
        artifact_descriptor["codesign"] = codesign
    job_document = build_job_document([artifact_descriptor], post_action=post_action)
    job_document_json = json.dumps(job_document)

    job_doc_key = f"{s3_prefix}/{thing_name}/{timestamp}-{hash_prefix}/job-document.json"
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=job_doc_key,
            Body=job_document_json,
            ContentType="application/json",
        )
    except ClientError as exc:
        raise OTATriggerError(
            f"Failed to upload job document to S3: {exc}"
        ) from exc

    # Build the job document URL for create_job
    job_document_url = f"https://{bucket}.s3.{s3_region}.amazonaws.com/{job_doc_key}"

    # Step 5: Create IoT Job — use inline document so the job document
    # is included in the notify-next MQTT notification payload.
    job_id = f"ota-{thing_name}-{timestamp}"
    try:
        response = iot_client.create_job(
            jobId=job_id,
            targets=[f"arn:aws:iot:{config.IOT_REGION}:{_get_account_id()}:thing/{thing_name}"],
            document=job_document_json,
            targetSelection="SNAPSHOT",
        )
    except ClientError as exc:
        raise OTATriggerError(
            f"Failed to create IoT Job: {exc}"
        ) from exc

    return {
        "job_id": response.get("jobId", job_id),
        "job_arn": response["jobArn"],
    }


def get_job_status(job_id: str, thing_name: str) -> dict:
    """Query the current execution status of an IoT Job.

    Uses the boto3 ``iot`` client's ``describe_job_execution`` API to
    retrieve the execution status for a specific job on a specific thing.

    Args:
        job_id: The IoT Job ID to query.
        thing_name: The AWS IoT thing name the job targets.

    Returns:
        A dict with the following keys:

        - ``status`` (str): Job execution status string (e.g.
          ``"QUEUED"``, ``"IN_PROGRESS"``, ``"SUCCEEDED"``, ``"FAILED"``).
        - ``status_detail`` (dict): Parsed status details. If the API
          response contains a ``statusDetails`` map, the values are
          JSON-decoded where possible; otherwise the raw string map is
          returned. Returns an empty dict when no details are present.
        - ``started_at`` (str | None): ISO-8601 timestamp of when
          execution started, or ``None`` if not yet started.
        - ``last_updated_at`` (str | None): ISO-8601 timestamp of the
          most recent status update, or ``None`` if unavailable.
        - ``queued_at`` (str | None): ISO-8601 timestamp of when the
          execution was queued, or ``None`` if unavailable.

    Raises:
        OTATriggerError: If the ``describe_job_execution`` API call fails.
    """
    iot_client = boto3.client("iot", region_name=config.IOT_REGION)

    try:
        response = iot_client.describe_job_execution(
            jobId=job_id,
            thingName=thing_name,
        )
    except ClientError as exc:
        raise OTATriggerError(
            f"Failed to describe job execution: {exc}"
        ) from exc

    execution = response.get("execution", {})

    # Parse status details — the API returns a dict of string→string.
    # Attempt to JSON-decode each value for richer structure.
    raw_details = execution.get("statusDetails", {}) or {}
    status_detail: dict = {}
    for key, value in raw_details.items():
        try:
            status_detail[key] = json.loads(value)
        except (ValueError, TypeError):
            status_detail[key] = value

    def _ts_to_iso(dt) -> str | None:
        """Convert a datetime object to an ISO-8601 string, or None."""
        if dt is None:
            return None
        return dt.isoformat()

    return {
        "status": execution.get("status", "UNKNOWN"),
        "status_detail": status_detail,
        "started_at": _ts_to_iso(execution.get("startedAt")),
        "last_updated_at": _ts_to_iso(execution.get("lastUpdatedAt")),
        "queued_at": _ts_to_iso(execution.get("queuedAt")),
    }


def _get_account_id() -> str:
    """Retrieve the current AWS account ID via STS.

    Returns:
        The 12-digit AWS account ID string.
    """
    sts = boto3.client("sts")
    return sts.get_caller_identity()["Account"]
