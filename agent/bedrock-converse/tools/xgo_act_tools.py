"""Strands @tool definitions for the XGO2 Act layer.

Each tool delegates to xgo_tools.send_xgo_tool_command() — the existing
xgo_tools.py is UNCHANGED.  These thin wrappers give the Strands SDK
the type hints and docstrings it needs to auto-generate tool schemas.

Safety clamping (speed 1-25) is handled internally by
xgo_tools.send_xgo_tool_command, so tools just pass through parameters.
"""

import os
import sys

# Add the xgo_tools directory to sys.path so we can import send_xgo_tool_command
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "example", "xgo2", "components", "xgo2-vision-navigation"
    ),
)

from strands import tool

from xgo_tools import send_xgo_tool_command  # noqa: E402


# ── XGO2 Navigation Tools ────────────────────────────────────────────────


@tool
def xgo_navigate_to_target(target_label: str, max_steps: int = 100, speed: int = 15) -> dict:
    """Start vision-guided navigation on the XGO2 robodog toward a target object.

    Args:
        target_label: Object class label to navigate toward (e.g. 'person', 'cup').
        max_steps: Maximum navigation steps (1-500). Default 100.
        speed: Walk speed (1-25). Default 15.
    """
    return send_xgo_tool_command(
        "xgo_navigate_to_target",
        {"target_label": target_label, "max_steps": max_steps, "speed": speed},
    )


@tool
def xgo_check_navigation_status() -> dict:
    """Check the status of an active navigation session on the XGO2."""
    return send_xgo_tool_command("xgo_check_navigation_status", {})


@tool
def xgo_stop_navigation() -> dict:
    """Stop any active navigation session on the XGO2."""
    return send_xgo_tool_command("xgo_stop_navigation", {})


# ── XGO2 Arm / Gripper Tools ─────────────────────────────────────────────


@tool
def xgo_arm(arm_x: int = 0, arm_z: int = 0) -> dict:
    """Move the XGO2 robodog's arm to a position.

    The arm has two axes: forward/back (x) and up/down (z).

    Args:
        arm_x: Forward/back position (-80 to 155). Negative = back, positive = forward. Default 0.
        arm_z: Up/down position (-95 to 155). Negative = down, positive = up. Default 0.
    """
    return send_xgo_tool_command(
        "xgo_arm",
        {"arm_x": arm_x, "arm_z": arm_z},
    )


@tool
def xgo_claw(pos: int = 128) -> dict:
    """Open or close the XGO2 robodog's gripper claw.

    Args:
        pos: Claw position (0 = fully closed, 255 = fully open). Default 128 (half open).
    """
    return send_xgo_tool_command(
        "xgo_claw",
        {"pos": pos},
    )


@tool
def xgo_action(action_id: int) -> dict:
    """Make the XGO2 robodog perform a preset action.

    Available actions:
    1=get down, 2=stand up, 3=crawl forward, 4=circle, 5=marking time,
    6=squat, 7=rotate roll, 8=rotate pitch, 9=rotate yaw,
    10=three axis rotation, 11=pee, 12=sit down, 13=wave, 14=stretch,
    15=wave (alt), 16=swing left/right, 17=seeking food, 18=find food,
    19=handshake, 20=greetings

    Args:
        action_id: Preset action ID (1-20).
    """
    return send_xgo_tool_command(
        "xgo_action",
        {"action_id": action_id},
    )


# ── XGO2 Grip Calibration Tools ──────────────────────────────────────────


@tool
def xgo_start_grip(
    max_iterations: int = 50,
    convergence_tolerance: int = 15,
    arm_step_limit: int = 10,
) -> dict:
    """Start vision-guided grip calibration on the XGO2 robodog.

    The robot will detect a red ball, servo the arm toward it using
    continuous camera feedback, and attempt to grip it when the arm
    converges on the ball position.

    Args:
        max_iterations: Maximum servoing iterations before timeout (1-200). Default 50.
        convergence_tolerance: Pixel tolerance for convergence (1-100). Default 15.
        arm_step_limit: Maximum arm step size per axis per iteration (1-50). Default 10.
    """
    return send_xgo_tool_command(
        "xgo_start_grip",
        {
            "max_iterations": max_iterations,
            "convergence_tolerance": convergence_tolerance,
            "arm_step_limit": arm_step_limit,
        },
    )


@tool
def xgo_check_grip_status() -> dict:
    """Check the status of an active or completed grip calibration session on the XGO2."""
    return send_xgo_tool_command("xgo_check_grip_status", {})


@tool
def xgo_stop_grip() -> dict:
    """Stop any active grip calibration session on the XGO2.

    The claw will open and the arm will return to home position.
    """
    return send_xgo_tool_command("xgo_stop_grip", {})
