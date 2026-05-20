"""Cloud-side SageMaker training pipeline for XGO2 depth estimation model.

Orchestrates SageMaker training jobs: submits a training job for a
lightweight monocular depth estimation model (e.g. MiDaS small), polls
for completion, and extracts the trained model artifact URI from S3.

Includes a TFLite fallback export path for when Neo compilation of the
trained model fails — the model can be exported directly as a TFLite
file for use with TFLite_Runtime on the device.

Python 3.11+ — runs on developer machine / cloud.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Required fields for TrainingConfig validation
_REQUIRED_FIELDS = (
    "s3_training_data_uri",
    "s3_output_location",
    "role_arn",
)

# Terminal states for a SageMaker training job
_TERMINAL_STATES = {"Completed", "Failed", "Stopped"}

# Polling configuration
_POLL_INTERVAL_SECONDS = 30
_MAX_POLL_ATTEMPTS = 120  # 120 * 30s = 3600s max wait


class TrainingError(Exception):
    """Raised when a SageMaker training job fails."""
    pass


@dataclass
class TrainingConfig:
    """Configuration for a SageMaker depth model training job.

    Required fields: s3_training_data_uri, s3_output_location, role_arn.

    Optional: instance_type, hyperparameters, max_runtime_seconds,
    training_image (ECR URI for the training container),
    poll_interval_seconds, max_poll_attempts.
    """

    s3_training_data_uri: str
    s3_output_location: str
    instance_type: str = "ml.g4dn.xlarge"
    role_arn: str = ""
    hyperparameters: dict[str, str] = field(default_factory=lambda: {
        "learning_rate": "0.0001",
        "epochs": "50",
        "batch_size": "16",
    })
    max_runtime_seconds: int = 3600
    training_image: str = ""
    poll_interval_seconds: int = _POLL_INTERVAL_SECONDS
    max_poll_attempts: int = _MAX_POLL_ATTEMPTS

    def __post_init__(self) -> None:
        """Validate that all required fields are present and non-empty."""
        missing: list[str] = []
        for field_name in _REQUIRED_FIELDS:
            value = getattr(self, field_name)
            if value is None or (isinstance(value, str) and not value):
                missing.append(field_name)
        if missing:
            raise ValueError(
                f"TrainingConfig missing required fields: {', '.join(missing)}"
            )


@dataclass
class TrainingResult:
    """Result of a completed SageMaker training job."""

    job_name: str
    status: str
    s3_model_artifact_uri: str
    failure_reason: str | None = None


def train_depth_model(
    config: TrainingConfig,
    sagemaker_client=None,
) -> TrainingResult:
    """Submit a SageMaker training job and poll until completion.

    Creates a training job for the depth estimation model, polls at a
    configurable interval until the job reaches a terminal state, and
    returns the result with the S3 model artifact URI.

    Args:
        config: Training configuration.
        sagemaker_client: Optional pre-configured SageMaker client
            (useful for testing). If None, creates a new boto3 client.

    Returns:
        TrainingResult on Completed status.

    Raises:
        TrainingError: On Failed, Stopped, or polling timeout.
    """
    if sagemaker_client is None:
        sagemaker_client = boto3.client("sagemaker")

    job_name = f"xgo2-depth-{uuid.uuid4().hex[:8]}"

    # Build training job parameters
    training_params: dict = {
        "TrainingJobName": job_name,
        "RoleArn": config.role_arn,
        "InputDataConfig": [
            {
                "ChannelName": "training",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": config.s3_training_data_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            }
        ],
        "OutputDataConfig": {
            "S3OutputPath": config.s3_output_location,
        },
        "ResourceConfig": {
            "InstanceType": config.instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": 50,
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": config.max_runtime_seconds,
        },
        "HyperParameters": config.hyperparameters,
    }

    # Add training image if specified
    if config.training_image:
        training_params["AlgorithmSpecification"] = {
            "TrainingImage": config.training_image,
            "TrainingInputMode": "File",
        }

    # Submit training job
    try:
        logger.info("Creating SageMaker training job: %s", job_name)
        sagemaker_client.create_training_job(**training_params)
        logger.info("Training job submitted: %s", job_name)
    except ClientError as e:
        raise TrainingError(
            f"Failed to create training job '{job_name}': {e}"
        ) from e

    # Poll for completion
    for attempt in range(1, config.max_poll_attempts + 1):
        time.sleep(config.poll_interval_seconds)

        try:
            response = sagemaker_client.describe_training_job(
                TrainingJobName=job_name
            )
        except ClientError as e:
            raise TrainingError(
                f"Failed to describe training job '{job_name}': {e}"
            ) from e

        status = response.get("TrainingJobStatus", "Unknown")
        logger.info(
            "Job %s — status: %s (poll %d/%d)",
            job_name, status, attempt, config.max_poll_attempts,
        )

        if status not in _TERMINAL_STATES:
            continue

        failure_reason = response.get("FailureReason")

        if status == "Completed":
            s3_model_artifact_uri = (
                response.get("ModelArtifacts", {}).get("S3ModelArtifacts", "")
            )
            logger.info(
                "Training COMPLETED. Model artifact: %s",
                s3_model_artifact_uri,
            )
            return TrainingResult(
                job_name=job_name,
                status=status,
                s3_model_artifact_uri=s3_model_artifact_uri,
                failure_reason=None,
            )

        # Failed or Stopped
        logger.error(
            "Training %s: %s — reason: %s",
            status, job_name, failure_reason,
        )
        raise TrainingError(
            f"Training job '{job_name}' {status}: {failure_reason}"
        )

    # Polling timeout
    raise TrainingError(
        f"Training job '{job_name}' timed out after "
        f"{config.max_poll_attempts * config.poll_interval_seconds}s"
    )


def export_tflite_fallback(
    s3_model_artifact_uri: str,
    output_dir: str,
    s3_client=None,
) -> str:
    """Download trained model and export as TFLite for fallback inference.

    This is the fallback path when Neo compilation fails. Downloads the
    trained model artifact from S3, extracts it, and converts to TFLite
    format for direct use with TFLite_Runtime on the device.

    Args:
        s3_model_artifact_uri: S3 URI of the trained model tar.gz artifact.
        output_dir: Local directory to save the TFLite model.
        s3_client: Optional pre-configured S3 client (useful for testing).
            If None, creates a new boto3 client.

    Returns:
        Local path to the exported TFLite model file.

    Raises:
        TrainingError: If download or conversion fails.
    """
    import os
    import tarfile
    import tempfile
    from urllib.parse import urlparse

    if s3_client is None:
        s3_client = boto3.client("s3")

    # Parse S3 URI
    parsed = urlparse(s3_model_artifact_uri)
    if parsed.scheme != "s3":
        raise TrainingError(
            f"Not a valid S3 URI: {s3_model_artifact_uri}"
        )
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    # Download model artifact
    os.makedirs(output_dir, exist_ok=True)
    local_tar_path = os.path.join(output_dir, "model.tar.gz")

    try:
        logger.info(
            "Downloading model artifact from %s", s3_model_artifact_uri
        )
        s3_client.download_file(bucket, key, local_tar_path)
        logger.info("Download complete: %s", local_tar_path)
    except ClientError as e:
        raise TrainingError(
            f"Failed to download model artifact from "
            f"{s3_model_artifact_uri}: {e}"
        ) from e

    # Extract tar.gz
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(local_tar_path, "r:gz") as tar:
                tar.extractall(tmpdir)

            # Look for an existing .tflite file in the archive
            tflite_files = []
            for root, _dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.endswith(".tflite"):
                        tflite_files.append(os.path.join(root, f))

            if tflite_files:
                # Use the first .tflite file found
                import shutil
                tflite_output = os.path.join(output_dir, "depth_model.tflite")
                shutil.copy2(tflite_files[0], tflite_output)
                logger.info(
                    "TFLite model extracted: %s", tflite_output
                )
                return tflite_output

            # No .tflite file found — look for a SavedModel or .pb and convert
            saved_model_dirs = []
            for root, dirs, files in os.walk(tmpdir):
                if "saved_model.pb" in files:
                    saved_model_dirs.append(root)

            if saved_model_dirs:
                tflite_output = os.path.join(
                    output_dir, "depth_model.tflite"
                )
                _convert_saved_model_to_tflite(
                    saved_model_dirs[0], tflite_output
                )
                logger.info(
                    "TFLite model converted from SavedModel: %s",
                    tflite_output,
                )
                return tflite_output

            raise TrainingError(
                "No .tflite file or SavedModel found in model artifact. "
                "Cannot export TFLite fallback."
            )

    except tarfile.TarError as e:
        raise TrainingError(
            f"Failed to extract model artifact: {e}"
        ) from e


def _convert_saved_model_to_tflite(
    saved_model_dir: str,
    output_path: str,
) -> None:
    """Convert a TensorFlow SavedModel to TFLite format.

    Args:
        saved_model_dir: Path to the SavedModel directory.
        output_path: Path to write the .tflite file.

    Raises:
        TrainingError: If conversion fails.
    """
    try:
        import tensorflow as tf

        converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        tflite_model = converter.convert()

        with open(output_path, "wb") as f:
            f.write(tflite_model)
    except ImportError:
        raise TrainingError(
            "TensorFlow is required for SavedModel-to-TFLite conversion. "
            "Install with: pip install tensorflow"
        )
    except Exception as e:
        raise TrainingError(
            f"Failed to convert SavedModel to TFLite: {e}"
        ) from e
