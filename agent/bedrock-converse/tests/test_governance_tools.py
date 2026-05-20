"""Unit tests for tools/governance_tools.py.

Governance tools are pure logic — no IoT or Bedrock dependencies —
so tests call them directly. get_profile is mocked to return
appropriate profiles for Zumi and XGO2.
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


# Patch get_profile for all tests in this module
_patcher = patch("tools.governance_tools.get_profile", side_effect=_mock_get_profile)
_patcher.start()

from tools.governance_tools import (
    validate_action,
    evaluate_outcome,
    check_safety_state,
)


# ── validate_action — Zumi emergency stop ─────────────────────────────────


class TestValidateActionEmergencyStop:
    """Emergency stop is ALWAYS approved regardless of context."""

    def test_emergency_stop_approved(self):
        result = validate_action(
            action="emergency_stop",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["safety_notes"] == []
        assert result["modified_parameters"] is None
        assert result["reason"] == ""

    def test_emergency_stop_approved_even_with_high_distance(self):
        ctx = json.dumps({"cumulative_distance_cm": 999})
        result = validate_action(
            action="emergency_stop",
            parameters="{}",
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is None

    def test_emergency_stop_approved_during_vision_guided(self):
        ctx = json.dumps({"vision_guided": True, "cumulative_distance_cm": 200})
        result = validate_action(
            action="emergency_stop",
            parameters="{}",
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is None


class TestValidateActionUnknown:
    """Unknown actions are blocked."""

    def test_unknown_action_blocked(self):
        result = validate_action(
            action="fly_away",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is False
        assert result["reason"] == "Unknown action: fly_away"

    def test_another_unknown_action(self):
        result = validate_action(
            action="self_destruct",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is False
        assert "Unknown action" in result["reason"]


class TestValidateActionNonMovement:
    """Non-movement actions (LEDs, buzzer, screen, camera, sensors) always approved."""

    def test_headlights_on_approved(self):
        result = validate_action(
            action="headlights_on",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["reason"] == ""

    def test_play_note_approved(self):
        result = validate_action(
            action="play_note",
            parameters=json.dumps({"note": 30, "duration_ms": 500}),
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True

    def test_take_photo_approved(self):
        result = validate_action(
            action="take_photo",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True

    def test_display_text_approved(self):
        result = validate_action(
            action="display_text",
            parameters=json.dumps({"message": "Hello"}),
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True

    def test_read_sensors_approved(self):
        result = validate_action(
            action="read_sensors",
            parameters="{}",
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True


class TestValidateActionCumulativeDistance:
    """Movement blocked when cumulative distance > 100cm (Zumi)."""

    def test_movement_blocked_at_101cm(self):
        ctx = json.dumps({"cumulative_distance_cm": 101})
        result = validate_action(
            action="drive_forward",
            parameters=json.dumps({"speed": 40, "duration": 1.0}),
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is False
        assert "Cumulative distance limit exceeded" in result["reason"]

    def test_movement_allowed_at_100cm(self):
        ctx = json.dumps({"cumulative_distance_cm": 100})
        result = validate_action(
            action="drive_forward",
            parameters=json.dumps({"speed": 40, "duration": 1.0}),
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True

    def test_movement_blocked_at_large_distance(self):
        ctx = json.dumps({"cumulative_distance_cm": 500})
        result = validate_action(
            action="move_centimeters",
            parameters=json.dumps({"distance": 10}),
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is False


class TestValidateActionVisionGuided:
    """Vision-guided navigation clamps speed to max 60, distance to max 20cm (Zumi)."""

    def test_speed_clamped_to_60(self):
        ctx = json.dumps({"vision_guided": True})
        params = json.dumps({"speed": 80})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is not None
        assert result["modified_parameters"]["speed"] == 60
        assert any("Speed clamped" in n for n in result["safety_notes"])

    def test_distance_clamped_to_20(self):
        ctx = json.dumps({"vision_guided": True})
        params = json.dumps({"distance": 30})
        result = validate_action(
            action="move_centimeters",
            parameters=params,
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is not None
        assert result["modified_parameters"]["distance"] == 20
        assert any("Distance clamped" in n for n in result["safety_notes"])

    def test_no_clamping_when_within_limits(self):
        ctx = json.dumps({"vision_guided": True})
        params = json.dumps({"speed": 50, "distance": 15})
        result = validate_action(
            action="move_centimeters",
            parameters=params,
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is None
        assert result["safety_notes"] == []

    def test_both_speed_and_distance_clamped(self):
        ctx = json.dumps({"vision_guided": True})
        params = json.dumps({"speed": 100, "distance": 50})
        result = validate_action(
            action="move_centimeters",
            parameters=params,
            context=ctx,
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"]["speed"] == 60
        assert result["modified_parameters"]["distance"] == 20
        assert len(result["safety_notes"]) == 2


class TestValidateActionGeneralMovement:
    """General movement clamps speed to [1, 80] and duration to [0.1, 5.0] (Zumi)."""

    def test_speed_clamped_above_80(self):
        params = json.dumps({"speed": 100, "duration": 1.0})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"]["speed"] == 80
        assert any("Speed clamped" in n for n in result["safety_notes"])

    def test_speed_clamped_below_1(self):
        params = json.dumps({"speed": 0, "duration": 1.0})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"]["speed"] == 1

    def test_duration_clamped_above_5(self):
        params = json.dumps({"speed": 40, "duration": 10.0})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"]["duration"] == 5.0

    def test_duration_clamped_below_01(self):
        params = json.dumps({"speed": 40, "duration": 0.01})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"]["duration"] == 0.1

    def test_no_clamping_when_within_range(self):
        params = json.dumps({"speed": 40, "duration": 2.0})
        result = validate_action(
            action="drive_forward",
            parameters=params,
            context="{}",
            robot_id="zumi",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is None
        assert result["safety_notes"] == []


# ── validate_action — XGO2 ───────────────────────────────────────────────


class TestValidateActionXGO2EmergencyStop:
    """XGO2 emergency stop (xgo_stop_navigation) is always approved."""

    def test_xgo_stop_navigation_approved(self):
        result = validate_action(
            action="xgo_stop_navigation",
            parameters="{}",
            context="{}",
            robot_id="xgo2",
        )
        assert result["approved"] is True
        assert result["safety_notes"] == []
        assert result["modified_parameters"] is None
        assert result["reason"] == ""

    def test_xgo_stop_navigation_approved_with_high_distance(self):
        ctx = json.dumps({"cumulative_distance_cm": 9999})
        result = validate_action(
            action="xgo_stop_navigation",
            parameters="{}",
            context=ctx,
            robot_id="xgo2",
        )
        assert result["approved"] is True


class TestValidateActionXGO2Tools:
    """XGO2 tools are recognized as known actions."""

    def test_xgo_navigate_to_target_approved(self):
        result = validate_action(
            action="xgo_navigate_to_target",
            parameters=json.dumps({"target_label": "cup", "speed": 15}),
            context="{}",
            robot_id="xgo2",
        )
        assert result["approved"] is True

    def test_xgo_check_navigation_status_approved(self):
        result = validate_action(
            action="xgo_check_navigation_status",
            parameters="{}",
            context="{}",
            robot_id="xgo2",
        )
        assert result["approved"] is True

    def test_zumi_action_unknown_for_xgo2(self):
        result = validate_action(
            action="drive_forward",
            parameters="{}",
            context="{}",
            robot_id="xgo2",
        )
        assert result["approved"] is False
        assert "Unknown action" in result["reason"]


class TestValidateActionXGO2SafetyLimits:
    """XGO2 uses its own safety limits (max_speed=25, max_cumulative=500)."""

    def test_xgo2_speed_clamped_to_25(self):
        params = json.dumps({"speed": 50, "duration": 1.0})
        result = validate_action(
            action="xgo_navigate_to_target",
            parameters=params,
            context="{}",
            robot_id="xgo2",
        )
        assert result["approved"] is True
        assert result["modified_parameters"] is not None
        assert result["modified_parameters"]["speed"] == 25

    def test_xgo2_cumulative_allowed_at_400(self):
        ctx = json.dumps({"cumulative_distance_cm": 400})
        result = validate_action(
            action="xgo_navigate_to_target",
            parameters=json.dumps({"target_label": "cup", "speed": 15}),
            context=ctx,
            robot_id="xgo2",
        )
        assert result["approved"] is True

    def test_xgo2_cumulative_blocked_at_501(self):
        ctx = json.dumps({"cumulative_distance_cm": 501})
        result = validate_action(
            action="xgo_navigate_to_target",
            parameters=json.dumps({"target_label": "cup", "speed": 15}),
            context=ctx,
            robot_id="xgo2",
        )
        assert result["approved"] is False
        assert "Cumulative distance limit exceeded" in result["reason"]


# ── evaluate_outcome ──────────────────────────────────────────────────────


class TestEvaluateOutcome:
    """evaluate_outcome returns feedback based on result status and context."""

    def test_error_result_aborts(self):
        result = evaluate_outcome(
            action="drive_forward",
            result=json.dumps({"status": "error", "message": "motor fault"}),
            context="{}",
        )
        assert result["feedback"] == "abort"
        assert any("error" in n for n in result["notes"])

    def test_blocked_result_continues(self):
        result = evaluate_outcome(
            action="drive_forward",
            result=json.dumps({"status": "blocked"}),
            context="{}",
        )
        assert result["feedback"] == "continue"
        assert any("blocked" in n for n in result["notes"])

    def test_ok_result_continues(self):
        result = evaluate_outcome(
            action="drive_forward",
            result=json.dumps({"status": "ok"}),
            context="{}",
        )
        assert result["feedback"] == "continue"
        assert result["notes"] == []

    def test_no_progress_aborts_at_5(self):
        ctx = json.dumps({"no_progress_count": 5})
        result = evaluate_outcome(
            action="drive_forward",
            result=json.dumps({"status": "ok"}),
            context=ctx,
        )
        assert result["feedback"] == "abort"
        assert any("5 consecutive" in n for n in result["notes"])

    def test_no_progress_continues_at_4(self):
        ctx = json.dumps({"no_progress_count": 4})
        result = evaluate_outcome(
            action="drive_forward",
            result=json.dumps({"status": "ok"}),
            context=ctx,
        )
        assert result["feedback"] == "continue"

    def test_no_progress_aborts_above_5(self):
        ctx = json.dumps({"no_progress_count": 10})
        result = evaluate_outcome(
            action="turn_left",
            result=json.dumps({"status": "ok"}),
            context=ctx,
        )
        assert result["feedback"] == "abort"


# ── check_safety_state ────────────────────────────────────────────────────


class TestCheckSafetyState:
    """check_safety_state returns safe=False when thresholds are exceeded."""

    def test_safe_within_limits(self):
        result = check_safety_state(
            cumulative_distance_cm=50.0,
            no_progress_count=2,
            robot_id="zumi",
        )
        assert result["safe"] is True
        assert result["recommendations"] == []

    def test_unsafe_distance_exceeded(self):
        result = check_safety_state(
            cumulative_distance_cm=101.0,
            no_progress_count=0,
            robot_id="zumi",
        )
        assert result["safe"] is False
        assert any("cumulative distance" in r for r in result["recommendations"])

    def test_safe_at_exactly_100(self):
        result = check_safety_state(
            cumulative_distance_cm=100.0,
            no_progress_count=0,
            robot_id="zumi",
        )
        assert result["safe"] is True

    def test_unsafe_no_progress(self):
        result = check_safety_state(
            cumulative_distance_cm=10.0,
            no_progress_count=5,
            robot_id="zumi",
        )
        assert result["safe"] is False
        assert any("5 consecutive" in r for r in result["recommendations"])

    def test_safe_at_4_no_progress(self):
        result = check_safety_state(
            cumulative_distance_cm=10.0,
            no_progress_count=4,
            robot_id="zumi",
        )
        assert result["safe"] is True

    def test_both_thresholds_exceeded(self):
        result = check_safety_state(
            cumulative_distance_cm=200.0,
            no_progress_count=7,
            robot_id="zumi",
        )
        assert result["safe"] is False
        assert len(result["recommendations"]) == 2


class TestCheckSafetyStateXGO2:
    """check_safety_state uses XGO2 limits (max_cumulative=500)."""

    def test_xgo2_safe_at_400(self):
        result = check_safety_state(
            cumulative_distance_cm=400.0,
            no_progress_count=0,
            robot_id="xgo2",
        )
        assert result["safe"] is True

    def test_xgo2_unsafe_at_501(self):
        result = check_safety_state(
            cumulative_distance_cm=501.0,
            no_progress_count=0,
            robot_id="xgo2",
        )
        assert result["safe"] is False
        assert any("500" in r for r in result["recommendations"])
