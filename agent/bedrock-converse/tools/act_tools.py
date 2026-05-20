"""Strands @tool definitions for the Act layer.

Each tool delegates to iot_client.send_tool_command() — the existing
iot_client.py is UNCHANGED.  These thin wrappers give the Strands SDK
the type hints and docstrings it needs to auto-generate tool schemas.

Safety clamping (speed 1-80, duration 0.1-5.0, etc.) is handled
internally by iot_client.send_tool_command, so tools just pass through
parameters.
"""

from strands import tool

from iot_client import send_tool_command


# ── Drive Tools ───────────────────────────────────────────────────────────


@tool
def drive_forward(speed: int = 40, duration: float = 1.0) -> dict:
    """Drive Zumi forward at the given speed for the given duration.

    Args:
        speed: Driving speed (1-80). Default 40.
        duration: Duration in seconds (0.1-5.0). Default 1.0.
    """
    return send_tool_command("drive_forward", {"speed": speed, "duration": duration})


@tool
def drive_reverse(speed: int = 40, duration: float = 1.0) -> dict:
    """Drive Zumi in reverse at the given speed for the given duration.

    Args:
        speed: Driving speed (1-80). Default 40.
        duration: Duration in seconds (0.1-5.0). Default 1.0.
    """
    return send_tool_command("drive_reverse", {"speed": speed, "duration": duration})


@tool
def turn_left(angle: int = 90) -> dict:
    """Turn Zumi left by the specified angle.

    Args:
        angle: Turn angle in degrees (1-360). Default 90.
    """
    return send_tool_command("turn_left", {"angle": angle})


@tool
def turn_right(angle: int = 90) -> dict:
    """Turn Zumi right by the specified angle.

    Args:
        angle: Turn angle in degrees (1-360). Default 90.
    """
    return send_tool_command("turn_right", {"angle": angle})


@tool
def emergency_stop() -> dict:
    """Immediately stop all motor activity on Zumi."""
    return send_tool_command("emergency_stop", {})


@tool
def move_inches(distance: float, angle: int | None = None) -> dict:
    """Drive Zumi a precise distance in inches using PID-controlled movement.

    Args:
        distance: Distance in inches (0.5-24.0).
        angle: Heading angle in degrees (0-360). Uses current heading if omitted.
    """
    params: dict = {"distance": distance}
    if angle is not None:
        params["angle"] = angle
    return send_tool_command("move_inches", params)


@tool
def move_centimeters(distance: float, angle: int | None = None) -> dict:
    """Drive Zumi a precise distance in centimeters using PID-controlled movement.

    Args:
        distance: Distance in centimeters (1.0-60.0).
        angle: Heading angle in degrees (0-360). Uses current heading if omitted.
    """
    params: dict = {"distance": distance}
    if angle is not None:
        params["angle"] = angle
    return send_tool_command("move_centimeters", params)


# ── Advanced Movement Tools ───────────────────────────────────────────────


@tool
def drive_circle(direction: str = "left", speed: int = 30, step: int = 2) -> dict:
    """Drive Zumi in a circle. Requires open floor space.

    Args:
        direction: Circle direction — 'left' or 'right'. Default 'left'.
        speed: Driving speed (1-80). Default 30.
        step: Angle step size (1-10). Smaller means wider circle. Default 2.
    """
    return send_tool_command(
        "drive_circle", {"direction": direction, "speed": speed, "step": step}
    )


@tool
def drive_square(direction: str = "left", speed: int = 40, seconds: float = 1.0) -> dict:
    """Drive Zumi in a square pattern. Requires open floor space.

    Args:
        direction: Square direction — 'left' or 'right'. Default 'left'.
        speed: Driving speed (1-80). Default 40.
        seconds: Duration per side in seconds (0.5-3.0). Default 1.0.
    """
    return send_tool_command(
        "drive_square", {"direction": direction, "speed": speed, "seconds": seconds}
    )


@tool
def drive_figure_8(speed: int = 30, step: int = 3) -> dict:
    """Drive Zumi in a figure-8 pattern. Requires open floor space.

    Args:
        speed: Driving speed (1-50). Default 30.
        step: Angle step size (1-10). Default 3.
    """
    return send_tool_command("drive_figure_8", {"speed": speed, "step": step})


@tool
def parallel_park(speed: int = 15) -> dict:
    """Perform a parallel parking maneuver. Requires open floor space.

    Args:
        speed: Driving speed (1-30). Default 15.
    """
    return send_tool_command("parallel_park", {"speed": speed})


@tool
def j_turn(speed: int = 80) -> dict:
    """Perform a J-turn (reverse 180-degree turn). Requires open floor space.

    Args:
        speed: Driving speed (1-80). Default 80.
    """
    return send_tool_command("j_turn", {"speed": speed})


# ── LED Tools ─────────────────────────────────────────────────────────────


@tool
def headlights_on() -> dict:
    """Turn on Zumi's front headlight LEDs."""
    return send_tool_command("headlights_on", {})


@tool
def headlights_off() -> dict:
    """Turn off Zumi's front headlight LEDs."""
    return send_tool_command("headlights_off", {})


@tool
def all_lights_on() -> dict:
    """Turn on all of Zumi's LEDs (front headlights and rear brake lights)."""
    return send_tool_command("all_lights_on", {})


@tool
def all_lights_off() -> dict:
    """Turn off all of Zumi's LEDs."""
    return send_tool_command("all_lights_off", {})


@tool
def hazard_lights_on() -> dict:
    """Turn on Zumi's hazard lights (flashing front and back LEDs)."""
    return send_tool_command("hazard_lights_on", {})


@tool
def hazard_lights_off() -> dict:
    """Turn off Zumi's hazard lights."""
    return send_tool_command("hazard_lights_off", {})


@tool
def signal_left_on() -> dict:
    """Turn on Zumi's left turn signal (flashing left LEDs)."""
    return send_tool_command("signal_left_on", {})


@tool
def signal_left_off() -> dict:
    """Turn off Zumi's left turn signal."""
    return send_tool_command("signal_left_off", {})


@tool
def signal_right_on() -> dict:
    """Turn on Zumi's right turn signal (flashing right LEDs)."""
    return send_tool_command("signal_right_on", {})


@tool
def signal_right_off() -> dict:
    """Turn off Zumi's right turn signal."""
    return send_tool_command("signal_right_off", {})


@tool
def brake_lights_on() -> dict:
    """Turn on Zumi's rear brake lights."""
    return send_tool_command("brake_lights_on", {})


@tool
def brake_lights_off() -> dict:
    """Turn off Zumi's rear brake lights."""
    return send_tool_command("brake_lights_off", {})


# ── Other Tools ───────────────────────────────────────────────────────────


@tool
def play_note(note: int, duration_ms: int = 500) -> dict:
    """Play a musical note on Zumi's buzzer.

    Args:
        note: Note number 1-60 (C2=1, C4=25, A4=34, B6=60).
        duration_ms: Duration in milliseconds (100-2500). Default 500.
    """
    return send_tool_command("play_note", {"note": note, "duration_ms": duration_ms})


@tool
def display_text(message: str) -> dict:
    """Display a text message on Zumi's OLED screen (128x64 pixels).

    Args:
        message: Text to display on Zumi's screen. Keep it short.
    """
    return send_tool_command("display_text", {"message": message})


@tool
def show_emotion(emotion: str) -> dict:
    """Show an emotion or expression on Zumi's OLED screen using animated eyes.

    Args:
        emotion: The emotion to display (happy, sad, angry, hello, sleeping, blink, glimmer, look_around).
    """
    return send_tool_command("show_emotion", {"emotion": emotion})
