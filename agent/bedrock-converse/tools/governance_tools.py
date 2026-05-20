"""Strands @tool definitions for the Governance layer.

Pure logic tools — no IoT or Bedrock dependencies.  These validate
actions against safety policies, evaluate outcomes, and check overall
safety state.  Parameters are JSON strings because Strands tools work
with primitive types; each function parses them internally.
"""

from __future__ import annotations

import json

from strands import tool

import config
from hardware_registry import get_profile


# ── Known Zumi Actions (kept for backward compatibility) ──────────────────

KNOWN_ACTIONS = {
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
}

MOVEMENT_ACTIONS = {
    "drive_forward", "drive_reverse", "turn_left", "turn_right",
    "move_inches", "move_centimeters",
    "drive_circle", "drive_square", "drive_figure_8",
    "parallel_park", "j_turn",
    # XGO2 navigation action (also involves movement)
    "xgo_navigate_to_target",
}


# ── Helper ────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> tuple[float, bool]:
    """Clamp *value* to [lo, hi].  Returns (clamped, was_clamped)."""
    clamped = max(lo, min(hi, value))
    return clamped, clamped != value


# ── Tools ─────────────────────────────────────────────────────────────────

@tool
def validate_action(action: str, parameters: str, context: str, robot_id: str = "") -> dict:
    """Validate a requested action against safety policies.

    Args:
        action: The action name (e.g. "drive_forward", "xgo_navigate_to_target").
        parameters: JSON string of action parameters
            (e.g. '{"speed": 40, "duration": 1.0}').
        context: JSON string of current state context
            (e.g. '{"cumulative_distance_cm": 50, "vision_guided": true}').
        robot_id: Robot identifier. Defaults to config.DEFAULT_ROBOT.

    Returns:
        dict with keys:
            approved (bool), safety_notes (list[str]),
            modified_parameters (dict|None), reason (str).
    """
    _robot_id = robot_id or config.DEFAULT_ROBOT
    profile = get_profile(_robot_id)

    params: dict = json.loads(parameters) if parameters else {}
    ctx: dict = json.loads(context) if context else {}

    # Emergency stop actions are ALWAYS approved immediately.
    if action in profile.emergency_stop_actions:
        return {
            "approved": True,
            "safety_notes": [],
            "modified_parameters": None,
            "reason": "",
        }

    # Unknown actions are blocked.
    if action not in profile.tool_names:
        return {
            "approved": False,
            "safety_notes": [],
            "modified_parameters": None,
            "reason": f"Unknown action: {action}",
        }

    # Non-movement actions (LEDs, buzzer, screen, camera, sensors) — always approved.
    if action not in MOVEMENT_ACTIONS:
        return {
            "approved": True,
            "safety_notes": [],
            "modified_parameters": None,
            "reason": "",
        }

    # ── Movement action checks ────────────────────────────────────────

    cumulative = ctx.get("cumulative_distance_cm", 0.0)

    # Block if cumulative distance already exceeded.
    if cumulative > profile.safety_limits.max_cumulative_distance_cm:
        return {
            "approved": False,
            "safety_notes": [],
            "modified_parameters": None,
            "reason": f"Cumulative distance limit exceeded (>{profile.safety_limits.max_cumulative_distance_cm}cm)",
        }

    safety_notes: list[str] = []
    modified: dict | None = None

    vision_guided = ctx.get("vision_guided", False)

    if vision_guided:
        # Vision-guided navigation: clamp speed and distance to profile limits.
        max_vis_speed = profile.safety_limits.max_vision_speed
        max_dist = profile.safety_limits.max_distance_per_step_cm
        mod = dict(params)
        changed = False

        if "speed" in mod:
            clamped_speed, was_clamped = _clamp(mod["speed"], 1, max_vis_speed)
            if was_clamped:
                safety_notes.append(
                    f"Speed clamped from {mod['speed']} to {clamped_speed} (vision-guided max {max_vis_speed})"
                )
                mod["speed"] = clamped_speed
                changed = True

        if "distance" in mod:
            clamped_dist, was_clamped = _clamp(mod["distance"], 0.5, max_dist)
            if was_clamped:
                safety_notes.append(
                    f"Distance clamped from {mod['distance']} to {clamped_dist} (vision-guided max {max_dist}cm)"
                )
                mod["distance"] = clamped_dist
                changed = True

        if changed:
            modified = mod
    else:
        # General movement: clamp speed to [1, max_speed], duration to [0.1, 5.0].
        max_speed = profile.safety_limits.max_speed
        mod = dict(params)
        changed = False

        if "speed" in mod:
            clamped_speed, was_clamped = _clamp(mod["speed"], 1, max_speed)
            if was_clamped:
                safety_notes.append(
                    f"Speed clamped from {mod['speed']} to {clamped_speed} (range 1-{max_speed})"
                )
                mod["speed"] = clamped_speed
                changed = True

        if "duration" in mod:
            clamped_dur, was_clamped = _clamp(mod["duration"], 0.1, 5.0)
            if was_clamped:
                safety_notes.append(
                    f"Duration clamped from {mod['duration']} to {clamped_dur} (range 0.1-5.0)"
                )
                mod["duration"] = clamped_dur
                changed = True

        if changed:
            modified = mod

    return {
        "approved": True,
        "safety_notes": safety_notes,
        "modified_parameters": modified,
        "reason": "",
    }


@tool
def evaluate_outcome(action: str, result: str, context: str) -> dict:
    """Evaluate the outcome of an executed action.

    Args:
        action: The action that was executed.
        result: JSON string of the execution result
            (e.g. '{"status": "ok"}').
        context: JSON string of current state context
            (e.g. '{"no_progress_count": 3}').

    Returns:
        dict with keys:
            feedback (str: "goal_met"/"continue"/"abort"),
            notes (list[str]).
    """
    res: dict = json.loads(result) if result else {}
    ctx: dict = json.loads(context) if context else {}

    status = res.get("status", "")

    if status == "error":
        return {"feedback": "abort", "notes": [f"Action '{action}' returned error"]}

    if status == "blocked":
        return {"feedback": "continue", "notes": [f"Action '{action}' was blocked, try a different approach"]}

    no_progress = ctx.get("no_progress_count", 0)
    if no_progress >= 5:
        return {
            "feedback": "abort",
            "notes": ["5 consecutive actions without progress"],
        }

    return {"feedback": "continue", "notes": []}


@tool
def check_safety_state(cumulative_distance_cm: float, no_progress_count: int, robot_id: str = "") -> dict:
    """Check overall safety state of the current session.

    Args:
        cumulative_distance_cm: Total distance moved so far in cm.
        no_progress_count: Number of consecutive actions without progress.
        robot_id: Robot identifier. Defaults to config.DEFAULT_ROBOT.

    Returns:
        dict with keys:
            safe (bool), recommendations (list[str]).
    """
    _robot_id = robot_id or config.DEFAULT_ROBOT
    profile = get_profile(_robot_id)

    recommendations: list[str] = []
    safe = True

    max_cumulative = profile.safety_limits.max_cumulative_distance_cm
    if cumulative_distance_cm > max_cumulative:
        safe = False
        recommendations.append(f"Abort: cumulative distance exceeded {max_cumulative}cm")

    if no_progress_count >= 5:
        safe = False
        recommendations.append("Abort: 5 consecutive actions without progress")

    return {"safe": safe, "recommendations": recommendations}
