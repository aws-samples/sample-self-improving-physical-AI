"""
AWS IoT Core client — publishes commands, reads telemetry, handles photo uploads.

Photo flow:
  1. Backend generates a presigned S3 PUT URL + unique key
  2. Sends {action: take_photo, upload_url, s3_key} to Zumi via MQTT
  3. Zumi captures photo, uploads JPEG to S3 via HTTP PUT
  4. Zumi publishes ack on photo_ack topic with the s3_key
  5. Backend waits for the ack, then generates a presigned GET URL
"""

import base64
import json
import logging
import time
import urllib.request
import uuid
import threading
import boto3
from config import (
    IOT_ENDPOINT, IOT_REGION, COMMAND_TOPIC, TELEMETRY_TOPIC,
    IOT_THING_NAME, S3_BUCKET, S3_REGION, S3_PRESIGN_EXPIRY,
    PHOTO_ACK_TOPIC, BEDROCK_REGION,
)

log = logging.getLogger("iot-client")

_iot_data = boto3.client(
    "iot-data",
    region_name=IOT_REGION,
    endpoint_url=f"https://{IOT_ENDPOINT}",
)

_s3 = boto3.client("s3", region_name=S3_REGION)

# ── Photo ack tracking ───────────────────────────────────────────────────
# Stores {s3_key: {"status": ..., "event": threading.Event}}
_photo_acks = {}
_photo_acks_lock = threading.Lock()

# MQTT connection for subscribing to photo acks (lazy-init)
_mqtt_connection = None
_mqtt_subscribed = False


def _ensure_photo_ack_subscription():
    """Subscribe to the photo_ack topic via IoT MQTT-over-WSS so we can
    receive the ack from the device.  Falls back to polling S3 if this
    fails (e.g. missing IoT credentials for WSS)."""
    global _mqtt_subscribed
    if _mqtt_subscribed:
        return
    # We'll use the polling approach instead of a persistent MQTT
    # subscription — simpler for a POC and avoids needing WSS creds.
    _mqtt_subscribed = True


def publish_command(payload: dict) -> dict:
    """Publish a JSON command to the Zumi command topic."""
    message = json.dumps(payload)
    log.info(f"Publishing to {COMMAND_TOPIC}: {message}")
    _iot_data.publish(topic=COMMAND_TOPIC, qos=1, payload=message)
    return payload


def _generate_s3_key():
    """Generate a unique S3 key for a photo."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"photos/{IOT_THING_NAME}/{ts}-{uid}.jpg"


def _generate_put_url(s3_key: str) -> str:
    """Generate a presigned PUT URL for the device to upload a photo."""
    url = _s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": s3_key,
            "ContentType": "image/jpeg",
        },
        ExpiresIn=S3_PRESIGN_EXPIRY,
    )
    return url


def _generate_get_url(s3_key: str) -> str:
    """Generate a presigned GET URL for the browser to view a photo."""
    url = _s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": s3_key,
        },
        ExpiresIn=S3_PRESIGN_EXPIRY,
    )
    return url


def _wait_for_photo(s3_key: str, timeout: float = 30.0) -> bool:
    """Poll S3 to check if the photo was uploaded by the device."""
    deadline = time.time() + timeout
    interval = 2.0
    while time.time() < deadline:
        try:
            _s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
            log.info(f"Photo found in S3: {s3_key}")
            return True
        except _s3.exceptions.ClientError:
            pass
        time.sleep(interval)
    log.warning(f"Timed out waiting for photo: {s3_key}")
    return False


# ── Safety clamping helpers ────────────────────────────────────────────


def _clamp(value: float, min_val: float, max_val: float) -> tuple[float, bool]:
    """Clamp a value to [min_val, max_val]. Returns (clamped_value, was_clamped)."""
    clamped = max(min_val, min(max_val, value))
    was_clamped = clamped != value
    return clamped, was_clamped


def _build_clamped_info(original: float, clamped: float, was_clamped: bool) -> dict | None:
    """Build clamped info dict if value was clamped, else None."""
    if was_clamped:
        return {"original": original, "clamped": clamped}
    return None


def _analyze_photo(image_url: str, target_description: str) -> dict:
    """Analyze a photo using Bedrock vision model (Claude 3 Haiku).

    1. Download image bytes from the presigned S3 GET URL
    2. Encode as base64 for Bedrock vision API
    3. Send to Claude 3 Haiku with a structured prompt asking for:
       - found (bool): Is the target object visible?
       - position (str): Where in the frame? left/center/right/null
       - estimated_distance_cm (float|null): Distance estimate
       - confidence (str): high/medium/low
       - description (str): Brief description of what the model sees
    4. Parse the JSON response
    5. Return structured result dict
    """
    # Step 1: Download image from presigned S3 GET URL
    try:
        with urllib.request.urlopen(image_url, timeout=15) as resp:
            image_bytes = resp.read()
    except Exception as e:
        log.error(f"Failed to download image from {image_url}: {e}")
        return {
            "status": "error",
            "action": "analyze_photo",
            "message": f"Failed to download image: {e}",
        }

    # Step 2: Encode as base64 (kept for potential logging/debugging)
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Step 3: Build the vision prompt
    vision_prompt = (
        "You are analyzing an image from a small robot's camera. The camera is mounted\n"
        "on a Zumi robot car, approximately 5cm above the ground, facing forward.\n"
        "\n"
        f"Look for this target: {target_description}\n"
        "\n"
        "Respond in JSON format only, with no other text:\n"
        "{\n"
        '    "found": true/false,\n'
        '    "position": "left" | "center" | "right" | null,\n'
        '    "estimated_distance_cm": <number or null>,\n'
        '    "confidence": "high" | "medium" | "low",\n'
        '    "description": "<brief description of what you see>"\n'
        "}\n"
        "\n"
        "If the target is found, estimate the distance in centimeters based on the\n"
        "apparent size of the object and the camera's low perspective. The Zumi camera\n"
        "is about 5cm above the ground. Common reference: a tennis ball is about 6.5cm\n"
        "in diameter."
    )

    # Step 4: Invoke Bedrock vision model
    try:
        bedrock_runtime = boto3.client(
            "bedrock-runtime", region_name=BEDROCK_REGION
        )
        response = bedrock_runtime.converse(
            modelId="us.anthropic.claude-3-haiku-20240307-v1:0",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": "jpeg",
                                "source": {
                                    "bytes": image_bytes,
                                },
                            },
                        },
                        {
                            "text": vision_prompt,
                        },
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 512, "temperature": 0.0},
        )
    except Exception as e:
        log.error(f"Vision analysis failed: {e}")
        return {
            "status": "error",
            "action": "analyze_photo",
            "message": f"Vision analysis failed: {e}",
        }

    # Step 5: Parse the JSON response from the vision model
    try:
        result_text = response["output"]["message"]["content"][0]["text"]
        parsed = json.loads(result_text)
        return {
            "status": "ok",
            "action": "analyze_photo",
            "found": bool(parsed.get("found", False)),
            "position": parsed.get("position"),
            "estimated_distance_cm": parsed.get("estimated_distance_cm"),
            "confidence": parsed.get("confidence", "low"),
            "description": parsed.get("description", ""),
        }
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log.warning(f"Could not parse vision model response: {e}")
        return {
            "status": "ok",
            "action": "analyze_photo",
            "found": False,
            "position": None,
            "estimated_distance_cm": None,
            "confidence": "low",
            "description": "Could not parse vision model response",
        }


def send_tool_command(tool_name: str, tool_input: dict) -> dict:
    """Map a Bedrock tool call to an IoT command and publish it.

    Returns a result dict that will be sent back to Bedrock as tool output.
    """
    # --- Sensor reads ---
    if tool_name == "read_sensors":
        publish_command({"action": "read_sensors"})
        return {"status": "requested", "note": "Sensor read command sent. The latest telemetry will contain IR sensor data."}

    elif tool_name == "read_battery":
        publish_command({"action": "read_battery"})
        return {"status": "requested", "note": "Battery read command sent. The latest telemetry will contain battery voltage."}

    elif tool_name == "read_orientation":
        publish_command({"action": "read_orientation"})
        return {"status": "requested", "note": "Orientation read command sent. The latest telemetry will contain orientation data."}

    elif tool_name == "read_angles":
        publish_command({"action": "read_angles"})
        return {"status": "requested", "note": "Angles read command sent. The latest telemetry will contain gyro angles."}

    # --- LEDs ---
    elif tool_name in (
        "headlights_on", "headlights_off",
        "all_lights_on", "all_lights_off",
        "hazard_lights_on", "hazard_lights_off",
        "signal_left_on", "signal_left_off",
        "signal_right_on", "signal_right_off",
        "brake_lights_on", "brake_lights_off",
    ):
        publish_command({"action": tool_name})
        return {"status": "ok", "action": tool_name}

    # --- Buzzer ---
    elif tool_name == "play_note":
        note = tool_input.get("note", 30)
        duration_ms = tool_input.get("duration_ms", 500)
        publish_command({"action": "play_note", "note": note, "duration_ms": duration_ms})
        return {"status": "ok", "action": "play_note", "note": note, "duration_ms": duration_ms}

    # --- Screen ---
    elif tool_name == "display_text":
        message = tool_input.get("message", "")
        publish_command({"action": "say", "message": message})
        return {"status": "ok", "action": "say", "message": message}

    elif tool_name == "show_emotion":
        emotion = tool_input.get("emotion", "happy")
        publish_command({"action": emotion})
        return {"status": "ok", "action": emotion}

    # --- Basic Drive ---
    elif tool_name == "drive_forward":
        speed = tool_input.get("speed", 40)
        duration = tool_input.get("duration", 1.0)
        speed, speed_clamped = _clamp(speed, 1, 80)
        duration, dur_clamped = _clamp(duration, 0.1, 5.0)
        publish_command({"action": "forward", "speed": int(speed), "duration": float(duration)})
        result = {"status": "ok", "action": "forward"}
        clamped = {}
        speed_info = _build_clamped_info(tool_input.get("speed", 40), speed, speed_clamped)
        if speed_info:
            clamped["speed"] = speed_info
        dur_info = _build_clamped_info(tool_input.get("duration", 1.0), duration, dur_clamped)
        if dur_info:
            clamped["duration"] = dur_info
        if clamped:
            result["clamped"] = clamped
        return result

    elif tool_name == "drive_reverse":
        speed = tool_input.get("speed", 40)
        duration = tool_input.get("duration", 1.0)
        speed, speed_clamped = _clamp(speed, 1, 80)
        duration, dur_clamped = _clamp(duration, 0.1, 5.0)
        publish_command({"action": "reverse", "speed": int(speed), "duration": float(duration)})
        result = {"status": "ok", "action": "reverse"}
        clamped = {}
        speed_info = _build_clamped_info(tool_input.get("speed", 40), speed, speed_clamped)
        if speed_info:
            clamped["speed"] = speed_info
        dur_info = _build_clamped_info(tool_input.get("duration", 1.0), duration, dur_clamped)
        if dur_info:
            clamped["duration"] = dur_info
        if clamped:
            result["clamped"] = clamped
        return result

    elif tool_name == "turn_left":
        angle = tool_input.get("angle", 90)
        angle, angle_clamped = _clamp(angle, 1, 360)
        publish_command({"action": "turn_left", "angle": int(angle)})
        result = {"status": "ok", "action": "turn_left"}
        clamped = {}
        angle_info = _build_clamped_info(tool_input.get("angle", 90), angle, angle_clamped)
        if angle_info:
            clamped["angle"] = angle_info
        if clamped:
            result["clamped"] = clamped
        return result

    elif tool_name == "turn_right":
        angle = tool_input.get("angle", 90)
        angle, angle_clamped = _clamp(angle, 1, 360)
        publish_command({"action": "turn_right", "angle": int(angle)})
        result = {"status": "ok", "action": "turn_right"}
        clamped = {}
        angle_info = _build_clamped_info(tool_input.get("angle", 90), angle, angle_clamped)
        if angle_info:
            clamped["angle"] = angle_info
        if clamped:
            result["clamped"] = clamped
        return result

    elif tool_name == "emergency_stop":
        publish_command({"action": "stop"})
        return {"status": "ok", "action": "stop"}

    # --- Advanced Movement ---
    elif tool_name == "drive_circle":
        direction = tool_input.get("direction", "left")
        speed = tool_input.get("speed", 30)
        step = tool_input.get("step", 2)
        action = "circle_left" if direction == "left" else "circle_right"
        publish_command({"action": action, "speed": int(speed), "step": int(step)})
        return {"status": "ok", "action": action}

    elif tool_name == "drive_square":
        direction = tool_input.get("direction", "left")
        speed = tool_input.get("speed", 40)
        seconds = tool_input.get("seconds", 1.0)
        action = "square_left" if direction == "left" else "square_right"
        publish_command({"action": action, "speed": int(speed), "seconds": float(seconds)})
        return {"status": "ok", "action": action}

    elif tool_name == "drive_figure_8":
        speed = tool_input.get("speed", 30)
        step = tool_input.get("step", 3)
        publish_command({"action": "figure_8", "speed": int(speed), "step": int(step)})
        return {"status": "ok", "action": "figure_8"}

    elif tool_name == "parallel_park":
        speed = tool_input.get("speed", 15)
        publish_command({"action": "parallel_park", "speed": int(speed)})
        return {"status": "ok", "action": "parallel_park"}

    elif tool_name == "j_turn":
        speed = tool_input.get("speed", 80)
        publish_command({"action": "j_turn", "speed": int(speed)})
        return {"status": "ok", "action": "j_turn"}

    # --- Distance Drive ---
    elif tool_name == "move_inches":
        distance = tool_input.get("distance", 5.0)
        distance, _ = _clamp(distance, 0.5, 24.0)
        cmd = {"action": "move_inches", "distance": float(distance)}
        if "angle" in tool_input:
            cmd["angle"] = int(tool_input["angle"])
        publish_command(cmd)
        return {"status": "ok", "action": "move_inches"}

    elif tool_name == "move_centimeters":
        distance = tool_input.get("distance", 10.0)
        distance, _ = _clamp(distance, 1.0, 60.0)
        cmd = {"action": "move_centimeters", "distance": float(distance)}
        if "angle" in tool_input:
            cmd["angle"] = int(tool_input["angle"])
        publish_command(cmd)
        return {"status": "ok", "action": "move_centimeters"}

    # --- Vision Analysis (cloud-side only) ---
    elif tool_name == "analyze_photo":
        image_url = tool_input.get("image_url", "")
        target_description = tool_input.get("target_description", "")
        return _analyze_photo(image_url, target_description)

    # --- Vision-Guided Navigation ---
    elif tool_name == "navigate_to_target":
        target_label = tool_input.get("target_label", "")
        cmd = {"action": "navigate_to_target", "target_label": target_label}
        if "max_steps" in tool_input:
            cmd["max_steps"] = int(tool_input["max_steps"])
        if "speed" in tool_input:
            speed_val = int(tool_input["speed"])
            # Clamp speed to max 40 for navigation safety
            speed_val, _ = _clamp(speed_val, 1, 40)
            cmd["speed"] = int(speed_val)
        publish_command(cmd)
        return {
            "status": "ok",
            "action": "navigate_to_target",
            "target_label": target_label,
            "note": "Navigation command sent. Zumi will use its camera and local ML model to navigate toward the target. Use check_navigation_status to monitor progress.",
        }

    elif tool_name == "check_navigation_status":
        # Navigation status is published by the device on the telemetry topic.
        # The chatbot doesn't maintain a persistent subscription to telemetry,
        # so we return a note directing the user to check telemetry.
        return {
            "status": "ok",
            "action": "check_navigation_status",
            "note": "Navigation status is published by the device on the telemetry topic. The latest status will include: step count, target detected, bearing, obstacle detected, and action taken. If navigation has completed, the final status will include the termination reason.",
        }

    # --- Camera (presigned S3 upload) ---
    elif tool_name == "take_photo":
        s3_key = _generate_s3_key()
        put_url = _generate_put_url(s3_key)

        # Send the presigned URL to the device
        publish_command({
            "action": "take_photo",
            "upload_url": put_url,
            "s3_key": s3_key,
        })

        # Wait for the photo to appear in S3
        if _wait_for_photo(s3_key, timeout=30.0):
            get_url = _generate_get_url(s3_key)
            return {
                "status": "ok",
                "action": "take_photo",
                "image_url": get_url,
                "s3_key": s3_key,
            }
        else:
            return {
                "status": "timeout",
                "action": "take_photo",
                "note": "Photo capture was requested but the upload did not complete in time. The device may be slow or the camera may have an issue.",
            }

    # --- Calibration ---
    elif tool_name == "calibrate_gyro":
        publish_command({"action": "calibrate_gyro"})
        return {"status": "ok", "action": "calibrate_gyro"}

    elif tool_name == "calibrate_mpu":
        count = tool_input.get("count", 100)
        publish_command({"action": "calibrate_mpu", "count": int(count)})
        return {"status": "ok", "action": "calibrate_mpu"}

    elif tool_name == "speed_calibration":
        speed = tool_input.get("speed", 40)
        ir_threshold = tool_input.get("ir_threshold", 100)
        time_out = tool_input.get("time_out", 3.0)
        cm_per_brick = tool_input.get("cm_per_brick", 2.0)
        publish_command({
            "action": "speed_calibration",
            "speed": int(speed),
            "ir_threshold": int(ir_threshold),
            "time_out": float(time_out),
            "cm_per_brick": float(cm_per_brick),
        })
        return {"status": "ok", "action": "speed_calibration"}

    elif tool_name == "reset_drive":
        publish_command({"action": "reset_drive"})
        return {"status": "ok", "action": "reset_drive"}

    elif tool_name == "reset_gyro":
        publish_command({"action": "reset_gyro"})
        return {"status": "ok", "action": "reset_gyro"}

    elif tool_name == "reset_pid":
        publish_command({"action": "reset_pid"})
        return {"status": "ok", "action": "reset_pid"}

    else:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}
