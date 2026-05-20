"""Perception Agent — observes the environment using the active robot's camera and sensors.

This module implements the Perception layer of the agentic architecture.
It wraps a Strands Agent with vision tools (take_photo, analyze_photo,
read_sensors, read_orientation) and exposes a ``perceive`` @tool function
that the Orchestrator invokes to get structured observation data.

The perception system prompt is built dynamically from a shared preamble
plus the active hardware profile's ``perception_prompt_fragment``.

The module uses a lazy-init pattern: call ``init_perception_agent(model)``
once at startup, then the ``perceive`` tool is ready for use.
"""

from __future__ import annotations

import json
import re
from typing import Any

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

import config
from hardware_registry import get_profile
from tools.perception_tools import (
    take_photo,
    analyze_photo,
    read_sensors,
    read_orientation,
)
from iot_client import send_tool_command

PERCEPTION_PREAMBLE = """\
You are the Perception Layer of a robot control system.
Your job is to observe the environment using the robot's camera and sensors.

When asked to perceive:
1. Take a photo using take_photo (if available)
2. Analyze the photo for the requested target using analyze_photo (if available)
3. Read sensors if additional context is needed
4. Return a structured observation with: what you see, where objects are, \
estimated distances, and confidence levels.

You MUST return your observations as structured JSON data. Always include:
- found: whether the target was detected
- position: left/center/right relative to camera frame
- estimated_distance_cm: distance estimate (null if uncertain)
- confidence: high/medium/low
- description: what you observe in the scene"""

# Keep the old prompt for backward compatibility.
PERCEPTION_SYSTEM_PROMPT = """\
You are the Perception Layer of a Zumi robot control system.
Your job is to observe the environment using the robot's camera and sensors.

When asked to perceive:
1. Take a photo using take_photo
2. Analyze the photo for the requested target using analyze_photo
3. Read sensors if additional context is needed (IR proximity, orientation)
4. Return a structured observation with: what you see, where objects are, \
estimated distances, and confidence levels.

You MUST return your observations as structured JSON data. Always include:
- found: whether the target was detected
- position: left/center/right relative to camera frame
- estimated_distance_cm: distance estimate (null if uncertain)
- confidence: high/medium/low
- description: what you observe in the scene

Camera is mounted ~5cm above ground, facing forward on a small robot car."""


def create_perception_agent(model: BedrockModel, perception_prompt_fragment: str = "") -> Agent:
    """Create the perception layer agent with vision tools.

    The system prompt is built from the shared ``PERCEPTION_PREAMBLE``
    plus the optional *perception_prompt_fragment* from the active
    hardware profile.
    """
    system_prompt = PERCEPTION_PREAMBLE
    if perception_prompt_fragment:
        system_prompt += "\n\n" + perception_prompt_fragment
    return Agent(
        model=model,
        tools=[take_photo, analyze_photo, read_sensors, read_orientation],
        system_prompt=system_prompt,
        callback_handler=None,
    )


# Module-level agent instance (lazy-init via init_perception_agent).
_perception_agent: Agent | None = None


def init_perception_agent(model: BedrockModel, perception_prompt_fragment: str = "") -> None:
    """Initialize the module-level perception agent.

    Must be called once at startup before the ``perceive`` tool is used.

    Args:
        model: The Bedrock model to use for the perception agent.
        perception_prompt_fragment: Optional prompt fragment from the active
            hardware profile to append to the shared preamble.
    """
    global _perception_agent
    _perception_agent = create_perception_agent(model, perception_prompt_fragment)


def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from mixed text.

    Handles cases where the agent wraps JSON in markdown code fences
    or includes preamble text before/after the JSON block.
    """
    # Try the raw text first.
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Try to find a JSON block inside markdown fences.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except (ValueError, TypeError):
            pass

    # Try to find the first { ... } block.
    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except (ValueError, TypeError):
            pass

    return None


@tool
def perceive(query: str, robot_id: str = "") -> dict[str, Any]:
    """Observe the environment using the active robot's camera and sensors.

    For robots that support cloud-side photo capture (e.g. Zumi), takes a
    photo, analyzes it for the described target, and returns structured
    perception data.  For robots whose camera is handled on-device
    (e.g. XGO2), returns a status indicating cloud-side capture is not
    available.

    Args:
        query: Natural language description of what to look for,
               e.g. "look around for a wrist watch"
        robot_id: Robot identifier. Defaults to ``config.DEFAULT_ROBOT``
                  when empty.

    Returns:
        dict with keys: found, position, estimated_distance_cm,
        confidence, description, image_url
    """
    # Determine active robot profile.
    _robot_id = robot_id or config.DEFAULT_ROBOT
    profile = get_profile(_robot_id)

    # If the robot doesn't support cloud-side photo capture, return early.
    if "take_photo" not in profile.tool_names:
        return {
            "found": False,
            "position": None,
            "estimated_distance_cm": None,
            "confidence": "low",
            "description": (
                "Cloud-side photo capture is not available for %s. "
                "The %s's camera and vision processing are handled "
                "by its on-device system." % (profile.display_name, profile.display_name)
            ),
            "image_url": None,
        }

    # ── S3 presigned URL photo flow (Zumi and any robot with take_photo) ──

    # Step 1: Take a photo via the profile's send_command.
    try:
        photo_result = profile.send_command("take_photo", {})
    except Exception as e:
        return {
            "found": False,
            "position": None,
            "estimated_distance_cm": None,
            "confidence": "low",
            "description": "Photo capture failed: %s" % e,
            "image_url": None,
        }

    if photo_result.get("status") != "ok":
        return {
            "found": False,
            "position": None,
            "estimated_distance_cm": None,
            "confidence": "low",
            "description": "Photo capture failed: %s" % photo_result.get("note", "unknown error"),
            "image_url": None,
        }

    image_url = photo_result.get("image_url")

    # Step 2: Analyze the photo for the target.
    try:
        analysis = profile.send_command("analyze_photo", {
            "image_url": image_url,
            "target_description": query,
        })
    except Exception as e:
        return {
            "found": False,
            "position": None,
            "estimated_distance_cm": None,
            "confidence": "low",
            "description": "Photo analysis failed: %s" % e,
            "image_url": image_url,
        }

    # Step 3: Build the result, always including the image_url.
    return {
        "found": bool(analysis.get("found", False)),
        "position": analysis.get("position"),
        "estimated_distance_cm": analysis.get("estimated_distance_cm"),
        "confidence": analysis.get("confidence", "low"),
        "description": analysis.get("description", ""),
        "image_url": image_url,
    }
