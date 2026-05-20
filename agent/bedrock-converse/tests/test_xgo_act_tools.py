"""Unit tests for tools/xgo_act_tools.py — grip calibration wrappers.

Each grip tool is a thin Strands @tool wrapper around
xgo_tools.send_xgo_tool_command().  We mock send_xgo_tool_command and
verify that each tool forwards the correct tool_name and tool_input.

This follows the same pattern as test_act_tools.py.
"""

import sys
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

from tools.xgo_act_tools import (
    xgo_start_grip,
    xgo_check_grip_status,
    xgo_stop_grip,
    xgo_navigate_to_target,
    xgo_check_navigation_status,
    xgo_stop_navigation,
    xgo_arm,
    xgo_claw,
    xgo_action,
)


# ── xgo_start_grip ───────────────────────────────────────────────────────


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_start_grip_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "start_grip"}

    result = xgo_start_grip()

    mock_send.assert_called_once_with(
        "xgo_start_grip",
        {
            "max_iterations": 50,
            "convergence_tolerance": 15,
            "arm_step_limit": 10,
        },
    )
    assert result["status"] == "ok"
    assert result["action"] == "start_grip"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_start_grip_custom_params(mock_send):
    mock_send.return_value = {"status": "ok", "action": "start_grip"}

    result = xgo_start_grip(
        max_iterations=100,
        convergence_tolerance=20,
        arm_step_limit=5,
    )

    mock_send.assert_called_once_with(
        "xgo_start_grip",
        {
            "max_iterations": 100,
            "convergence_tolerance": 20,
            "arm_step_limit": 5,
        },
    )
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_start_grip_partial_params(mock_send):
    mock_send.return_value = {"status": "ok", "action": "start_grip"}

    result = xgo_start_grip(max_iterations=30)

    mock_send.assert_called_once_with(
        "xgo_start_grip",
        {
            "max_iterations": 30,
            "convergence_tolerance": 15,
            "arm_step_limit": 10,
        },
    )
    assert result["status"] == "ok"


# ── xgo_check_grip_status ────────────────────────────────────────────────


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_check_grip_status(mock_send):
    mock_send.return_value = {
        "status": "ok",
        "action": "check_grip_status",
        "grip_status": {"step": 10, "convergence_state": "converging"},
    }

    result = xgo_check_grip_status()

    mock_send.assert_called_once_with("xgo_check_grip_status", {})
    assert result["status"] == "ok"
    assert result["action"] == "check_grip_status"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_check_grip_status_no_session(mock_send):
    mock_send.return_value = {
        "status": "ok",
        "action": "check_grip_status",
        "note": "No retained grip status available.",
    }

    result = xgo_check_grip_status()

    mock_send.assert_called_once_with("xgo_check_grip_status", {})
    assert result["status"] == "ok"
    assert "note" in result


# ── xgo_stop_grip ─────────────────────────────────────────────────────────


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_stop_grip(mock_send):
    mock_send.return_value = {
        "status": "ok",
        "action": "stop_grip",
        "note": "Stop grip command sent to XGO2.",
    }

    result = xgo_stop_grip()

    mock_send.assert_called_once_with("xgo_stop_grip", {})
    assert result["status"] == "ok"
    assert result["action"] == "stop_grip"


# ── Existing navigation tools still work ──────────────────────────────────


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_navigate_to_target_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "navigate_to_target"}

    result = xgo_navigate_to_target(target_label="cup")

    mock_send.assert_called_once_with(
        "xgo_navigate_to_target",
        {"target_label": "cup", "max_steps": 100, "speed": 15},
    )
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_check_navigation_status_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "check_navigation_status"}

    result = xgo_check_navigation_status()

    mock_send.assert_called_once_with("xgo_check_navigation_status", {})
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_stop_navigation_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "stop_navigation"}

    result = xgo_stop_navigation()

    mock_send.assert_called_once_with("xgo_stop_navigation", {})
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_arm_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "arm"}

    result = xgo_arm(arm_x=50, arm_z=30)

    mock_send.assert_called_once_with("xgo_arm", {"arm_x": 50, "arm_z": 30})
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_claw_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "claw"}

    result = xgo_claw(pos=200)

    mock_send.assert_called_once_with("xgo_claw", {"pos": 200})
    assert result["status"] == "ok"


@patch("tools.xgo_act_tools.send_xgo_tool_command")
def test_xgo_action_still_works(mock_send):
    mock_send.return_value = {"status": "ok", "action": "xgo_action"}

    result = xgo_action(action_id=13)

    mock_send.assert_called_once_with("xgo_action", {"action_id": 13})
    assert result["status"] == "ok"
