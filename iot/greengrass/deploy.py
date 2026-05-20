"""Cloud-side Greengrass deployment script for XGO2 VisionNavigation component.

Uploads artifacts to S3, creates or updates the Greengrass component version,
triggers a deployment to the xgo-robodog core device, and polls until the
deployment reaches a terminal state.

Python 3.11+ — runs on developer machine / cloud.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Component identity
_COMPONENT_NAME = "com.xgo.VisionNavigation"

# Required artifact filenames that must exist in model_dir before upload
_REQUIRED_ARTIFACTS = (
    "main.py",
    "vision_inference.py",
    "nav_controller.py",
    "bedrock_reasoner.py",
    "lcd_display.py",
    "requirements.txt",
    "labels.txt",
    "model.zip",
    "grip_controller.py",
    "depth_estimator.py",
    "coordinate_mapper.py",
    "grip_reasoner.py",
    "depth_model.zip",
)

# Deployment polling configuration
_POLL_INTERVAL_SECONDS = 20   # 15-30s range per spec
_MAX_POLL_ATTEMPTS = 90       # 90 * 20s = 1800s max wait

# Terminal deployment states
_TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELED"}


class DeploymentError(Exception):
    """Raised when a Greengrass deployment operation fails."""
    pass


def _verify_artifacts(model_dir: str) -> list[str]:
    """Verify all required artifacts exist locally.

    Args:
        model_dir: Directory containing the component artifacts.

    Returns:
        List of absolute paths to the verified artifacts.

    Raises:
        DeploymentError: If any required artifacts are missing.
    """
    missing: list[str] = []
    paths: list[str] = []

    for filename in _REQUIRED_ARTIFACTS:
        path = os.path.join(model_dir, filename)
        if not os.path.isfile(path):
            missing.append(filename)
        else:
            paths.append(path)

    if missing:
        raise DeploymentError(
            f"Missing required artifacts in {model_dir}: {', '.join(missing)}"
        )

    return paths


def _upload_artifacts(
    model_dir: str,
    version: str,
    bucket: str,
    region: str,
) -> None:
    """Upload all component artifacts to S3.

    Uploads each artifact to:
        s3://{bucket}/artifacts/com.xgo.VisionNavigation/{version}/{filename}

    Args:
        model_dir: Local directory containing the artifacts.
        version: Component version string.
        bucket: S3 bucket name.
        region: AWS region.

    Raises:
        DeploymentError: If any upload fails.
    """
    s3_client = boto3.client("s3", region_name=region)
    s3_prefix = f"artifacts/{_COMPONENT_NAME}/{version}"

    for filename in _REQUIRED_ARTIFACTS:
        local_path = os.path.join(model_dir, filename)
        s3_key = f"{s3_prefix}/{filename}"

        try:
            logger.info("Uploading %s to s3://%s/%s", local_path, bucket, s3_key)
            s3_client.upload_file(local_path, bucket, s3_key)
        except ClientError as e:
            raise DeploymentError(
                f"Failed to upload {filename} to s3://{bucket}/{s3_key}: {e}"
            ) from e

    logger.info("All artifacts uploaded to s3://%s/%s/", bucket, s3_prefix)


def _load_recipe(version: str) -> str:
    """Load the component recipe from recipe.yaml and substitute the version.

    The recipe file is expected in the same directory as this script.
    The placeholder {version} in the recipe is replaced with the actual version.

    Args:
        version: Component version string to substitute.

    Returns:
        The recipe YAML content as a string with version substituted.

    Raises:
        DeploymentError: If the recipe file cannot be loaded.
    """
    recipe_path = os.path.join(os.path.dirname(__file__), "recipe.yaml")

    if not os.path.isfile(recipe_path):
        raise DeploymentError(f"Recipe file not found: {recipe_path}")

    try:
        with open(recipe_path, "r") as f:
            recipe_content = f.read()
    except OSError as e:
        raise DeploymentError(f"Failed to read recipe file: {e}") from e

    # Replace {version} placeholder with actual version
    recipe_content = recipe_content.replace("{version}", version)
    return recipe_content


def _create_component_version(
    recipe_content: str,
    region: str,
) -> str:
    """Create a Greengrass component version from the recipe.

    Args:
        recipe_content: The YAML recipe with version substituted.
        region: AWS region.

    Returns:
        The component version ARN.

    Raises:
        DeploymentError: If the API call fails.
    """
    gg_client = boto3.client("greengrassv2", region_name=region)

    try:
        logger.info("Creating component version for %s", _COMPONENT_NAME)
        response = gg_client.create_component_version(
            inlineRecipe=recipe_content.encode("utf-8"),
        )
        component_arn = response.get("arn", "")
        logger.info("Component version created: %s", component_arn)
        return component_arn
    except ClientError as e:
        raise DeploymentError(
            f"Failed to create component version: {e}"
        ) from e


def _create_deployment(
    version: str,
    thing_name: str,
    region: str,
) -> str:
    """Create a Greengrass deployment targeting the specified thing.

    Args:
        version: Component version to deploy.
        thing_name: IoT thing name of the target core device.
        region: AWS region.

    Returns:
        The deployment ID.

    Raises:
        DeploymentError: If the API call fails.
    """
    gg_client = boto3.client("greengrassv2", region_name=region)

    # Resolve the account ID from the caller identity for the thing ARN
    sts_client = boto3.client("sts", region_name=region)
    try:
        account_id = sts_client.get_caller_identity()["Account"]
    except ClientError as e:
        raise DeploymentError(
            f"Failed to resolve AWS account ID: {e}"
        ) from e

    target_arn = f"arn:aws:iot:{region}:{account_id}:thing/{thing_name}"

    try:
        logger.info(
            "Creating deployment for %s v%s targeting %s",
            _COMPONENT_NAME, version, target_arn,
        )
        response = gg_client.create_deployment(
            targetArn=target_arn,
            components={
                _COMPONENT_NAME: {
                    "componentVersion": version,
                },
            },
        )
        deployment_id = response.get("deploymentId", "")
        logger.info("Deployment created: %s", deployment_id)
        return deployment_id
    except ClientError as e:
        raise DeploymentError(
            f"Failed to create deployment: {e}"
        ) from e


def _poll_deployment(deployment_id: str, region: str) -> str:
    """Poll deployment status until it reaches a terminal state.

    Args:
        deployment_id: The Greengrass deployment ID.
        region: AWS region.

    Returns:
        The terminal deployment status (COMPLETED, FAILED, or CANCELED).

    Raises:
        DeploymentError: On FAILED status (with error details) or polling timeout.
    """
    gg_client = boto3.client("greengrassv2", region_name=region)

    for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
        time.sleep(_POLL_INTERVAL_SECONDS)

        try:
            response = gg_client.get_deployment(deploymentId=deployment_id)
        except ClientError as e:
            raise DeploymentError(
                f"Failed to get deployment status for {deployment_id}: {e}"
            ) from e

        status = response.get("deploymentStatus", "UNKNOWN")
        logger.info(
            "Deployment %s — status: %s (poll %d/%d)",
            deployment_id, status, attempt, _MAX_POLL_ATTEMPTS,
        )

        if status not in _TERMINAL_STATES:
            continue

        if status == "FAILED":
            # Extract error details from the API response
            status_details = response.get("deploymentStatusDetails", {})
            error_message = status_details.get(
                "message", "No error details available"
            )
            raise DeploymentError(
                f"Deployment {deployment_id} FAILED: {error_message}"
            )

        return status

    # Polling timeout
    raise DeploymentError(
        f"Deployment {deployment_id} timed out after "
        f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS}s"
    )


def deploy(
    version: str,
    model_dir: str,
    thing_name: str = "xgo-robodog",
    bucket: str = "654654616949-use1-greengrass",
    region: str = "us-east-1",
) -> dict:
    """Build, upload, and deploy the VisionNavigation component.

    Steps:
        1. Verify all required artifacts exist locally in model_dir
        2. Upload artifacts to s3://{bucket}/artifacts/com.xgo.VisionNavigation/{version}/
        3. Create component version via greengrassv2.create_component_version()
        4. Create deployment targeting thing_name
        5. Poll deployment status until terminal state

    Args:
        version: Semantic version string for the component (e.g. "1.0.0").
        model_dir: Local directory containing all required artifacts.
        thing_name: IoT thing name of the target Greengrass core device.
        bucket: S3 bucket for artifact storage.
        region: AWS region.

    Returns:
        Dict with "deployment_id" (str) and "status" (str).

    Raises:
        DeploymentError: On any failure during the deployment pipeline.
    """
    # Step 1: Verify artifacts
    logger.info("Verifying artifacts in %s", model_dir)
    _verify_artifacts(model_dir)

    # Step 2: Upload artifacts to S3
    _upload_artifacts(model_dir, version, bucket, region)

    # Step 3: Create component version
    recipe_content = _load_recipe(version)
    _create_component_version(recipe_content, region)

    # Step 4: Create deployment
    deployment_id = _create_deployment(version, thing_name, region)

    # Step 5: Poll deployment status
    status = _poll_deployment(deployment_id, region)

    logger.info(
        "Deployment complete — id: %s, status: %s", deployment_id, status
    )
    return {"deployment_id": deployment_id, "status": status}


def main() -> None:
    """CLI entry point for the deploy script."""
    parser = argparse.ArgumentParser(
        description="Deploy the VisionNavigation Greengrass component.",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Component version (semantic versioning, e.g. 1.0.0)",
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        help="Local directory containing all component artifacts",
    )
    parser.add_argument(
        "--thing-name",
        default="xgo-robodog",
        help="Target Greengrass core device thing name (default: xgo-robodog)",
    )
    parser.add_argument(
        "--bucket",
        default="654654616949-use1-greengrass",
        help="S3 bucket for artifacts (default: 654654616949-use1-greengrass)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        result = deploy(
            version=args.version,
            model_dir=args.model_dir,
            thing_name=args.thing_name,
            bucket=args.bucket,
            region=args.region,
        )
        print(json.dumps(result, indent=2))
    except DeploymentError as e:
        logger.error("Deployment failed: %s", e)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
