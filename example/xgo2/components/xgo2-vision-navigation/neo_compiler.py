"""Cloud-side SageMaker Neo compilation script for XGO2 vision model.

Orchestrates Neo compilation jobs: uploads source model to S3, submits
compilation targeting rasp4b (CM4 aarch64 with NEON SIMD), polls for
completion, and downloads the compiled artifact.

Python 3.11+ — runs on developer machine / cloud.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Required fields for CompilationConfig validation
_REQUIRED_FIELDS = (
    "s3_input_uri",
    "s3_output_location",
    "framework",
    "framework_version",
    "input_shape",
    "target_device",
    "role_arn",
    "max_runtime_seconds",
)

# Terminal states for a Neo compilation job
_TERMINAL_STATES = {"COMPLETED", "FAILED", "STOPPED"}

# Polling configuration
_POLL_INTERVAL_SECONDS = 20  # 15-30s range per spec
_MAX_POLL_ATTEMPTS = 120     # 120 * 20s = 2400s max wait


class CompilationError(Exception):
    """Raised when a Neo compilation job fails."""
    pass


@dataclass
class CompilationConfig:
    """Configuration for a SageMaker Neo compilation job.

    Required fields: s3_input_uri, s3_output_location, framework,
    framework_version, input_shape, target_device, role_arn,
    max_runtime_seconds.

    Optional: target_platform overrides target_device when set.
    compiler_options provides custom Neo compiler flags as a JSON string.
    """

    s3_input_uri: str
    s3_output_location: str
    framework: str
    framework_version: str
    input_shape: dict
    target_device: str = "rasp4b"
    target_platform: dict | None = None
    compiler_options: str | None = None
    role_arn: str = ""
    max_runtime_seconds: int = 900

    def __post_init__(self) -> None:
        """Validate that all required fields are present and non-empty."""
        missing: list[str] = []
        for field_name in _REQUIRED_FIELDS:
            value = getattr(self, field_name)
            if value is None or (isinstance(value, (str, dict)) and not value):
                missing.append(field_name)
            elif isinstance(value, int) and value <= 0:
                missing.append(field_name)
        if missing:
            raise ValueError(
                f"CompilationConfig missing required fields: {', '.join(missing)}"
            )


@dataclass
class CompilationResult:
    """Result of a completed Neo compilation job."""

    job_name: str
    status: str
    s3_output_uri: str
    failure_reason: str | None = None


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse an S3 URI into (bucket, key)."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Not a valid S3 URI: {s3_uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def upload_model_to_s3(local_path: str, s3_uri: str) -> str:
    """Upload a model tar.gz to S3 if not already present.

    Args:
        local_path: Path to the local model tar.gz file.
        s3_uri: Target S3 URI (s3://bucket/key).

    Returns:
        The S3 URI of the uploaded (or already-existing) object.

    Raises:
        FileNotFoundError: If local_path does not exist.
        CompilationError: If the S3 upload fails.
    """
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Model file not found: {local_path}")

    bucket, key = _parse_s3_uri(s3_uri)
    s3_client = boto3.client("s3")

    # Check if object already exists
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        logger.info("Model already exists at %s, skipping upload", s3_uri)
        return s3_uri
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code not in ("404", "NoSuchKey"):
            raise CompilationError(
                f"Failed to check S3 object at {s3_uri}: {e}"
            ) from e

    # Upload
    try:
        logger.info("Uploading %s to %s", local_path, s3_uri)
        s3_client.upload_file(local_path, bucket, key)
        logger.info("Upload complete: %s", s3_uri)
        return s3_uri
    except ClientError as e:
        raise CompilationError(f"Failed to upload model to {s3_uri}: {e}") from e


def compile_model(config: CompilationConfig) -> CompilationResult:
    """Submit a SageMaker Neo compilation job and poll until completion.

    Creates a compilation job targeting the configured device or platform,
    polls every ~20 seconds until the job reaches a terminal state.

    Args:
        config: Compilation configuration.

    Returns:
        CompilationResult on COMPLETED status.

    Raises:
        CompilationError: On FAILED, STOPPED, or polling timeout.
    """
    sagemaker_client = boto3.client("sagemaker")
    job_name = f"xgo2-neo-{uuid.uuid4().hex[:8]}"

    # Build InputConfig
    input_config = {
        "S3Uri": config.s3_input_uri,
        "DataInputConfig": json.dumps(config.input_shape),
        "Framework": config.framework.upper(),
        "FrameworkVersion": config.framework_version,
    }

    # Build OutputConfig — use TargetPlatform if specified, else TargetDevice
    output_config: dict = {
        "S3OutputLocation": config.s3_output_location,
    }
    if config.target_platform is not None:
        output_config["TargetPlatform"] = config.target_platform
    else:
        output_config["TargetDevice"] = config.target_device

    if config.compiler_options is not None:
        output_config["CompilerOptions"] = config.compiler_options

    # Submit compilation job
    try:
        logger.info("Creating Neo compilation job: %s", job_name)
        sagemaker_client.create_compilation_job(
            CompilationJobName=job_name,
            RoleArn=config.role_arn,
            InputConfig=input_config,
            OutputConfig=output_config,
            StoppingCondition={
                "MaxRuntimeInSeconds": config.max_runtime_seconds,
            },
        )
        logger.info("Compilation job submitted: %s", job_name)
    except ClientError as e:
        raise CompilationError(
            f"Failed to create compilation job '{job_name}': {e}"
        ) from e

    # Poll for completion
    for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
        time.sleep(_POLL_INTERVAL_SECONDS)

        try:
            response = sagemaker_client.describe_compilation_job(
                CompilationJobName=job_name
            )
        except ClientError as e:
            raise CompilationError(
                f"Failed to describe compilation job '{job_name}': {e}"
            ) from e

        status = response.get("CompilationJobStatus", "UNKNOWN")
        logger.info(
            "Job %s — status: %s (poll %d/%d)",
            job_name, status, attempt, _MAX_POLL_ATTEMPTS,
        )

        if status not in _TERMINAL_STATES:
            continue

        failure_reason = response.get("FailureReason")

        if status == "COMPLETED":
            s3_output_uri = (
                response.get("ModelArtifacts", {}).get("S3ModelArtifacts", "")
            )
            logger.info(
                "Compilation COMPLETED. Output: %s", s3_output_uri
            )
            return CompilationResult(
                job_name=job_name,
                status=status,
                s3_output_uri=s3_output_uri,
                failure_reason=None,
            )

        # FAILED or STOPPED
        logger.error(
            "Compilation %s: %s — reason: %s",
            status, job_name, failure_reason,
        )
        raise CompilationError(
            f"Compilation job '{job_name}' {status}: {failure_reason}"
        )

    # Polling timeout
    raise CompilationError(
        f"Compilation job '{job_name}' timed out after "
        f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS}s"
    )


def download_compiled_model(s3_uri: str, local_dir: str) -> str:
    """Download the compiled model tar.gz from S3 to a local directory.

    Args:
        s3_uri: S3 URI of the compiled model artifact.
        local_dir: Local directory to download into.

    Returns:
        The local file path of the downloaded artifact.

    Raises:
        CompilationError: If the download fails.
    """
    bucket, key = _parse_s3_uri(s3_uri)
    filename = os.path.basename(key) or "compiled_model.tar.gz"
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)

    s3_client = boto3.client("s3")
    try:
        logger.info("Downloading %s to %s", s3_uri, local_path)
        s3_client.download_file(bucket, key, local_path)
        logger.info("Download complete: %s", local_path)
        return local_path
    except ClientError as e:
        raise CompilationError(
            f"Failed to download compiled model from {s3_uri}: {e}"
        ) from e
