"""Unit tests for tools/act_tools.py.

Each act tool is a thin Strands @tool wrapper around
iot_client.send_tool_command().  We mock send_tool_command and verify
that each tool forwards the correct tool_name and tool_input.
"""

import sys
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

from tools.act_tools import (
    drive_forward,
    drive_reverse,
    turn_left,
    turn_right,
    emergency_stop,
    move_inches,
    move_centimeters,
    drive_circle,
    drive_square,
    drive_figure_8,
    parallel_park,
    j_turn,
    headlights_on,
    headlights_off,
    all_lights_on,
    all_lights_off,
    hazard_lights_on,
    hazard_lights_off,
    signal_left_on,
    signal_left_off,
    signal_right_on,
    signal_right_off,
    brake_lights_on,
    brake_lights_off,
    play_note,
    display_text,
    show_emotion,
)


# ── Drive Tools ───────────────────────────────────────────────────────────


@patch("tools.act_tools.send_tool_command")
def test_drive_forward_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "forward"}

    result = drive_forward()

    mock_send.assert_called_once_with("drive_forward", {"speed": 40, "duration": 1.0})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_drive_forward_custom_params(mock_send):
    mock_send.return_value = {"status": "ok", "action": "forward"}

    result = drive_forward(speed=60, duration=2.5)

    mock_send.assert_called_once_with("drive_forward", {"speed": 60, "duration": 2.5})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_drive_reverse_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "reverse"}

    result = drive_reverse()

    mock_send.assert_called_once_with("drive_reverse", {"speed": 40, "duration": 1.0})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_turn_left_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "turn_left"}

    result = turn_left()

    mock_send.assert_called_once_with("turn_left", {"angle": 90})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_turn_left_custom_angle(mock_send):
    mock_send.return_value = {"status": "ok", "action": "turn_left"}

    result = turn_left(angle=45)

    mock_send.assert_called_once_with("turn_left", {"angle": 45})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_turn_right_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "turn_right"}

    result = turn_right()

    mock_send.assert_called_once_with("turn_right", {"angle": 90})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_emergency_stop(mock_send):
    mock_send.return_value = {"status": "ok", "action": "stop"}

    result = emergency_stop()

    mock_send.assert_called_once_with("emergency_stop", {})
    assert result["status"] == "ok"


# ── Distance Drive Tools ─────────────────────────────────────────────────


@patch("tools.act_tools.send_tool_command")
def test_move_inches_without_angle(mock_send):
    mock_send.return_value = {"status": "ok", "action": "move_inches"}

    result = move_inches(distance=5.0)

    mock_send.assert_called_once_with("move_inches", {"distance": 5.0})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_move_inches_with_angle(mock_send):
    mock_send.return_value = {"status": "ok", "action": "move_inches"}

    result = move_inches(distance=10.0, angle=180)

    mock_send.assert_called_once_with("move_inches", {"distance": 10.0, "angle": 180})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_move_centimeters_without_angle(mock_send):
    mock_send.return_value = {"status": "ok", "action": "move_centimeters"}

    result = move_centimeters(distance=15.0)

    mock_send.assert_called_once_with("move_centimeters", {"distance": 15.0})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_move_centimeters_with_angle(mock_send):
    mock_send.return_value = {"status": "ok", "action": "move_centimeters"}

    result = move_centimeters(distance=20.0, angle=90)

    mock_send.assert_called_once_with(
        "move_centimeters", {"distance": 20.0, "angle": 90}
    )
    assert result["status"] == "ok"


# ── Advanced Movement Tools ──────────────────────────────────────────────


@patch("tools.act_tools.send_tool_command")
def test_drive_circle_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "circle_left"}

    result = drive_circle()

    mock_send.assert_called_once_with(
        "drive_circle", {"direction": "left", "speed": 30, "step": 2}
    )
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_drive_square_custom(mock_send):
    mock_send.return_value = {"status": "ok", "action": "square_right"}

    result = drive_square(direction="right", speed=50, seconds=2.0)

    mock_send.assert_called_once_with(
        "drive_square", {"direction": "right", "speed": 50, "seconds": 2.0}
    )
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_drive_figure_8_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "figure_8"}

    result = drive_figure_8()

    mock_send.assert_called_once_with("drive_figure_8", {"speed": 30, "step": 3})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_parallel_park_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "parallel_park"}

    result = parallel_park()

    mock_send.assert_called_once_with("parallel_park", {"speed": 15})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_j_turn_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "j_turn"}

    result = j_turn()

    mock_send.assert_called_once_with("j_turn", {"speed": 80})
    assert result["status"] == "ok"


# ── LED Tools ─────────────────────────────────────────────────────────────


@patch("tools.act_tools.send_tool_command")
def test_headlights_on(mock_send):
    mock_send.return_value = {"status": "ok", "action": "headlights_on"}

    result = headlights_on()

    mock_send.assert_called_once_with("headlights_on", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_headlights_off(mock_send):
    mock_send.return_value = {"status": "ok", "action": "headlights_off"}

    result = headlights_off()

    mock_send.assert_called_once_with("headlights_off", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_all_lights_on(mock_send):
    mock_send.return_value = {"status": "ok", "action": "all_lights_on"}

    result = all_lights_on()

    mock_send.assert_called_once_with("all_lights_on", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_all_lights_off(mock_send):
    mock_send.return_value = {"status": "ok", "action": "all_lights_off"}

    result = all_lights_off()

    mock_send.assert_called_once_with("all_lights_off", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_hazard_lights_on(mock_send):
    mock_send.return_value = {"status": "ok", "action": "hazard_lights_on"}

    result = hazard_lights_on()

    mock_send.assert_called_once_with("hazard_lights_on", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_signal_left_on(mock_send):
    mock_send.return_value = {"status": "ok", "action": "signal_left_on"}

    result = signal_left_on()

    mock_send.assert_called_once_with("signal_left_on", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_signal_right_off(mock_send):
    mock_send.return_value = {"status": "ok", "action": "signal_right_off"}

    result = signal_right_off()

    mock_send.assert_called_once_with("signal_right_off", {})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_brake_lights_on(mock_send):
    mock_send.return_value = {"status": "ok", "action": "brake_lights_on"}

    result = brake_lights_on()

    mock_send.assert_called_once_with("brake_lights_on", {})
    assert result["status"] == "ok"


# ── Other Tools ───────────────────────────────────────────────────────────


@patch("tools.act_tools.send_tool_command")
def test_play_note_defaults(mock_send):
    mock_send.return_value = {"status": "ok", "action": "play_note", "note": 25, "duration_ms": 500}

    result = play_note(note=25)

    mock_send.assert_called_once_with("play_note", {"note": 25, "duration_ms": 500})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_play_note_custom_duration(mock_send):
    mock_send.return_value = {"status": "ok", "action": "play_note", "note": 34, "duration_ms": 1000}

    result = play_note(note=34, duration_ms=1000)

    mock_send.assert_called_once_with("play_note", {"note": 34, "duration_ms": 1000})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_display_text(mock_send):
    mock_send.return_value = {"status": "ok", "action": "say", "message": "Hello!"}

    result = display_text(message="Hello!")

    mock_send.assert_called_once_with("display_text", {"message": "Hello!"})
    assert result["status"] == "ok"


@patch("tools.act_tools.send_tool_command")
def test_show_emotion(mock_send):
    mock_send.return_value = {"status": "ok", "action": "happy"}

    result = show_emotion(emotion="happy")

    mock_send.assert_called_once_with("show_emotion", {"emotion": "happy"})
    assert result["status"] == "ok"
