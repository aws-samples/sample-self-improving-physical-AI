"""Unit tests for tools/perception_tools.py.

Each perception tool is a thin Strands @tool wrapper around
iot_client.send_tool_command().  We mock send_tool_command and verify
that each tool forwards the correct tool_name and tool_input.
"""

import sys
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

from tools.perception_tools import (
    take_photo,
    analyze_photo,
    read_sensors,
    read_orientation,
)


# ---------------------------------------------------------------------------
# take_photo
# ---------------------------------------------------------------------------

@patch("tools.perception_tools.send_tool_command")
def test_take_photo_delegates_correctly(mock_send):
    mock_send.return_value = {
        "status": "ok",
        "action": "take_photo",
        "image_url": "https://s3.example.com/photo.jpg",
        "s3_key": "photos/zumi/photo.jpg",
    }

    result = take_photo()

    mock_send.assert_called_once_with("take_photo", {})
    assert result["status"] == "ok"
    assert "image_url" in result
    assert "s3_key" in result


@patch("tools.perception_tools.send_tool_command")
def test_take_photo_timeout(mock_send):
    mock_send.return_value = {"status": "timeout", "action": "take_photo"}

    result = take_photo()

    mock_send.assert_called_once_with("take_photo", {})
    assert result["status"] == "timeout"


# ---------------------------------------------------------------------------
# analyze_photo
# ---------------------------------------------------------------------------

@patch("tools.perception_tools.send_tool_command")
def test_analyze_photo_delegates_correctly(mock_send):
    mock_send.return_value = {
        "status": "ok",
        "action": "analyze_photo",
        "found": True,
        "position": "center",
        "estimated_distance_cm": 15.0,
        "confidence": "high",
        "description": "A wrist watch on the table",
    }

    result = analyze_photo(
        image_url="https://s3.example.com/photo.jpg",
        target_description="wrist watch",
    )

    mock_send.assert_called_once_with(
        "analyze_photo",
        {
            "image_url": "https://s3.example.com/photo.jpg",
            "target_description": "wrist watch",
        },
    )
    assert result["found"] is True
    assert result["position"] == "center"


# ---------------------------------------------------------------------------
# read_sensors
# ---------------------------------------------------------------------------

@patch("tools.perception_tools.send_tool_command")
def test_read_sensors_delegates_correctly(mock_send):
    mock_send.return_value = {
        "status": "requested",
        "note": "Sensor read command sent.",
    }

    result = read_sensors()

    mock_send.assert_called_once_with("read_sensors", {})
    assert result["status"] == "requested"


# ---------------------------------------------------------------------------
# read_orientation
# ---------------------------------------------------------------------------

@patch("tools.perception_tools.send_tool_command")
def test_read_orientation_delegates_correctly(mock_send):
    mock_send.return_value = {
        "status": "requested",
        "note": "Orientation read command sent.",
    }

    result = read_orientation()

    mock_send.assert_called_once_with("read_orientation", {})
    assert result["status"] == "requested"
