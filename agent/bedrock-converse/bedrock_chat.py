"""
Bedrock Converse API integration with tool use for Zumi control.

Manages conversation history and handles the tool-use loop:
  User message → Bedrock → (tool call → execute → feed result back) → final text

The chat() function returns a dict with "text" and optional "image_url"
so the frontend can render photos inline.
"""

import json
import logging
import boto3
from config import BEDROCK_REGION, BEDROCK_MODEL_ID
from zumi_tools import ZUMI_TOOLS
from iot_client import send_tool_command

log = logging.getLogger("bedrock-chat")

_bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

SYSTEM_PROMPT = """You are Zumi Bot, a friendly assistant that controls a Robolink Zumi robot.
The Zumi is a small educational robot car with IR sensors, LEDs, a buzzer, an OLED screen, a camera,
and motorized wheels for driving.

You can:
- Read sensors (IR proximity, battery voltage, orientation, gyro angles)
- Control LEDs (headlights, brake lights, hazard lights, turn signals)
- Play musical notes on the buzzer (notes 1-60, C2 to B6)
- Display text or emotions on the OLED screen
- Take photos with the camera and show them to the user
- Drive forward and reverse at controllable speed and duration
- Turn left and right by a specified angle
- Emergency stop to immediately halt all motors
- Drive in shapes: circles, squares, figure-8 patterns
- Perform maneuvers: parallel parking, J-turns
- Drive precise distances in inches or centimeters
- Analyze photos to detect objects and estimate distances (vision-guided movement)
- Calibrate sensors (gyro, MPU, speed prediction) and reset drive state (drive, gyro, PID)

## Safety Guidelines

Before executing the FIRST movement command in a conversation, warn the user that the robot will
physically move and recommend placing Zumi on the floor on a flat surface with clearance around it.

If the user expresses urgency about stopping (e.g. "stop!", "halt!", "it's going to fall!"),
immediately use the emergency_stop tool.

Advanced movement commands (circles, squares, figure-8, parallel park, J-turn) require open floor
space. Warn the user if they haven't confirmed Zumi is on the floor.

## Vision-Guided Movement

When a user asks to move towards a visible object, use an iterative approach:

### Step 1: Initial assessment
1. Call take_photo to capture the current scene
2. Call analyze_photo with the returned image_url and the target description

### Step 2: Align heading
3. If position is "left", turn_left by ~15 degrees; if "right", turn_right by ~15 degrees

### Step 3: Move towards target
4. If distance is estimated, subtract any requested stopping distance (e.g. "stop 1 inch away"
   means subtract ~2.5 cm from the estimated distance). Use move_centimeters with the adjusted
   distance. Move at most 20 cm per step to avoid overshooting.
5. If distance cannot be estimated, move a cautious 5 cm forward.

### Step 4: Verify and repeat
6. After each move, take another photo and call analyze_photo again to check progress.
7. If the target is still far away, repeat steps 2-4. Keep iterating until the target appears
   large in the frame (estimated distance is close to the desired stopping distance) or you have
   made 3 move attempts.
8. If the target is lost after a move, inform the user.

### Important notes
- Vision distance estimation is approximate. Always prefer multiple small moves over one large move.
- When the user specifies a stopping distance (e.g. "stop 1 inch away"), convert to cm (1 inch ≈ 2.5 cm)
  and stop when the estimated distance is at or below that threshold.
- Tell the user what you see and what you're doing at each step so they can follow along.
- If the target is not found initially, inform the user and suggest repositioning Zumi.

## Photo Display

When you take a photo and the tool result contains an image_url, mention that the photo is shown
below your message. Do NOT include the URL in your text — the UI handles displaying it.

## Calibration

If the user reports inaccurate turns or drift, recommend running calibrate_gyro. Zumi must be
stationary on a flat surface during calibration.

The speed_calibration tool requires a physical calibration sheet with 5 horizontal white lines.
Zumi must be placed on the black portion of the sheet before starting. This calibration is needed
for accurate move_inches and move_centimeters commands.

Recommend reset_drive before sequences of precise turns or straight-line driving to clear
accumulated PID errors and reset gyro angles.

## Sensor Data

Sensor readings (IR sensors, gyro angles, orientation, battery voltage) are available both through
periodic telemetry updates and on-demand via the sensor read tools (read_sensors, read_angles,
read_orientation, read_battery).

## Battery Voltage

Interpret battery voltage readings as follows:
- 3.7–4.2V: Fully charged
- 3.3–3.7V: Normal operating range
- 3.0–3.3V: Low battery, recommend charging soon
- Below 3.0V: Critical, Zumi may behave erratically
- ~0.07V: USB-powered (no battery), this is normal when connected via USB
"""

# Conversation history: list of Bedrock message dicts
_conversation = []

MAX_TOOL_ROUNDS = 15


def reset_conversation():
    """Clear conversation history."""
    global _conversation
    _conversation = []


def chat(user_message: str) -> dict:
    """Process a user message through Bedrock with tool use.

    Returns a dict: {"text": "...", "image_url": "..." or None, "steps": [...]}
    where steps is a list of intermediate reasoning and tool calls.
    """
    global _conversation

    _conversation.append({
        "role": "user",
        "content": [{"text": user_message}],
    })

    tool_config = {"tools": ZUMI_TOOLS}
    image_url = None
    steps = []  # Collect intermediate reasoning + tool calls for the frontend

    for _round in range(MAX_TOOL_ROUNDS):
        log.info(f"Bedrock call round {_round + 1}")

        response = _bedrock.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=_conversation,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig=tool_config,
        )

        output_message = response["output"]["message"]
        stop_reason = response["stopReason"]

        _conversation.append(output_message)

        if stop_reason == "tool_use":
            # Capture any reasoning text that precedes tool calls
            for block in output_message["content"]:
                if "text" in block and block["text"].strip():
                    steps.append({"type": "reasoning", "text": block["text"]})

            tool_results = []
            for block in output_message["content"]:
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    tool_name = tool_use["name"]
                    tool_input = tool_use.get("input", {})
                    tool_use_id = tool_use["toolUseId"]

                    log.info(f"Tool call: {tool_name}({json.dumps(tool_input)})")

                    # Record the tool call for the frontend
                    steps.append({
                        "type": "tool_call",
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    result = send_tool_command(tool_name, tool_input)
                    log.info(f"Tool result: {json.dumps(result)}")

                    # Record the tool result for the frontend
                    # Omit image_url from step display (it's large and shown separately)
                    step_result = {k: v for k, v in result.items() if k != "image_url"}
                    steps.append({
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": step_result,
                    })

                    # Capture image URL if present
                    if result.get("image_url"):
                        image_url = result["image_url"]

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": result}],
                        }
                    })

            _conversation.append({
                "role": "user",
                "content": tool_results,
            })
            continue
        else:
            break

    # Extract final text
    text_parts = []
    last_msg = _conversation[-1]
    if last_msg.get("role") == "assistant":
        for block in last_msg.get("content", []):
            if "text" in block:
                text_parts.append(block["text"])

    text = "\n".join(text_parts) if text_parts else "(No response)"
    return {"text": text, "image_url": image_url, "steps": steps}
