"""Orchestrator — the central Reasoning layer that coordinates all agent layers.

Replaces ``bedrock_chat.py`` with a Strands SDK-based agentic pipeline.
The Orchestrator decomposes user commands, invokes Perception and
Governance/Act layers as tools, maintains conversation history, and
produces the final ``{text, image_url, steps}`` response matching the
existing API contract.

Usage::

    from layer_config import load_layer_configs
    from orchestrator import Orchestrator

    configs = load_layer_configs()
    orch = Orchestrator(configs)
    result = orch.chat("turn on the headlights")
    # result == {"text": "...", "image_url": None, "steps": [...]}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from strands import Agent, tool

import config
from hardware_profile import HardwareProfile
from hardware_registry import get_profile
from layer_config import AgentLayerConfigs
from models import ConversationStep
from perception_agent import init_perception_agent, perceive
from act_agent import init_act_agent, execute_physical_action
from governance_agent import (
    init_governance_agent,
    set_act_agent,
    governed_execute,
)

# Act tool imports for the TOOL_REGISTRY
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
from tools.xgo_act_tools import (
    xgo_navigate_to_target,
    xgo_check_navigation_status,
    xgo_stop_navigation,
    xgo_arm,
    xgo_claw,
    xgo_action,
)
from tools.perception_tools import (
    take_photo,
    analyze_photo,
    read_sensors,
    read_orientation,
)

log = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Tool registry — maps tool name strings to Strands @tool callables
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable] = {
    # Drive
    "drive_forward": drive_forward,
    "drive_reverse": drive_reverse,
    "turn_left": turn_left,
    "turn_right": turn_right,
    "emergency_stop": emergency_stop,
    "move_inches": move_inches,
    "move_centimeters": move_centimeters,
    # Advanced movement
    "drive_circle": drive_circle,
    "drive_square": drive_square,
    "drive_figure_8": drive_figure_8,
    "parallel_park": parallel_park,
    "j_turn": j_turn,
    # LEDs
    "headlights_on": headlights_on,
    "headlights_off": headlights_off,
    "all_lights_on": all_lights_on,
    "all_lights_off": all_lights_off,
    "hazard_lights_on": hazard_lights_on,
    "hazard_lights_off": hazard_lights_off,
    "signal_left_on": signal_left_on,
    "signal_left_off": signal_left_off,
    "signal_right_on": signal_right_on,
    "signal_right_off": signal_right_off,
    "brake_lights_on": brake_lights_on,
    "brake_lights_off": brake_lights_off,
    # Buzzer
    "play_note": play_note,
    # Screen
    "display_text": display_text,
    "show_emotion": show_emotion,
    # XGO2 navigation
    "xgo_navigate_to_target": xgo_navigate_to_target,
    "xgo_check_navigation_status": xgo_check_navigation_status,
    "xgo_stop_navigation": xgo_stop_navigation,
    # XGO2 arm / gripper
    "xgo_arm": xgo_arm,
    "xgo_claw": xgo_claw,
    "xgo_action": xgo_action,
    # Perception
    "take_photo": take_photo,
    "analyze_photo": analyze_photo,
    "read_sensors": read_sensors,
    "read_orientation": read_orientation,
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SHARED_PREAMBLE = """\
You are a friendly assistant that controls a robot using a layered agent architecture.
You are the Reasoning Layer — you plan and coordinate.

You have two tools to invoke other agent layers:
- perceive(query): Ask the Perception layer to observe the environment
- governed_execute(action, parameters, context): Ask the Governance layer to \
validate and execute a physical action"""

# Keep the old constant for backward compatibility.
ORCHESTRATOR_SYSTEM_PROMPT = """\
You are Zumi Bot, a friendly assistant that controls a Robolink Zumi robot
using a layered agent architecture. You are the Reasoning Layer - you plan and coordinate.

You have two tools to invoke other agent layers:
- perceive(query): Ask the Perception layer to observe the environment
- governed_execute(action, parameters, context): Ask the Governance layer to \
validate and execute a physical action

## Available Actions for governed_execute

### Sensors
- read_sensors: Read all 6 IR sensor values (no parameters)
- read_orientation: Get orientation (upright, upside down, etc.) (no parameters)

### LEDs
- headlights_on / headlights_off: Front headlight LEDs
- all_lights_on / all_lights_off: All LEDs
- hazard_lights_on / hazard_lights_off: Flashing hazard lights
- signal_left_on / signal_left_off: Left turn signal
- signal_right_on / signal_right_off: Right turn signal
- brake_lights_on / brake_lights_off: Rear brake lights

### Buzzer
- play_note: Play a musical note. Parameters: {"note": 1-60, "duration_ms": 100-2500}
  Common notes: C4=25, D4=27, E4=29, F4=30, G4=32, A4=34, B4=36

### Screen
- display_text: Show text on OLED. Parameters: {"message": "text"}
- show_emotion: Show animated eyes. Parameters: {"emotion": "happy|sad|angry|hello|sleeping|blink|glimmer|look_around"}

### Camera
- Use perceive() instead of governed_execute for camera operations

### Drive (robot will physically move!)
- drive_forward: Parameters: {"speed": 1-80, "duration": 0.1-5.0}
- drive_reverse: Parameters: {"speed": 1-80, "duration": 0.1-5.0}
- turn_left / turn_right: Parameters: {"angle": 1-360}
- move_inches: PID-controlled. Parameters: {"distance": 0.5-24.0, "angle": 0-360 (optional)}
- move_centimeters: PID-controlled. Parameters: {"distance": 1.0-60.0, "angle": 0-360 (optional)}
- emergency_stop: Immediately stop all motors (no parameters)

### Advanced Movement
- drive_circle: Parameters: {"direction": "left|right", "speed": 1-80, "step": 1-10}
- drive_square: Parameters: {"direction": "left|right", "speed": 1-80, "seconds": 0.5-3.0}
- drive_figure_8: Parameters: {"speed": 1-50, "step": 1-10}
- parallel_park: Parameters: {"speed": 1-30}
- j_turn: Parameters: {"speed": 1-80}

## How to Use

For complex commands like "find the watch and move 1 inch away":
1. Use perceive() to scan the environment
2. Plan a sequence of small movements based on perception
3. Use governed_execute() for each movement step
4. Re-perceive after each movement to verify progress
5. Repeat until the goal is met or governance recommends abort

For simple commands like "turn on the headlights":
1. Use governed_execute() directly with the appropriate action

For compound commands like "play happy music and show a happy face":
1. Break into individual actions
2. Call governed_execute() for each action sequentially

## Safety Guidelines
- Before the FIRST movement in a conversation, warn the user about physical movement
- If the user says "stop!" or similar, immediately use governed_execute with emergency_stop
- Always tell the user what you see and what you are doing at each step
- Vision distance estimation is approximate - prefer multiple small moves

## Photo Display
- When a photo is taken, mention it is shown below. Do NOT include the URL in text.

IMPORTANT: When calling governed_execute, the parameters and context arguments must be JSON strings.
For example: governed_execute(action="drive_forward", parameters='{"speed": 40, "duration": 1.0}', context='{"cumulative_distance_cm": 0}')"""


# ---------------------------------------------------------------------------
# StepCollector
# ---------------------------------------------------------------------------


class StepCollector:
    """Collects reasoning steps, tool calls, and results for the frontend.

    Each step is stored as a :class:`ConversationStep` with layer
    attribution so the UI can display which agent layer produced it.
    """

    def __init__(self) -> None:
        self.steps: list[ConversationStep] = []
        self.image_url: str | None = None

    def add_reasoning(self, text: str, layer: str = "reasoning") -> None:
        """Record a reasoning / text step."""
        self.steps.append(
            ConversationStep(type="reasoning", layer=layer, text=text)
        )

    def add_tool_call(
        self, tool_name: str, input_data: dict, layer: str = ""
    ) -> None:
        """Record a tool invocation."""
        self.steps.append(
            ConversationStep(
                type="tool_call", layer=layer, tool=tool_name, input_data=input_data
            )
        )

    def add_tool_result(
        self, tool_name: str, result: dict, layer: str = ""
    ) -> None:
        """Record a tool result, capturing ``image_url`` if present."""
        if isinstance(result, dict) and result.get("image_url"):
            self.image_url = result["image_url"]
        self.steps.append(
            ConversationStep(
                type="tool_result", layer=layer, tool=tool_name, result=result
            )
        )


# ---------------------------------------------------------------------------
# Module-level state (set before each chat call / on robot switch)
# ---------------------------------------------------------------------------

_current_collector: StepCollector | None = None
_active_robot_id: str = ""  # Set by Orchestrator.__init__ and select_robot


# ---------------------------------------------------------------------------
# Wrapper tools that log to the step collector
# ---------------------------------------------------------------------------


@tool
def _perceive_with_logging(query: str) -> dict:
    """Observe the environment using the active robot's camera and sensors.

    Takes a photo, analyzes it for the described target, and returns
    structured perception data including object detection, position,
    and distance estimates.

    Args:
        query: Natural language description of what to look for,
               e.g. "look around for a wrist watch"

    Returns:
        dict with keys: found, position, estimated_distance_cm,
        confidence, description, image_url
    """
    if _current_collector:
        _current_collector.add_tool_call(
            "perceive", {"query": query}, layer="perception"
        )
    result = perceive(query=query, robot_id=_active_robot_id)
    if _current_collector:
        _current_collector.add_tool_result("perceive", result, layer="perception")
    return result


@tool
def _governed_execute_with_logging(
    action: str, parameters: str, context: str
) -> dict:
    """Validate and execute a physical action with safety governance.

    Calls governance tools directly (deterministic logic, no LLM needed),
    then delegates approved actions to the Act layer.

    Args:
        action: The action name (e.g. "drive_forward", "xgo_navigate_to_target").
        parameters: JSON string of action parameters.
        context: JSON string of current state context
            (e.g. '{"cumulative_distance_cm": 50}').

    Returns:
        dict with keys: status, action, governance, execution_result,
        feedback, cumulative_distance_cm.
    """
    if _current_collector:
        _current_collector.add_tool_call(
            "governed_execute",
            {"action": action, "parameters": parameters},
            layer="governance",
        )
    result = governed_execute(action=action, parameters=parameters, context=context, robot_id=_active_robot_id)
    if _current_collector:
        _current_collector.add_tool_result(
            "governed_execute", result, layer="governance"
        )
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Maximum tool-use rounds the Strands agent is allowed before we stop.
MAX_AGENT_ITERATIONS = 15


class Orchestrator:
    """Main orchestrator that manages the layered agent pipeline.

    Attributes:
        _configs: Per-layer model configurations.
        _profile: The active robot's HardwareProfile.
        _conversation: Conversation history (list of message dicts).
        _cumulative_distance_cm: Total distance moved in this session.
        _movement_warned: Whether the user has been warned about movement.
    """

    def __init__(self, configs: AgentLayerConfigs, robot_id: str | None = None) -> None:
        global _active_robot_id

        self._configs = configs
        self._conversation: list[dict] = []
        self._cumulative_distance_cm: float = 0.0
        self._movement_warned: bool = False

        # Look up the hardware profile.
        _robot_id = robot_id or config.DEFAULT_ROBOT
        self._profile: HardwareProfile = get_profile(_robot_id)
        _active_robot_id = self._profile.robot_id

        # Initialize all sub-agents.
        init_perception_agent(configs.perception.to_bedrock_model())
        init_act_agent(configs.act.to_bedrock_model())
        init_governance_agent(configs.governance.to_bedrock_model())
        set_act_agent(execute_physical_action)

        # Build the reasoning agent.
        self._agent: Agent = self._build_agent()

    # ── Properties ────────────────────────────────────────────────────

    @property
    def active_robot_id(self) -> str:
        """Return the active robot's identifier."""
        return self._profile.robot_id

    @property
    def active_display_name(self) -> str:
        """Return the active robot's display name."""
        return self._profile.display_name

    # ── Agent building ────────────────────────────────────────────────

    def _build_agent(self) -> Agent:
        """Build the reasoning agent with profile-driven prompt and tools."""
        system_prompt = SHARED_PREAMBLE + "\n\n" + self._profile.system_prompt_fragment
        return Agent(
            model=self._configs.reasoning.to_bedrock_model(),
            tools=[_perceive_with_logging, _governed_execute_with_logging],
            system_prompt=system_prompt,
            callback_handler=None,
        )

    # ── Robot switching ───────────────────────────────────────────────

    def select_robot(self, robot_id: str) -> dict:
        """Switch to a different robot. Returns {robot_id, display_name}.

        Resets conversation state, reinitializes all layers, and rebuilds
        the Strands Agent with the new profile's prompt and tools.
        """
        global _active_robot_id

        self._profile = get_profile(robot_id)
        _active_robot_id = self._profile.robot_id
        self.reset()

        # Reinitialize layers.
        init_perception_agent(self._configs.perception.to_bedrock_model())
        init_act_agent(self._configs.act.to_bedrock_model())
        init_governance_agent(self._configs.governance.to_bedrock_model())
        set_act_agent(execute_physical_action)

        self._agent = self._build_agent()
        return {"robot_id": self._profile.robot_id, "display_name": self._profile.display_name}

    def chat(self, user_message: str) -> dict[str, Any]:
        """Process a user message through the layered agent pipeline.

        Returns::

            {
                "text": str,        # non-empty response text
                "image_url": str | None,
                "steps": list[dict] # chronological step dicts
            }
        """
        global _current_collector

        # Append user message to conversation history.
        self._conversation.append({"role": "user", "content": user_message})

        # Create a fresh step collector for this turn.
        collector = StepCollector()
        _current_collector = collector

        try:
            # Invoke the reasoning agent — it will autonomously call
            # perceive and governed_execute as tools via the Strands SDK.
            result = self._agent(user_message)
            response_text = str(result)

            if not response_text or not response_text.strip():
                response_text = "(No response)"

        except Exception as exc:
            log.exception("Orchestrator error during chat")
            error_msg = str(exc)
            # Surface a user-friendly message for common Bedrock errors.
            if "throttl" in error_msg.lower() or "rate" in error_msg.lower():
                response_text = (
                    "I'm being rate-limited by the AI service right now. "
                    "Please wait a moment and try again."
                )
            elif "service" in error_msg.lower() or "500" in error_msg:
                response_text = (
                    "The AI service encountered an error. "
                    "Please try again in a moment."
                )
            else:
                response_text = (
                    "Sorry, something went wrong while processing your request: %s"
                    % error_msg
                )
        finally:
            _current_collector = None

        # Add a reasoning step with the final response.
        collector.add_reasoning(response_text, layer="reasoning")

        # Update cumulative distance from any governed_execute results.
        for step in collector.steps:
            if (
                step.type == "tool_result"
                and step.tool == "governed_execute"
                and isinstance(step.result, dict)
            ):
                new_dist = step.result.get("cumulative_distance_cm")
                if new_dist is not None:
                    try:
                        new_dist_float = float(new_dist)
                        if new_dist_float > self._cumulative_distance_cm:
                            self._cumulative_distance_cm = new_dist_float
                    except (ValueError, TypeError):
                        pass

        # Append assistant response to conversation history.
        self._conversation.append(
            {"role": "assistant", "content": response_text}
        )

        return {
            "text": response_text,
            "image_url": collector.image_url,
            "steps": [s.to_dict() for s in collector.steps],
        }

    def reset(self) -> None:
        """Clear conversation history and reset state."""
        self._conversation = []
        self._cumulative_distance_cm = 0.0
        self._movement_warned = False
