"""Unit tests for perception_agent.py.

Tests verify:
- perceive takes a photo directly and analyzes it (Zumi)
- perceive always includes image_url when photo succeeds (Zumi)
- perceive handles photo timeout gracefully (Zumi)
- perceive handles analysis failure gracefully (Zumi)
- perceive handles photo exception gracefully (Zumi)
- perceive returns "not available" for XGO2 (no take_photo in tool_names)
- create_perception_agent creates agent with correct tools and system prompt
- create_perception_agent includes profile fragment in prompt when provided
- init_perception_agent passes perception_prompt_fragment through
- _extract_json handles markdown fences and mixed text
"""

import sys
from unittest.mock import MagicMock, patch
import json

# Stub heavy dependencies before importing the module under test.
_mock_config = MagicMock()
_mock_config.DEFAULT_ROBOT = "zumi"
sys.modules.setdefault("config", _mock_config)
sys.modules.setdefault("boto3", MagicMock())

import perception_agent
from perception_agent import (
    create_perception_agent,
    init_perception_agent,
    perceive,
    _extract_json,
    PERCEPTION_SYSTEM_PROMPT,
    PERCEPTION_PREAMBLE,
)
from tools.perception_tools import (
    take_photo,
    analyze_photo,
    read_sensors,
    read_orientation,
)


# ---------------------------------------------------------------------------
# Helpers — mock profiles
# ---------------------------------------------------------------------------

def _make_zumi_profile(send_command=None):
    """Return a mock HardwareProfile that looks like Zumi (has take_photo).
    
    Args:
        send_command: Optional callable to use as profile.send_command.
            If None, a default MagicMock is used.
    """
    profile = MagicMock()
    profile.robot_id = "zumi"
    profile.display_name = "Zumi"
    profile.tool_names = (
        "drive_forward", "turn_left", "take_photo", "analyze_photo",
        "read_sensors", "read_orientation", "emergency_stop",
    )
    profile.perception_prompt_fragment = "Zumi camera at 5cm height."
    if send_command is not None:
        profile.send_command = send_command
    return profile


def _make_xgo2_profile():
    """Return a mock HardwareProfile that looks like XGO2 (has take_photo now)."""
    profile = MagicMock()
    profile.robot_id = "xgo2"
    profile.display_name = "XGO2 Robodog"
    profile.tool_names = (
        "xgo_navigate_to_target", "xgo_check_navigation_status",
        "xgo_stop_navigation", "take_photo", "analyze_photo",
    )
    profile.perception_prompt_fragment = "XGO2 on-device ML inference."
    return profile


# ---------------------------------------------------------------------------
# _extract_json helper
# ---------------------------------------------------------------------------


def test_extract_json_plain_json():
    text = '{"found": true, "position": "center"}'
    result = _extract_json(text)
    assert result == {"found": True, "position": "center"}


def test_extract_json_markdown_fenced():
    text = 'Here is the result:\n```json\n{"found": false, "confidence": "low"}\n```'
    result = _extract_json(text)
    assert result == {"found": False, "confidence": "low"}


def test_extract_json_embedded_braces():
    text = 'I analyzed the photo. {"found": true, "description": "a watch"} That is all.'
    result = _extract_json(text)
    assert result["found"] is True
    assert result["description"] == "a watch"


def test_extract_json_no_json():
    text = "I could not find any objects in the scene."
    result = _extract_json(text)
    assert result is None


def test_extract_json_invalid_json():
    text = "{found: true, position: center}"
    result = _extract_json(text)
    assert result is None


# ---------------------------------------------------------------------------
# create_perception_agent
# ---------------------------------------------------------------------------


@patch("perception_agent.Agent")
def test_create_perception_agent_uses_correct_tools_and_prompt(mock_agent_cls):
    mock_model = MagicMock()
    create_perception_agent(mock_model)

    mock_agent_cls.assert_called_once_with(
        model=mock_model,
        tools=[take_photo, analyze_photo, read_sensors, read_orientation],
        system_prompt=PERCEPTION_PREAMBLE,
        callback_handler=None,
    )


@patch("perception_agent.Agent")
def test_create_perception_agent_with_fragment(mock_agent_cls):
    """When a perception_prompt_fragment is provided, it is appended to the preamble."""
    mock_model = MagicMock()
    fragment = "Zumi camera at 5cm height."
    create_perception_agent(mock_model, perception_prompt_fragment=fragment)

    expected_prompt = PERCEPTION_PREAMBLE + "\n\n" + fragment
    mock_agent_cls.assert_called_once_with(
        model=mock_model,
        tools=[take_photo, analyze_photo, read_sensors, read_orientation],
        system_prompt=expected_prompt,
        callback_handler=None,
    )


@patch("perception_agent.Agent")
def test_create_perception_agent_returns_agent_instance(mock_agent_cls):
    mock_model = MagicMock()
    mock_agent_cls.return_value = MagicMock(name="agent_instance")

    agent = create_perception_agent(mock_model)

    assert agent is mock_agent_cls.return_value


# ---------------------------------------------------------------------------
# init_perception_agent
# ---------------------------------------------------------------------------


@patch("perception_agent.create_perception_agent")
def test_init_perception_agent_sets_module_agent(mock_create):
    mock_model = MagicMock()
    mock_agent = MagicMock()
    mock_create.return_value = mock_agent

    init_perception_agent(mock_model)

    mock_create.assert_called_once_with(mock_model, "")
    assert perception_agent._perception_agent is mock_agent

    # Clean up module state.
    perception_agent._perception_agent = None


@patch("perception_agent.create_perception_agent")
def test_init_perception_agent_passes_fragment(mock_create):
    """init_perception_agent forwards perception_prompt_fragment to create_perception_agent."""
    mock_model = MagicMock()
    mock_create.return_value = MagicMock()

    init_perception_agent(mock_model, perception_prompt_fragment="XGO2 on-device ML.")

    mock_create.assert_called_once_with(mock_model, "XGO2 on-device ML.")

    # Clean up module state.
    perception_agent._perception_agent = None


# ---------------------------------------------------------------------------
# perceive — successful photo + analysis
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_returns_image_url_from_photo(mock_get_profile):
    """perceive should always include image_url when photo succeeds."""

    def send_command(tool_name, params):
        if tool_name == "take_photo":
            return {
                "status": "ok",
                "image_url": "https://s3.example.com/photo.jpg",
                "s3_key": "photos/test.jpg",
            }
        elif tool_name == "analyze_photo":
            return {
                "status": "ok",
                "found": True,
                "position": "center",
                "estimated_distance_cm": 15.0,
                "confidence": "high",
                "description": "A wrist watch on the table",
            }
        return {}

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look for a wrist watch")

    assert result["found"] is True
    assert result["position"] == "center"
    assert result["estimated_distance_cm"] == 15.0
    assert result["confidence"] == "high"
    assert result["description"] == "A wrist watch on the table"
    assert result["image_url"] == "https://s3.example.com/photo.jpg"


@patch("perception_agent.get_profile")
def test_perceive_target_not_found(mock_get_profile):
    """When target is not found, image_url should still be present."""

    def send_command(tool_name, params):
        if tool_name == "take_photo":
            return {
                "status": "ok",
                "image_url": "https://s3.example.com/photo2.jpg",
                "s3_key": "photos/test2.jpg",
            }
        elif tool_name == "analyze_photo":
            return {
                "status": "ok",
                "found": False,
                "position": None,
                "estimated_distance_cm": None,
                "confidence": "low",
                "description": "No wrist watch visible",
            }
        return {}

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look for a wrist watch")

    assert result["found"] is False
    assert result["image_url"] == "https://s3.example.com/photo2.jpg"


# ---------------------------------------------------------------------------
# perceive — photo timeout
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_photo_timeout(mock_get_profile):
    """When photo times out, return found=False with no image_url."""

    def send_command(tool_name, params):
        return {
            "status": "timeout",
            "action": "take_photo",
            "note": "Photo capture timed out",
        }

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look around")

    assert result["found"] is False
    assert result["image_url"] is None
    assert "timed out" in result["description"].lower() or "failed" in result["description"].lower()


# ---------------------------------------------------------------------------
# perceive — photo exception
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_photo_exception(mock_get_profile):
    """When take_photo raises, return error gracefully."""

    def send_command(tool_name, params):
        raise RuntimeError("MQTT publish failed")

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look around")

    assert result["found"] is False
    assert result["image_url"] is None
    assert "MQTT publish failed" in result["description"]


# ---------------------------------------------------------------------------
# perceive — analysis failure
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_analysis_exception(mock_get_profile):
    """When analyze_photo raises, return error but still include image_url."""

    def send_command(tool_name, params):
        if tool_name == "take_photo":
            return {
                "status": "ok",
                "image_url": "https://s3.example.com/photo.jpg",
                "s3_key": "photos/test.jpg",
            }
        elif tool_name == "analyze_photo":
            raise RuntimeError("Vision model unavailable")
        return {}

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look for something")

    assert result["found"] is False
    assert result["image_url"] == "https://s3.example.com/photo.jpg"
    assert "Vision model unavailable" in result["description"]


# ---------------------------------------------------------------------------
# perceive — passes query as target_description
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_passes_query_to_analyze(mock_get_profile):
    """The query should be passed as target_description to analyze_photo."""
    calls = []

    def send_command(tool_name, params):
        calls.append((tool_name, params))
        if tool_name == "take_photo":
            return {"status": "ok", "image_url": "https://example.com/p.jpg", "s3_key": "k"}
        elif tool_name == "analyze_photo":
            return {"status": "ok", "found": False, "confidence": "low", "description": "nothing"}
        return {}

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    perceive(query="find the red ball")

    # Check the analyze_photo call
    assert len(calls) == 2
    assert calls[1][0] == "analyze_photo"
    assert calls[1][1]["target_description"] == "find the red ball"
    assert calls[1][1]["image_url"] == "https://example.com/p.jpg"


# ---------------------------------------------------------------------------
# perceive — XGO2 (cloud-side photo not available)
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_xgo2_uses_photo_flow(mock_get_profile):
    """XGO2 now has take_photo in tool_names, so perceive uses the S3 photo flow."""

    def send_command(tool_name, params):
        if tool_name == "take_photo":
            return {
                "status": "ok",
                "image_url": "https://s3.example.com/xgo2-photo.jpg",
                "s3_key": "photos/xgo2/test.jpg",
            }
        elif tool_name == "analyze_photo":
            return {
                "status": "ok",
                "found": True,
                "position": "center",
                "confidence": "high",
                "description": "A cup on the floor",
            }
        return {}

    mock_get_profile.return_value = _make_xgo2_profile()
    mock_get_profile.return_value.send_command = send_command

    result = perceive(query="look for a cup", robot_id="xgo2")

    assert result["found"] is True
    assert result["image_url"] == "https://s3.example.com/xgo2-photo.jpg"
    assert result["description"] == "A cup on the floor"


@patch("perception_agent.get_profile")
def test_perceive_xgo2_photo_timeout(mock_get_profile):
    """XGO2 photo timeout returns graceful error."""

    def send_command(tool_name, params):
        return {
            "status": "timeout",
            "action": "take_photo",
            "note": "Photo capture timed out",
        }

    mock_get_profile.return_value = _make_xgo2_profile()
    mock_get_profile.return_value.send_command = send_command

    result = perceive(query="look around", robot_id="xgo2")

    assert result["found"] is False
    assert result["image_url"] is None


# ---------------------------------------------------------------------------
# perceive — robot_id parameter routing
# ---------------------------------------------------------------------------


@patch("perception_agent.get_profile")
def test_perceive_zumi_explicit_robot_id(mock_get_profile):
    """Passing robot_id='zumi' explicitly should use the Zumi photo flow."""

    def send_command(tool_name, params):
        return {
            "status": "ok",
            "image_url": "https://s3.example.com/photo.jpg",
            "s3_key": "photos/test.jpg",
        }

    mock_get_profile.return_value = _make_zumi_profile(send_command=send_command)

    result = perceive(query="look around", robot_id="zumi")

    mock_get_profile.assert_called_once_with("zumi")
    # Should have gotten a photo result (not "not available")
    assert result.get("image_url") is not None


# ---------------------------------------------------------------------------
# Perception prompt — backward compatibility
# ---------------------------------------------------------------------------


def test_perception_system_prompt_still_exported():
    """PERCEPTION_SYSTEM_PROMPT should still be available for backward compat."""
    assert "Zumi" in PERCEPTION_SYSTEM_PROMPT
    assert "camera" in PERCEPTION_SYSTEM_PROMPT.lower()


def test_perception_preamble_is_generic():
    """PERCEPTION_PREAMBLE should be robot-agnostic."""
    assert "Zumi" not in PERCEPTION_PREAMBLE
    assert "robot control system" in PERCEPTION_PREAMBLE.lower()
    assert "structured JSON" in PERCEPTION_PREAMBLE
