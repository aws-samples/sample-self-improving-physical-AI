"""Strands @tool definitions for the Perception layer.

Each tool delegates to iot_client.send_tool_command() — the existing
iot_client.py is UNCHANGED.  These thin wrappers give the Strands SDK
the type hints and docstrings it needs to auto-generate tool schemas.
"""

from strands import tool

from iot_client import send_tool_command


@tool
def take_photo() -> dict:
    """Take a photo with Zumi's camera via S3 presigned URL flow.

    Returns dict with status, image_url, s3_key on success;
    status 'timeout' on failure.
    """
    return send_tool_command("take_photo", {})


@tool
def analyze_photo(image_url: str, target_description: str) -> dict:
    """Analyze a photo to detect a target object and estimate distance.

    Args:
        image_url: Presigned S3 GET URL of the photo to analyze.
        target_description: What to look for in the photo.
    """
    return send_tool_command(
        "analyze_photo",
        {"image_url": image_url, "target_description": target_description},
    )


@tool
def read_sensors() -> dict:
    """Read all IR sensor values from Zumi. Returns 6 IR readings."""
    return send_tool_command("read_sensors", {})


@tool
def read_orientation() -> dict:
    """Get Zumi's current orientation (upright, upside down, etc.)."""
    return send_tool_command("read_orientation", {})
