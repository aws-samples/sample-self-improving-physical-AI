"""Hardware registry — stores and retrieves HardwareProfile instances by robot_id.

Pre-populated with Zumi and XGO2 profiles at import time. Any layer can
call ``get_profile(robot_id)`` to obtain the active robot's configuration
without hardcoded references.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Dict, List

from hardware_profile import HardwareProfile, IoTConfig, SafetyLimits
import config
from iot_client import send_tool_command as _zumi_send_command

# Add the xgo_tools directory to sys.path so we can import send_xgo_tool_command
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "example", "xgo2", "components", "xgo2-vision-navigation"
    ),
)
from xgo_tools import send_xgo_tool_command as _xgo_send_command  # noqa: E402

log = logging.getLogger("hardware-registry")

# ── Module-level registry ─────────────────────────────────────────────────

_registry: Dict[str, HardwareProfile] = {}


# ── Public API ────────────────────────────────────────────────────────────


def register_profile(profile: HardwareProfile) -> None:
    """Register a hardware profile. Overwrites any existing profile with the same robot_id."""
    _registry[profile.robot_id] = profile


def get_profile(robot_id: str) -> HardwareProfile:
    """Retrieve a profile by robot_id.

    Raises ``ValueError`` listing all available robot IDs when the
    requested ``robot_id`` is not registered.
    """
    if robot_id not in _registry:
        available = sorted(_registry.keys())
        raise ValueError(
            f"Unknown robot_id '{robot_id}'. Available robots: {available}"
        )
    return _registry[robot_id]


def list_robots() -> List[dict]:
    """Return a list of dicts with ``robot_id``, ``display_name``, and ``capability_tags``
    for every registered profile.
    """
    return [
        {
            "robot_id": p.robot_id,
            "display_name": p.display_name,
            "capability_tags": list(p.capability_tags),
        }
        for p in _registry.values()
    ]


def get_available_ids() -> List[str]:
    """Return a sorted list of all registered robot_id strings."""
    return sorted(_registry.keys())


# ── Zumi system prompt fragment ───────────────────────────────────────────


_ZUMI_SYSTEM_PROMPT_FRAGMENT = """\
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


# ── XGO2 system prompt fragment ──────────────────────────────────────────

_XGO2_SYSTEM_PROMPT_FRAGMENT = """\
## Available Actions for governed_execute

### Vision-Guided Navigation
- xgo_navigate_to_target: Start vision-guided navigation toward a target object.
  Parameters: {"target_label": "object class label (e.g. 'person', 'cup')", "max_steps": 1-500 (optional, default 100), "speed": 1-25 (optional, default 15)}
- xgo_check_navigation_status: Check the status of an active navigation session (no parameters).
  Returns: step count, target detected, bearing, action taken, and termination reason when complete.
- xgo_stop_navigation: Stop any active navigation session immediately (no parameters).
  The robot will return to a safe standing posture.

### Arm / Gripper
- xgo_arm: Move the robot's arm. Parameters: {"arm_x": -80 to 155 (forward/back), "arm_z": -95 to 155 (up/down)}
  arm_x: negative = retract back, positive = extend forward. arm_z: negative = lower, positive = raise.
- xgo_claw: Open or close the gripper claw. Parameters: {"pos": 0-255}
  0 = fully closed, 255 = fully open, 128 = half open.

### Preset Actions
- xgo_action: Perform a preset action. Parameters: {"action_id": 1-20}
  1=get down, 2=stand up, 3=crawl forward, 4=circle, 5=marking time,
  6=squat, 7=rotate roll, 8=rotate pitch, 9=rotate yaw,
  10=three axis rotation, 11=pee, 12=sit down, 13=wave, 14=stretch,
  15=wave (alt), 16=swing left/right, 17=seeking food, 18=find food,
  19=handshake, 20=greetings

### Camera
- Use perceive() for camera operations (photo capture and analysis)

## How to Use

For "grab the X" or "pick up the X" commands (MUST follow this sequence):
1. Use perceive() to take a photo and confirm the target is visible
2. Open the claw: governed_execute(action="xgo_claw", parameters='{"pos": 255}')
3. Navigate to the target: governed_execute(action="xgo_navigate_to_target", parameters='{"target_label": "...", "speed": 10}')
   - This command BLOCKS until navigation completes and returns the result
   - Check termination_reason: "target_reached" means success, "target_lost" means the object wasn't found
4. If target_reached: lower the arm, close the claw, raise the arm:
   - governed_execute(action="xgo_arm", parameters='{"arm_x": 80, "arm_z": -70}')
   - governed_execute(action="xgo_claw", parameters='{"pos": 0}')
   - governed_execute(action="xgo_arm", parameters='{"arm_x": 0, "arm_z": 80}')
5. Use perceive() to take a photo and verify the grab succeeded
6. Report the result to the user

For navigation commands like "walk to the cup":
1. Use perceive() first to confirm the target is visible
2. Use governed_execute() with xgo_navigate_to_target — it blocks until done
3. The result includes termination_reason: target_reached, target_lost, stopped, timeout, tilt_detected
4. Use perceive() after to verify the robot's new position
5. Report the result to the user

For arm/gripper commands like "open the claw":
1. Use governed_execute() with xgo_arm or xgo_claw directly

For preset actions like "wave" or "sit down":
1. Use governed_execute() with xgo_action and the appropriate action_id

## Target Labels for Navigation
The on-device ML model (SSD MobileNet V1 COCO) recognizes these common objects:
person, bicycle, car, cat, dog, chair, couch, potted plant, bed, dining table,
toilet, tv, laptop, mouse, remote, keyboard, cell phone, book, clock, vase,
scissors, teddy bear, toothbrush, cup, fork, knife, spoon, bowl, banana, apple,
sandwich, orange, pizza, cake, bottle, wine glass, sports ball, frisbee, backpack,
umbrella, handbag, tie, suitcase, skateboard, surfboard, tennis racket

Additionally, a color-based detector recognizes:
red_ball — any red spherical object (detected by color, not ML model)

NOTE: For a red ball, use target_label "red_ball" (color-based detection).
For other balls (soccer, basketball), use "sports ball" (ML model detection).

## Safety Guidelines
- The XGO2 is a quadruped robot — it walks, not drives. Max speed is 25.
- Before the FIRST movement in a conversation, warn the user about physical movement
- If the user says "stop!" or similar, immediately use governed_execute with xgo_stop_navigation
- Always tell the user what the robot is doing at each step
- ALWAYS use perceive() before and after physical actions to verify the environment
- Navigation is vision-guided: the robot uses its camera and local ML model to detect and approach targets
- The arm has limited reach — position carefully before gripping

## Photo Display
- When a photo is taken, mention it is shown below. Do NOT include the URL in text.

IMPORTANT: When calling governed_execute, the parameters and context arguments must be JSON strings.
For example: governed_execute(action="xgo_navigate_to_target", parameters='{"target_label": "cup", "speed": 15}', context='{"cumulative_distance_cm": 0}')"""


# ── Zumi perception prompt fragment ──────────────────────────────────────

_ZUMI_PERCEPTION_PROMPT = """\
Zumi is equipped with:
- 6 IR sensors (2 front, 2 bottom, 2 rear) for obstacle and line detection
- A gyroscope/accelerometer (MPU) for orientation sensing
- A front-facing camera mounted approximately 5cm above the ground
The camera captures JPEG images uploaded to S3 via presigned URLs. \
Vision analysis uses Bedrock Claude 3 Haiku to detect objects, estimate \
positions (left/center/right), and approximate distances in centimeters."""


# ── XGO2 perception prompt fragment ─────────────────────────────────────

_XGO2_PERCEPTION_PROMPT = """\
XGO2 is equipped with:
- A front-facing camera with on-device ML inference (SSD MobileNet V1) for object detection
- A 2-inch LCD display for status and visual feedback
Camera and vision processing run entirely on-device via the Greengrass \
VisionNavigation component. Cloud-side photo capture is not available — \
the XGO2's camera is managed by its on-device Bedrock reasoner. \
Navigation decisions (bearing, obstacle avoidance) are computed locally."""


# ── Zumi governance prompt fragment ──────────────────────────────────────

_ZUMI_GOVERNANCE_PROMPT = """\
Zumi safety constraints:
- Maximum speed: 80 (absolute), 60 during vision-guided navigation
- Maximum distance per movement step: 20 cm (during vision-guided navigation)
- Maximum cumulative distance per command sequence: 100 cm
- Maximum navigation steps: 200
- Emergency stop action: emergency_stop (bypasses all validation)
Speed and duration parameters are clamped to safe ranges by the IoT client."""


# ── XGO2 governance prompt fragment ─────────────────────────────────────

_XGO2_GOVERNANCE_PROMPT = """\
XGO2 safety constraints:
- Maximum walk speed: 25
- Maximum vision-guided navigation speed: 25
- Maximum distance per navigation step: 50 cm
- Maximum cumulative distance per command sequence: 500 cm
- Maximum navigation steps: 500
- Emergency stop action: xgo_stop_navigation (bypasses all validation)
The XGO2 is a quadruped — it walks slowly and deliberately. \
Speed is clamped to 25 by the device-side handler."""


# ── Zumi tool names ──────────────────────────────────────────────────────

_ZUMI_TOOL_NAMES: tuple[str, ...] = (
    # Drive
    "drive_forward",
    "drive_reverse",
    "turn_left",
    "turn_right",
    "emergency_stop",
    "move_inches",
    "move_centimeters",
    # Advanced movement
    "drive_circle",
    "drive_square",
    "drive_figure_8",
    "parallel_park",
    "j_turn",
    # LEDs
    "headlights_on",
    "headlights_off",
    "all_lights_on",
    "all_lights_off",
    "hazard_lights_on",
    "hazard_lights_off",
    "signal_left_on",
    "signal_left_off",
    "signal_right_on",
    "signal_right_off",
    "brake_lights_on",
    "brake_lights_off",
    # Buzzer
    "play_note",
    # Screen
    "display_text",
    "show_emotion",
    # Perception
    "take_photo",
    "analyze_photo",
    "read_sensors",
    "read_orientation",
)

# ── XGO2 tool names ─────────────────────────────────────────────────────

_XGO2_TOOL_NAMES: tuple[str, ...] = (
    "xgo_navigate_to_target",
    "xgo_check_navigation_status",
    "xgo_stop_navigation",
    "xgo_arm",
    "xgo_claw",
    "xgo_action",
    "take_photo",
    "analyze_photo",
)


# ── Register profiles at module load time ────────────────────────────────

_ZUMI_PROFILE = HardwareProfile(
    robot_id="zumi",
    display_name="Zumi",
    system_prompt_fragment=_ZUMI_SYSTEM_PROMPT_FRAGMENT,
    tool_names=_ZUMI_TOOL_NAMES,
    iot_config=IoTConfig(
        endpoint=config.IOT_ENDPOINT,
        region=config.IOT_REGION,
        thing_name=config.IOT_THING_NAME,
        command_topic=f"zumi/{config.IOT_THING_NAME}/command",
    ),
    safety_limits=SafetyLimits(
        max_speed=80,
        max_vision_speed=60,
        max_distance_per_step_cm=20.0,
        max_cumulative_distance_cm=100.0,
        max_navigation_steps=200,
    ),
    capability_tags=(
        "differential_drive",
        "ir_sensors",
        "buzzer",
        "oled_screen",
        "camera",
        "vision_navigation",
    ),
    perception_prompt_fragment=_ZUMI_PERCEPTION_PROMPT,
    governance_prompt_fragment=_ZUMI_GOVERNANCE_PROMPT,
    greeting_message=(
        "Hi! I'm Zumi Bot. I can control the Zumi robot car — drive, "
        "flash LEDs, play music, take photos, and more. What would you "
        "like to do?"
    ),
    send_command=_zumi_send_command,
    emergency_stop_actions=("emergency_stop",),
)

_XGO2_PROFILE = HardwareProfile(
    robot_id="xgo2",
    display_name="XGO2 Robodog",
    system_prompt_fragment=_XGO2_SYSTEM_PROMPT_FRAGMENT,
    tool_names=_XGO2_TOOL_NAMES,
    iot_config=IoTConfig(
        endpoint=config.XGO2_IOT_ENDPOINT,
        region=config.XGO2_IOT_REGION,
        thing_name=config.XGO2_THING_NAME,
        command_topic="xgo-robodog/vision/command",
    ),
    safety_limits=SafetyLimits(
        max_speed=25,
        max_vision_speed=25,
        max_distance_per_step_cm=50.0,
        max_cumulative_distance_cm=500.0,
        max_navigation_steps=500,
    ),
    capability_tags=(
        "quadruped",
        "vision_navigation",
        "lcd_display",
        "camera",
    ),
    perception_prompt_fragment=_XGO2_PERCEPTION_PROMPT,
    governance_prompt_fragment=_XGO2_GOVERNANCE_PROMPT,
    greeting_message=(
        "Hi! I'm XGO2 Bot. I can control the XGO2 robodog — navigate to "
        "objects using vision, check navigation status, and stop navigation. "
        "What would you like to do?"
    ),
    send_command=_xgo_send_command,
    emergency_stop_actions=("xgo_stop_navigation",),
)

register_profile(_ZUMI_PROFILE)
register_profile(_XGO2_PROFILE)
