"""Act Agent — executes physical commands on the Zumi robot.

This module implements the Act layer of the agentic architecture.
It dispatches action requests directly to ``iot_client.send_tool_command()``
without an intermediate LLM call — the action-to-IoT mapping is
deterministic and doesn't need model reasoning.

The Strands Agent is still created (for potential future use with
ambiguous commands) but the hot path uses direct dispatch for
reliability and speed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from hardware_registry import get_profile
from iot_dispatcher import dispatch_command
from iot_client import send_tool_command
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

log = logging.getLogger("act-agent")

ACT_SYSTEM_PROMPT = """\
You are the Act Layer of a Zumi robot control system.
Your job is to execute physical commands on the robot.

You receive specific action requests and execute them using the available tools.
You do NOT make decisions about what to do - you only execute what you are told.

Rules:
- Execute the requested action using the appropriate tool
- Report the result accurately including any clamping that occurred
- If a tool call fails, report the error - do not retry on your own
- For movement commands, always report the actual parameters used (after clamping)

You have access to: drive, turn, LED, buzzer, screen, and camera tools."""

# All act tools that the agent has access to.
_ALL_ACT_TOOLS = [
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
]

# Actions that iot_client.send_tool_command knows how to handle directly.
_DIRECT_DISPATCH_ACTIONS = {
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
    "read_battery", "read_angles",
}


def create_act_agent(model: BedrockModel) -> Agent:
    """Create the act layer agent with all physical command tools."""
    return Agent(
        model=model,
        tools=_ALL_ACT_TOOLS,
        system_prompt=ACT_SYSTEM_PROMPT,
        callback_handler=None,
    )


# Module-level agent instance (lazy-init via init_act_agent).
_act_agent: Agent | None = None


def init_act_agent(model: BedrockModel) -> None:
    """Initialize the module-level act agent.

    Must be called once at startup before the ``execute_physical_action``
    tool is used.
    """
    global _act_agent
    _act_agent = create_act_agent(model)


@tool
def execute_physical_action(action: str, parameters: str, robot_id: str = "zumi") -> dict:
    """Execute a physical action on the selected robot.

    Looks up the active hardware profile and dispatches the action through
    ``iot_dispatcher.dispatch_command()`` which routes to the profile's
    ``send_command`` callable.  This is faster and more reliable than
    routing through the act agent's Strands model.

    Args:
        action: The action to perform, e.g. "drive_forward", "turn_left",
                "headlights_on", "show_emotion", "play_note".
        parameters: JSON string of action-specific parameters, e.g.
                    '{"speed": 40, "duration": 1.0}'.
        robot_id: Identifier of the robot to dispatch to (default "zumi").

    Returns:
        dict with at minimum: status, action.  On success includes the
        execution result from the profile's send_command.  On error
        includes a message describing the failure.
    """
    # Look up the active profile from the registry.
    profile = get_profile(robot_id)

    # Parse parameters from JSON string.
    try:
        params: dict = json.loads(parameters) if parameters else {}
    except (ValueError, TypeError):
        params = {}

    # Dispatch through profile for known actions — no LLM call needed.
    if action in profile.tool_names:
        result = dispatch_command(profile, action, params)
        log.info("Act dispatch [%s]: %s → %s", profile.display_name, action, result.get("status"))
        return result

    # Unknown action — return error (governance should have caught this).
    log.warning("Act agent received unknown action for %s: %s", profile.display_name, action)
    return {"status": "error", "action": action, "message": "Unknown action for %s: %s" % (profile.display_name, action)}
