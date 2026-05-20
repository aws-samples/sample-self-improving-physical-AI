"""Unit tests for governance_agent.py.

Tests verify:
- governed_execute blocks action when validate_action returns approved=False
- governed_execute executes action when approved, returns correct result
- governed_execute updates cumulative distance for movement actions
- governed_execute handles emergency_stop immediately (Zumi)
- governed_execute handles xgo_stop_navigation immediately (XGO2)
- governed_execute handles act agent errors gracefully
- governed_execute returns error when not initialized
- governed_execute passes robot_id through to validate_action and act agent
- create_governance_agent creates agent with correct tools and system prompt
"""

import sys
import json
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("boto3", MagicMock())

from hardware_profile import HardwareProfile, IoTConfig, SafetyLimits

# ── Helper: build mock profiles ──────────────────────────────────────────

_ZUMI_SAFETY = SafetyLimits(
    max_speed=80,
    max_vision_speed=60,
    max_distance_per_step_cm=20.0,
    max_cumulative_distance_cm=100.0,
    max_navigation_steps=200,
)

_XGO2_SAFETY = SafetyLimits(
    max_speed=25,
    max_vision_speed=25,
    max_distance_per_step_cm=50.0,
    max_cumulative_distance_cm=500.0,
    max_navigation_steps=500,
)

_DUMMY_IOT = IoTConfig(
    endpoint="test-endpoint",
    region="us-east-1",
    thing_name="test-thing",
    command_topic="test/command",
)

_ZUMI_TOOL_NAMES = (
    "drive_forward", "drive_reverse", "turn_left", "turn_right",
    "emergency_stop", "move_inches", "move_centimeters",
    "drive_circle", "drive_square", "drive_figure_8",
    "parallel_park", "j_turn",
    "headlights_on", "headlights_off", "all_lights_on", "all_lights_off",
    "hazard_lights_on", "hazard_lights_off",
    "signal_left_on", "signal_left_off",
    "signal_right_on", "signal_right_off",
    "brake_lights_on", "brake_lights_off",
    "play_note", "display_text", "show_emotion",
    "take_photo", "analyze_photo", "read_sensors", "read_orientation",
)

_XGO2_TOOL_NAMES = (
    "xgo_navigate_to_target",
    "xgo_check_navigation_status",
    "xgo_stop_navigation",
)

_dummy_send = lambda name, inp: {"status": "ok"}

_ZUMI_PROFILE = HardwareProfile(
    robot_id="zumi",
    display_name="Zumi",
    system_prompt_fragment="Zumi prompt",
    tool_names=_ZUMI_TOOL_NAMES,
    iot_config=_DUMMY_IOT,
    safety_limits=_ZUMI_SAFETY,
    capability_tags=("differential_drive",),
    perception_prompt_fragment="Zumi perception",
    governance_prompt_fragment="Zumi governance",
    greeting_message="Hi from Zumi",
    send_command=_dummy_send,
    emergency_stop_actions=("emergency_stop",),
)

_XGO2_PROFILE = HardwareProfile(
    robot_id="xgo2",
    display_name="XGO2 Robodog",
    system_prompt_fragment="XGO2 prompt",
    tool_names=_XGO2_TOOL_NAMES,
    iot_config=_DUMMY_IOT,
    safety_limits=_XGO2_SAFETY,
    capability_tags=("quadruped",),
    perception_prompt_fragment="XGO2 perception",
    governance_prompt_fragment="XGO2 governance",
    greeting_message="Hi from XGO2",
    send_command=_dummy_send,
    emergency_stop_actions=("xgo_stop_navigation",),
)


def _mock_get_profile(robot_id):
    if robot_id == "xgo2":
        return _XGO2_PROFILE
    return _ZUMI_PROFILE


# Patch get_profile for both governance_agent and governance_tools
_patcher1 = patch("governance_agent.get_profile", side_effect=_mock_get_profile)
_patcher2 = patch("tools.governance_tools.get_profile", side_effect=_mock_get_profile)
_patcher1.start()
_patcher2.start()

import governance_agent
from governance_agent import (
    create_governance_agent,
    init_governance_agent,
    set_act_agent,
    governed_execute,
    _estimate_distance_cm,
    GOVERNANCE_SYSTEM_PROMPT,
)

from tools.governance_tools import validate_action, evaluate_outcome, check_safety_state


# ---------------------------------------------------------------------------
# _estimate_distance_cm helper
# ---------------------------------------------------------------------------


def test_estimate_distance_move_centimeters():
    assert _estimate_distance_cm("move_centimeters", {"distance": 15}) == 15.0


def test_estimate_distance_move_inches():
    result = _estimate_distance_cm("move_inches", {"distance": 2})
    assert abs(result - 5.08) < 0.01


def test_estimate_distance_drive_forward():
    # speed=40, duration=1.0 → 40 * 1.0 * 0.3 = 12.0
    result = _estimate_distance_cm("drive_forward", {"speed": 40, "duration": 1.0})
    assert abs(result - 12.0) < 0.01


def test_estimate_distance_drive_reverse():
    result = _estimate_distance_cm("drive_reverse", {"speed": 30, "duration": 2.0})
    assert abs(result - 18.0) < 0.01


def test_estimate_distance_turn():
    assert _estimate_distance_cm("turn_left", {}) == 10.0
    assert _estimate_distance_cm("turn_right", {}) == 10.0


def test_estimate_distance_shapes():
    assert _estimate_distance_cm("drive_circle", {}) == 30.0
    assert _estimate_distance_cm("drive_square", {}) == 30.0
    assert _estimate_distance_cm("drive_figure_8", {}) == 30.0
    assert _estimate_distance_cm("parallel_park", {}) == 30.0
    assert _estimate_distance_cm("j_turn", {}) == 30.0


def test_estimate_distance_non_movement():
    assert _estimate_distance_cm("headlights_on", {}) == 0.0
    assert _estimate_distance_cm("play_note", {}) == 0.0


# ---------------------------------------------------------------------------
# create_governance_agent
# ---------------------------------------------------------------------------


@patch("governance_agent.Agent")
def test_create_governance_agent_uses_correct_tools_and_prompt(mock_agent_cls):
    mock_model = MagicMock()
    create_governance_agent(mock_model)

    mock_agent_cls.assert_called_once_with(
        model=mock_model,
        tools=[validate_action, evaluate_outcome, check_safety_state],
        system_prompt=GOVERNANCE_SYSTEM_PROMPT,
        callback_handler=None,
    )


@patch("governance_agent.Agent")
def test_create_governance_agent_returns_agent_instance(mock_agent_cls):
    mock_model = MagicMock()
    mock_agent_cls.return_value = MagicMock(name="agent_instance")

    agent = create_governance_agent(mock_model)
    assert agent is mock_agent_cls.return_value


# ---------------------------------------------------------------------------
# init_governance_agent / set_act_agent
# ---------------------------------------------------------------------------


@patch("governance_agent.create_governance_agent")
def test_init_governance_agent_sets_module_agent(mock_create):
    mock_model = MagicMock()
    mock_agent = MagicMock()
    mock_create.return_value = mock_agent

    init_governance_agent(mock_model)

    mock_create.assert_called_once_with(mock_model)
    assert governance_agent._governance_agent is mock_agent

    # Clean up.
    governance_agent._governance_agent = None


def test_set_act_agent_stores_reference():
    mock_fn = MagicMock()
    set_act_agent(mock_fn)

    assert governance_agent._act_agent_ref is mock_fn

    # Clean up.
    governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — not initialized
# ---------------------------------------------------------------------------


def test_governed_execute_returns_error_when_not_initialized():
    governance_agent._act_agent_ref = None

    result = governed_execute(
        action="drive_forward",
        parameters='{"speed": 40, "duration": 1.0}',
        context="{}",
        robot_id="zumi",
    )

    assert result["status"] == "error"
    assert result["action"] == "drive_forward"
    assert result["governance"]["approved"] is False
    assert "not initialized" in result["governance"]["reason"]
    assert result["execution_result"] is None


# ---------------------------------------------------------------------------
# governed_execute — action blocked
# ---------------------------------------------------------------------------


def test_governed_execute_blocks_unknown_action():
    mock_act = MagicMock()
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="fly_away",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )

        assert result["status"] == "blocked"
        assert result["action"] == "fly_away"
        assert result["governance"]["approved"] is False
        assert result["execution_result"] is None
        # Act agent should NOT have been called.
        mock_act.assert_not_called()
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_blocks_when_cumulative_exceeded():
    mock_act = MagicMock()
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context='{"cumulative_distance_cm": 105}',
            robot_id="zumi",
        )

        assert result["status"] == "blocked"
        assert result["governance"]["approved"] is False
        assert "cumulative" in result["governance"]["reason"].lower()
        mock_act.assert_not_called()
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — action approved and executed
# ---------------------------------------------------------------------------


def test_governed_execute_approved_returns_correct_result():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "drive_forward"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context="{}",
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["action"] == "drive_forward"
        assert result["governance"]["approved"] is True
        assert result["execution_result"]["status"] == "ok"
        assert result["feedback"] in ("goal_met", "continue", "abort")
        mock_act.assert_called_once()
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_approved_non_movement_zero_distance():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "headlights_on"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="headlights_on",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["cumulative_distance_cm"] == 0.0
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — cumulative distance tracking
# ---------------------------------------------------------------------------


def test_governed_execute_updates_cumulative_distance_move_cm():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "move_centimeters"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="move_centimeters",
            parameters='{"distance": 15}',
            context='{"cumulative_distance_cm": 20}',
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["cumulative_distance_cm"] == 35.0  # 20 + 15
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_updates_cumulative_distance_move_inches():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "move_inches"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="move_inches",
            parameters='{"distance": 2}',
            context='{"cumulative_distance_cm": 10}',
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        # 10 + 2 * 2.54 = 15.08
        assert abs(result["cumulative_distance_cm"] - 15.08) < 0.01
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_updates_cumulative_distance_drive_forward():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "drive_forward"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context='{"cumulative_distance_cm": 5}',
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        # 5 + 40 * 1.0 * 0.3 = 17.0
        assert abs(result["cumulative_distance_cm"] - 17.0) < 0.01
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — emergency stop (Zumi)
# ---------------------------------------------------------------------------


def test_governed_execute_emergency_stop_always_approved():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "emergency_stop"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="emergency_stop",
            parameters="{}",
            context='{"cumulative_distance_cm": 200}',
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["governance"]["approved"] is True
        assert result["feedback"] == "goal_met"
        # Cumulative distance should NOT increase for emergency stop.
        assert result["cumulative_distance_cm"] == 200.0
        mock_act.assert_called_once()
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_emergency_stop_no_parameter_modification():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "emergency_stop"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="emergency_stop",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )

        assert result["governance"]["modified_parameters"] is None
        assert result["governance"]["safety_notes"] == []
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_emergency_stop_without_act_agent():
    """Emergency stop should still attempt execution even without act agent."""
    governance_agent._act_agent_ref = None

    result = governed_execute(
        action="emergency_stop",
        parameters="{}",
        context="{}",
        robot_id="zumi",
    )

    assert result["status"] == "ok"
    assert result["governance"]["approved"] is True
    assert result["execution_result"]["status"] == "error"
    assert "not initialized" in result["execution_result"]["message"]


# ---------------------------------------------------------------------------
# governed_execute — XGO2 emergency stop (xgo_stop_navigation)
# ---------------------------------------------------------------------------


def test_governed_execute_xgo2_stop_navigation_always_approved():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "xgo_stop_navigation"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="xgo_stop_navigation",
            parameters="{}",
            context='{"cumulative_distance_cm": 9999}',
            robot_id="xgo2",
        )

        assert result["status"] == "ok"
        assert result["governance"]["approved"] is True
        assert result["feedback"] == "goal_met"
        assert result["cumulative_distance_cm"] == 9999.0
        mock_act.assert_called_once()
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_xgo2_stop_navigation_without_act_agent():
    governance_agent._act_agent_ref = None

    result = governed_execute(
        action="xgo_stop_navigation",
        parameters="{}",
        context="{}",
        robot_id="xgo2",
    )

    assert result["status"] == "ok"
    assert result["governance"]["approved"] is True
    assert result["execution_result"]["status"] == "error"
    assert "not initialized" in result["execution_result"]["message"]


# ---------------------------------------------------------------------------
# governed_execute — XGO2 actions
# ---------------------------------------------------------------------------


def test_governed_execute_xgo2_navigate_approved():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "xgo_navigate_to_target"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="xgo_navigate_to_target",
            parameters='{"target_label": "cup", "speed": 15}',
            context="{}",
            robot_id="xgo2",
        )

        assert result["status"] == "ok"
        assert result["governance"]["approved"] is True
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_xgo2_blocks_zumi_action():
    mock_act = MagicMock()
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40}',
            context="{}",
            robot_id="xgo2",
        )

        assert result["status"] == "blocked"
        assert result["governance"]["approved"] is False
        assert "Unknown action" in result["governance"]["reason"]
        mock_act.assert_not_called()
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — robot_id passed to act agent
# ---------------------------------------------------------------------------


def test_governed_execute_passes_robot_id_to_act_agent():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "drive_forward"}
    governance_agent._act_agent_ref = mock_act

    try:
        governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context="{}",
            robot_id="zumi",
        )

        call_kwargs = mock_act.call_args[1]
        assert call_kwargs["robot_id"] == "zumi"
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_passes_xgo2_robot_id_to_act_agent():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "xgo_navigate_to_target"}
    governance_agent._act_agent_ref = mock_act

    try:
        governed_execute(
            action="xgo_navigate_to_target",
            parameters='{"target_label": "cup", "speed": 15}',
            context="{}",
            robot_id="xgo2",
        )

        call_kwargs = mock_act.call_args[1]
        assert call_kwargs["robot_id"] == "xgo2"
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — act agent errors
# ---------------------------------------------------------------------------


def test_governed_execute_handles_act_agent_exception():
    mock_act = MagicMock()
    mock_act.side_effect = RuntimeError("MQTT publish failed")
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context="{}",
            robot_id="zumi",
        )

        assert result["status"] == "error"
        assert result["action"] == "drive_forward"
        assert result["governance"]["approved"] is True
        assert "MQTT publish failed" in result["execution_result"]["message"]
        assert result["feedback"] == "abort"
    finally:
        governance_agent._act_agent_ref = None


def test_governed_execute_handles_act_agent_error_status():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "error", "action": "drive_forward", "message": "timeout"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 40, "duration": 1.0}',
            context="{}",
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["execution_result"]["status"] == "error"
        # evaluate_outcome should return abort for error status.
        assert result["feedback"] == "abort"
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — vision-guided clamping
# ---------------------------------------------------------------------------


def test_governed_execute_clamps_speed_during_vision_guided():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "drive_forward"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="drive_forward",
            parameters='{"speed": 80, "duration": 1.0}',
            context='{"vision_guided": true}',
            robot_id="zumi",
        )

        assert result["status"] == "ok"
        assert result["governance"]["approved"] is True
        # Should have clamped speed to 60.
        assert result["governance"]["modified_parameters"] is not None
        assert result["governance"]["modified_parameters"]["speed"] == 60
    finally:
        governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# governed_execute — malformed parameters
# ---------------------------------------------------------------------------


def test_governed_execute_handles_malformed_parameters():
    mock_act = MagicMock()
    mock_act.return_value = {"status": "ok", "action": "headlights_on"}
    governance_agent._act_agent_ref = mock_act

    try:
        result = governed_execute(
            action="headlights_on",
            parameters="not-json",
            context="also-not-json",
            robot_id="zumi",
        )

        # Should not crash — falls back to empty dicts.
        assert result["status"] == "ok"
    finally:
        governance_agent._act_agent_ref = None
