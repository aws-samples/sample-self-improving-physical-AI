"""Cloud-side SageMaker Neo compilation script.

Compiles a vision model (e.g., MobileNet-SSD) using SageMaker Neo's
``create_compilation_job`` API, polls for completion, and returns the
compiled model location. Supports both ``TargetDevice`` (rasp3b) and
``TargetPlatform`` (ARM_EABIHF without NEON) configurations.

Python 3.11+. Uses boto3.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields for CompilationConfig validation (Property 1)
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = (
    "s3_input_uri",
    "s3_output_location",
    "framework",
    "framework_version",
    "input_shape",
    "role_arn",
)

# Terminal states for a Neo compilation job
_TERMINAL_STATES = {"COMPLETED", "FAILED", "STOPPED"}

# Default polling interval (seconds) and max attempts
_POLL_INTERVAL = 20  # 15-30 seconds per requirement 1.4
_MAX_POLL_ATTEMPTS = 180  # 180 * 20s = 3600s = 1 hour max


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CompilationError(Exception):
    """Raised when a Neo compilation job fails or encounters an API error."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CompilationConfig:
    """Configuration for a SageMaker Neo compilation job.

    Required fields: ``s3_input_uri``, ``s3_output_location``, ``framework``,
    ``framework_version``, ``input_shape``, ``role_arn``.

    Optional fields: ``target_device`` (default ``rasp3b``),
    ``target_platform``, ``compiler_options``, ``max_runtime_seconds``.

    Raises:
        ValueError: If any required field is missing or empty.
    """

    s3_input_uri: str
    s3_output_location: str
    framework: str
    framework_version: str
    input_shape: dict
    role_arn: str
    max_runtime_seconds: int = 900
    target_device: Optional[str] = "rasp3b"
    target_platform: Optional[dict] = None
    compiler_options: Optional[str] = None

    def __post_init__(self) -> None:
        missing = []
        for name in _REQUIRED_FIELDS:
            value = getattr(self, name, None)
            # Treat None, empty string, and empty dict as missing
            if value is None or value == "" or value == {}:
                missing.append(name)
        if missing:
            raise ValueError(
                f"Missing required CompilationConfig fields: {', '.join(sorted(missing))}"
            )


@dataclass
class CompilationResult:
    """Result of a successful Neo compilation job."""

    job_name: str
    status: str
    s3_output_uri: str
    failure_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key`` into ``(bucket, key)``."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Expected s3:// URI, got: {s3_uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def upload_model_to_s3(local_path: str, s3_uri: str) -> str:
    """Upload a model tar.gz to S3 if not already present.

    Args:
        local_path: Path to the local model tar.gz file.
        s3_uri: Target S3 URI (``s3://bucket/path/to/model.tar.gz``).

    Returns:
        The S3 URI of the (existing or newly uploaded) model.

    Raises:
        FileNotFoundError: If *local_path* does not exist.
        CompilationError: If the S3 upload fails.
    """
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Model file not found: {local_path}")

    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")

    # Check if object already exists
    try:
        s3.head_object(Bucket=bucket, Key=key)
        logger.info("Model already exists at %s — skipping upload", s3_uri)
        return s3_uri
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code not in ("404", "NoSuchKey"):
            raise CompilationError(
                f"Failed to check S3 object {s3_uri}: {exc}"
            ) from exc

    # Upload
    try:
        logger.info("Uploading %s to %s", local_path, s3_uri)
        s3.upload_file(local_path, bucket, key)
        logger.info("Upload complete: %s", s3_uri)
        return s3_uri
    except ClientError as exc:
        raise CompilationError(
            f"Failed to upload model to {s3_uri}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def _build_job_name(framework: str) -> str:
    """Generate a unique compilation job name."""
    timestamp = int(time.time())
    return f"zumi-neo-{framework}-{timestamp}"


def compile_model(config: CompilationConfig) -> CompilationResult:
    """Submit a SageMaker Neo compilation job and poll until completion.

    Args:
        config: A validated :class:`CompilationConfig`.

    Returns:
        A :class:`CompilationResult` on successful compilation.

    Raises:
        CompilationError: On API failure, job FAILED/STOPPED, or polling
            timeout.
    """
    sm = boto3.client("sagemaker")
    job_name = _build_job_name(config.framework)

    # Build the API parameters
    params: dict = {
        "CompilationJobName": job_name,
        "RoleArn": config.role_arn,
        "InputConfig": {
            "S3Uri": config.s3_input_uri,
            "DataInputConfig": json.dumps(config.input_shape),
            "Framework": config.framework.upper(),
            "FrameworkVersion": config.framework_version,
        },
        "OutputConfig": {
            "S3OutputLocation": config.s3_output_location,
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": config.max_runtime_seconds,
        },
    }

    # TargetDevice vs TargetPlatform (Req 1.7, 2.1, 2.2)
    if config.target_platform is not None:
        params["OutputConfig"]["TargetPlatform"] = config.target_platform
        if config.compiler_options is not None:
            params["OutputConfig"]["CompilerOptions"] = config.compiler_options
    elif config.target_device is not None:
        params["OutputConfig"]["TargetDevice"] = config.target_device
        if config.compiler_options is not None:
            params["OutputConfig"]["CompilerOptions"] = config.compiler_options
    else:
        # Default to rasp3b if neither is specified
        params["OutputConfig"]["TargetDevice"] = "rasp3b"

    # Submit the compilation job (Req 1.3)
    try:
        logger.info("Creating compilation job: %s", job_name)
        sm.create_compilation_job(**params)
    except ClientError as exc:
        raise CompilationError(
            f"Failed to create compilation job '{job_name}': {exc}"
        ) from exc

    # Poll until terminal state (Req 1.4)
    for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
        time.sleep(_POLL_INTERVAL)

        try:
            resp = sm.describe_compilation_job(
                CompilationJobName=job_name
            )
        except ClientError as exc:
            raise CompilationError(
                f"Failed to describe compilation job '{job_name}': {exc}"
            ) from exc

        status = resp.get("CompilationJobStatus", "UNKNOWN")
        logger.info(
            "Job %s — status: %s (poll %d/%d)",
            job_name, status, attempt, _MAX_POLL_ATTEMPTS,
        )

        if status not in _TERMINAL_STATES:
            continue

        # Terminal state reached
        failure_reason = resp.get("FailureReason", "")
        s3_output = resp.get("ModelArtifacts", {}).get(
            "S3ModelArtifacts", ""
        )

        if status == "COMPLETED":
            logger.info(
                "Compilation COMPLETED. Output: %s", s3_output
            )
            return CompilationResult(
                job_name=job_name,
                status=status,
                s3_output_uri=s3_output,
                failure_reason=None,
            )

        # FAILED or STOPPED (Req 1.6)
        error_msg = (
            f"Compilation job '{job_name}' {status}: {failure_reason}"
        )
        logger.error(error_msg)
        raise CompilationError(error_msg)

    # Polling timeout
    raise CompilationError(
        f"Compilation job '{job_name}' did not complete within "
        f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL} seconds"
    )
