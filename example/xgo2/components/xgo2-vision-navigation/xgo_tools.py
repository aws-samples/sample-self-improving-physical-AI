"""
XGO2 robodog tool definitions for Bedrock Converse API.

Each tool maps to a vision navigation command published to the XGO2
via MQTT (IoT Core). The XGO2 runs a Greengrass component
(com.xgo.VisionNavigation) that subscribes to these commands.

MQTT topics:
  - Command:  xgo-robodog/vision/command   (publish navigation commands)
  - Status:   xgo-robodog/vision/status     (subscribe for navigation status)
"""

import json
import logging
import time
import uuid
import boto3

log = logging.getLogger("xgo-tools")

# ── MQTT Configuration ────────────────────────────────────────────────

XGO_COMMAND_TOPIC = "xgo-robodog/vision/command"
XGO_STATUS_TOPIC = "xgo-robodog/vision/status"

XGO_GRIP_COMMAND_TOPIC = "xgo-robodog/grip/command"
XGO_GRIP_STATUS_TOPIC = "xgo-robodog/grip/status"

# ── IoT Data Client ───────────────────────────────────────────────────

_iot_data = None


def _get_iot_data_client(
    endpoint: str | None = None,
    region: str | None = None,
):
    """Lazy-initialize the IoT Data client.

    When called without explicit parameters, attempts to read
    ``XGO2_IOT_ENDPOINT`` and ``XGO2_IOT_REGION`` from the chatbot
    ``config`` module.  If the import fails (e.g. running on the
    device side where ``config.py`` is not on ``sys.path``), falls
    back to ``us-east-1`` with no custom endpoint.

    Parameters
    ----------
    endpoint : str, optional
        Custom IoT endpoint URL. When *None* the client tries the
        chatbot config value, then falls back to the default regional
        endpoint resolved by boto3.
    region : str, optional
        AWS region for the IoT Data client. When *None* the client
        tries the chatbot config value, then falls back to
        ``"us-east-1"``.
    """
    global _iot_data
    if _iot_data is None:
        # Try to use chatbot config values when available
        if endpoint is None or region is None:
            try:
                import config as _cfg
                if endpoint is None:
                    endpoint = getattr(_cfg, "XGO2_IOT_ENDPOINT", None)
                if region is None:
                    region = getattr(_cfg, "XGO2_IOT_REGION", "us-east-1")
            except ImportError:
                pass
        if region is None:
            region = "us-east-1"

        kwargs = {"region_name": region}
        if endpoint:
            kwargs["endpoint_url"] = f"https://{endpoint}"
        _iot_data = boto3.client("iot-data", **kwargs)
    return _iot_data


def _publish_command(payload: dict) -> dict:
    """Publish a JSON command to the XGO2 vision command topic."""
    client = _get_iot_data_client()
    message = json.dumps(payload)
    log.info("Publishing to %s: %s", XGO_COMMAND_TOPIC, message)
    client.publish(topic=XGO_COMMAND_TOPIC, qos=1, payload=message)
    return payload


# ── Tool Definitions ──────────────────────────────────────────────────

XGO_TOOLS = [
    {
        "toolSpec": {
            "name": "xgo_navigate_to_target",
            "description": (
                "Start vision-guided navigation on the XGO2 robodog "
                "toward a target object."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "target_label": {
                            "type": "string",
                            "description": (
                                "Object class label to navigate toward "
                                "(e.g. 'person', 'cup')"
                            ),
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": (
                                "Maximum navigation steps (default 100)"
                            ),
                            "minimum": 1,
                            "maximum": 500,
                        },
                        "speed": {
                            "type": "integer",
                            "description": (
                                "Walk speed (1-25, default 15)"
                            ),
                            "minimum": 1,
                            "maximum": 25,
                        },
                    },
                    "required": ["target_label"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "xgo_check_navigation_status",
            "description": (
                "Check the status of an active navigation session "
                "on the XGO2."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "xgo_stop_navigation",
            "description": (
                "Stop any active navigation session on the XGO2."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "xgo_start_grip",
            "description": (
                "Start vision-guided grip calibration on the XGO2 robodog. "
                "The robot will detect a red ball, servo the arm toward it, "
                "and attempt to grip it."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "max_iterations": {
                            "type": "integer",
                            "description": (
                                "Maximum servoing iterations (default 50)"
                            ),
                            "minimum": 1,
                            "maximum": 200,
                        },
                        "convergence_tolerance": {
                            "type": "integer",
                            "description": (
                                "Convergence pixel tolerance (default 15)"
                            ),
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "arm_step_limit": {
                            "type": "integer",
                            "description": (
                                "Maximum arm step size per axis (default 10)"
                            ),
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "xgo_check_grip_status",
            "description": (
                "Check the status of an active or completed grip "
                "calibration session on the XGO2."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "xgo_stop_grip",
            "description": (
                "Stop any active grip calibration session on the XGO2. "
                "The claw will open and the arm will return to home position."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
            },
        }
    },
]


# ── MQTT Publish Handlers ─────────────────────────────────────────────


def handle_xgo_navigate(tool_input: dict) -> dict:
    """Start vision-guided navigation and wait for completion.

    Publishes a navigate_to_target command to the XGO2, then polls the
    retained status topic until the navigation session completes or a
    timeout is reached.

    Parameters
    ----------
    tool_input : dict
        Must contain ``target_label`` (str).
        May contain ``max_steps`` (int), ``speed`` (int, max 25),
        and ``confidence_threshold`` (float).

    Returns
    -------
    dict
        Result with termination_reason, steps_completed, and target_label.
    """
    target_label = tool_input.get("target_label", "")
    cmd: dict = {
        "action": "navigate_to_target",
        "target_label": target_label,
    }

    if "max_steps" in tool_input:
        cmd["max_steps"] = int(tool_input["max_steps"])

    if "speed" in tool_input:
        speed = int(tool_input["speed"])
        speed = max(1, min(speed, 25))
        cmd["speed"] = speed

    if "confidence_threshold" in tool_input:
        cmd["confidence_threshold"] = float(tool_input["confidence_threshold"])

    _publish_command(cmd)
    log.info("Navigation started: target=%s", target_label)

    # Poll for completion via retained status message (max 90s)
    client = _get_iot_data_client()
    deadline = time.time() + 90.0
    poll_interval = 2.0

    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            response = client.get_retained_message(topic=XGO_STATUS_TOPIC)
            payload_bytes = response.get("payload", b"")
            if payload_bytes:
                status = json.loads(payload_bytes)
                if status.get("status") == "completed" and status.get("target_label") == target_label:
                    reason = status.get("termination_reason", "unknown")
                    steps = status.get("steps_completed", 0)
                    log.info("Navigation completed: reason=%s, steps=%d", reason, steps)
                    return {
                        "status": "ok",
                        "action": "navigate_to_target",
                        "target_label": target_label,
                        "termination_reason": reason,
                        "steps_completed": steps,
                        "note": "Navigation %s after %d steps." % (reason, steps),
                    }
        except Exception:
            pass

    log.warning("Navigation poll timeout for target=%s", target_label)
    return {
        "status": "ok",
        "action": "navigate_to_target",
        "target_label": target_label,
        "termination_reason": "poll_timeout",
        "steps_completed": 0,
        "note": (
            "Navigation command was sent but the result could not be confirmed "
            "within 90 seconds. Use xgo_check_navigation_status to check."
        ),
    }


def handle_xgo_check_status() -> dict:
    """Get the latest navigation status from the XGO2.

    The device publishes retained status messages to the
    ``xgo-robodog/vision/status`` topic. This handler retrieves the
    latest retained message via the IoT Data ``get_retained_message``
    API.  If no retained message is available it falls back to a
    descriptive note.

    Returns
    -------
    dict
        The latest navigation status payload, or a note if unavailable.
    """
    client = _get_iot_data_client()
    try:
        response = client.get_retained_message(topic=XGO_STATUS_TOPIC)
        payload_bytes = response.get("payload", b"")
        if payload_bytes:
            status_payload = json.loads(payload_bytes)
            return {
                "status": "ok",
                "action": "check_navigation_status",
                "navigation_status": status_payload,
            }
    except client.exceptions.ResourceNotFoundException:
        log.info("No retained message on %s", XGO_STATUS_TOPIC)
    except Exception as exc:
        log.warning("Failed to get retained status: %s", exc)

    return {
        "status": "ok",
        "action": "check_navigation_status",
        "note": (
            "No retained navigation status available. The XGO2 "
            "publishes status updates to the "
            "xgo-robodog/vision/status topic while a navigation "
            "session is active. The status includes: step count, "
            "target detected, bearing, action taken, and "
            "termination reason when complete."
        ),
    }


def handle_xgo_stop() -> dict:
    """Publish a stop command to terminate any active navigation session.

    Returns
    -------
    dict
        Acknowledgment that the stop command was sent.
    """
    _publish_command({"action": "stop"})

    return {
        "status": "ok",
        "action": "stop_navigation",
        "note": (
            "Stop command sent to XGO2. Any active navigation "
            "session will be terminated and the robot will return "
            "to a safe standing posture."
        ),
    }


def handle_xgo_arm(tool_input: dict) -> dict:
    """Move the XGO2's arm to a position.

    Parameters
    ----------
    tool_input : dict
        Must contain ``arm_x`` (int, -80 to 155) and ``arm_z`` (int, -95 to 155).

    Returns
    -------
    dict
        Acknowledgment with the arm position.
    """
    arm_x = int(tool_input.get("arm_x", 0))
    arm_z = int(tool_input.get("arm_z", 0))
    arm_x = max(-80, min(155, arm_x))
    arm_z = max(-95, min(155, arm_z))

    _publish_command({"action": "arm", "arm_x": arm_x, "arm_z": arm_z})

    return {
        "status": "ok",
        "action": "arm",
        "arm_x": arm_x,
        "arm_z": arm_z,
        "note": "Arm moved to position x=%d, z=%d." % (arm_x, arm_z),
    }


def handle_xgo_claw(tool_input: dict) -> dict:
    """Open or close the XGO2's gripper claw.

    Parameters
    ----------
    tool_input : dict
        Must contain ``pos`` (int, 0=closed to 255=fully open).

    Returns
    -------
    dict
        Acknowledgment with the claw position.
    """
    pos = int(tool_input.get("pos", 128))
    pos = max(0, min(255, pos))

    _publish_command({"action": "claw", "pos": pos})

    state = "open" if pos > 128 else "closed" if pos < 50 else "partially open"
    return {
        "status": "ok",
        "action": "claw",
        "pos": pos,
        "note": "Gripper claw set to %d (%s)." % (pos, state),
    }


def handle_xgo_action(tool_input: dict) -> dict:
    """Execute a preset action on the XGO2.

    Parameters
    ----------
    tool_input : dict
        Must contain ``action_id`` (int, 1-20).

    Returns
    -------
    dict
        Acknowledgment with the action ID.
    """
    action_id = int(tool_input.get("action_id", 1))
    action_id = max(1, min(255, action_id))

    ACTION_NAMES = {
        1: "get down", 2: "stand up", 3: "crawl forward", 4: "circle",
        5: "marking time", 6: "squat", 7: "rotate roll", 8: "rotate pitch",
        9: "rotate yaw", 10: "three axis rotation", 11: "pee", 12: "sit down",
        13: "wave", 14: "stretch", 15: "wave (alt)", 16: "swing left/right",
        17: "seeking food", 18: "find food", 19: "handshake", 20: "greetings",
    }
    name = ACTION_NAMES.get(action_id, "action #%d" % action_id)

    _publish_command({"action": "xgo_action", "action_id": action_id})

    return {
        "status": "ok",
        "action": "xgo_action",
        "action_id": action_id,
        "note": "XGO2 performing: %s." % name,
    }


# ── Grip Calibration Handlers ─────────────────────────────────────────


def _publish_grip_command(payload: dict) -> dict:
    """Publish a JSON command to the XGO2 grip command topic."""
    client = _get_iot_data_client()
    message = json.dumps(payload)
    log.info("Publishing to %s: %s", XGO_GRIP_COMMAND_TOPIC, message)
    client.publish(topic=XGO_GRIP_COMMAND_TOPIC, qos=1, payload=message)
    return payload


def handle_xgo_start_grip(tool_input: dict) -> dict:
    """Start vision-guided grip calibration and wait for completion.

    Publishes a ``start_grip`` command to the XGO2 grip command topic,
    then polls the grip status topic until the session completes or a
    120-second timeout is reached.

    Parameters
    ----------
    tool_input : dict
        May contain ``max_iterations`` (int), ``convergence_tolerance``
        (int, pixels), and ``arm_step_limit`` (int).

    Returns
    -------
    dict
        Result with termination_reason and grip session details.
    """
    cmd: dict = {"action": "start_grip"}

    if "max_iterations" in tool_input:
        cmd["max_iterations"] = int(tool_input["max_iterations"])

    if "convergence_tolerance" in tool_input:
        cmd["convergence_tolerance"] = int(tool_input["convergence_tolerance"])

    if "arm_step_limit" in tool_input:
        cmd["arm_step_limit"] = int(tool_input["arm_step_limit"])

    _publish_grip_command(cmd)
    log.info("Grip calibration started")

    # Poll for completion via retained status message (max 120s)
    client = _get_iot_data_client()
    deadline = time.time() + 120.0
    poll_interval = 2.0

    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            response = client.get_retained_message(topic=XGO_GRIP_STATUS_TOPIC)
            payload_bytes = response.get("payload", b"")
            if payload_bytes:
                status = json.loads(payload_bytes)
                termination_reason = status.get("termination_reason")
                if termination_reason is not None:
                    log.info(
                        "Grip session completed: reason=%s",
                        termination_reason,
                    )
                    return {
                        "status": "ok",
                        "action": "start_grip",
                        "termination_reason": termination_reason,
                        "grip_status": status,
                        "note": "Grip session ended: %s." % termination_reason,
                    }
        except Exception:
            pass

    log.warning("Grip status poll timeout")
    return {
        "status": "ok",
        "action": "start_grip",
        "termination_reason": "poll_timeout",
        "note": (
            "Grip command was sent but the result could not be confirmed "
            "within 120 seconds. Use xgo_check_grip_status to check."
        ),
    }


def handle_xgo_check_grip_status() -> dict:
    """Get the latest grip calibration status from the XGO2.

    Retrieves the latest retained message from the
    ``xgo-robodog/grip/status`` topic via the IoT Data
    ``get_retained_message`` API.

    Returns
    -------
    dict
        The latest grip status payload, or a note if unavailable.
    """
    client = _get_iot_data_client()
    try:
        response = client.get_retained_message(topic=XGO_GRIP_STATUS_TOPIC)
        payload_bytes = response.get("payload", b"")
        if payload_bytes:
            status_payload = json.loads(payload_bytes)
            return {
                "status": "ok",
                "action": "check_grip_status",
                "grip_status": status_payload,
            }
    except client.exceptions.ResourceNotFoundException:
        log.info("No retained message on %s", XGO_GRIP_STATUS_TOPIC)
    except Exception as exc:
        log.warning("Failed to get retained grip status: %s", exc)

    return {
        "status": "ok",
        "action": "check_grip_status",
        "note": (
            "No retained grip status available. The XGO2 publishes "
            "status updates to the xgo-robodog/grip/status topic "
            "while a grip session is active. The status includes: "
            "step number, ball detected, ball position, arm position, "
            "servoing error, convergence state, and termination reason "
            "when complete."
        ),
    }


def handle_xgo_stop_grip() -> dict:
    """Publish a stop command to terminate any active grip session.

    Returns
    -------
    dict
        Acknowledgment that the stop command was sent.
    """
    _publish_grip_command({"action": "stop_grip"})

    return {
        "status": "ok",
        "action": "stop_grip",
        "note": (
            "Stop grip command sent to XGO2. Any active grip "
            "session will be terminated, the claw will open, "
            "and the arm will return to home position."
        ),
    }


# ── S3 Photo Flow (same pattern as Zumi iot_client.py) ───────────────

_s3_client = None


def _get_s3_client():
    """Lazy-initialize the S3 client."""
    global _s3_client
    if _s3_client is None:
        try:
            import config as _cfg
            _s3_client = boto3.client("s3", region_name=getattr(_cfg, "S3_REGION", "us-east-1"))
        except ImportError:
            _s3_client = boto3.client("s3", region_name="us-east-1")
    return _s3_client


def _get_s3_config():
    """Get S3 bucket and presign expiry from chatbot config."""
    try:
        import config as _cfg
        return {
            "bucket": getattr(_cfg, "S3_BUCKET", "zumi-chatbot-photos"),
            "expiry": getattr(_cfg, "S3_PRESIGN_EXPIRY", 300),
            "thing_name": getattr(_cfg, "XGO2_THING_NAME", "xgo-robodog"),
        }
    except ImportError:
        return {"bucket": "zumi-chatbot-photos", "expiry": 300, "thing_name": "xgo-robodog"}


def handle_xgo_take_photo(tool_input: dict) -> dict:
    """Take a photo on the XGO2 via S3 presigned URL flow.

    Generates a presigned PUT URL, sends it to the device via MQTT,
    then polls S3 until the photo appears (or times out).

    Returns
    -------
    dict
        Result with status, image_url, s3_key on success;
        status 'timeout' on failure.
    """
    s3 = _get_s3_client()
    cfg = _get_s3_config()

    # Generate unique S3 key
    ts = time.strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:8]
    s3_key = "photos/%s/%s-%s.jpg" % (cfg["thing_name"], ts, uid)

    # Generate presigned PUT URL
    put_url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": cfg["bucket"],
            "Key": s3_key,
            "ContentType": "image/jpeg",
        },
        ExpiresIn=cfg["expiry"],
    )

    # Send take_photo command to XGO2 via MQTT
    _publish_command({
        "action": "take_photo",
        "upload_url": put_url,
        "s3_key": s3_key,
    })

    # Poll S3 for the photo (30s timeout)
    deadline = time.time() + 30.0
    while time.time() < deadline:
        try:
            s3.head_object(Bucket=cfg["bucket"], Key=s3_key)
            log.info("XGO2 photo found in S3: %s", s3_key)
            # Generate GET URL for the browser
            get_url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": cfg["bucket"], "Key": s3_key},
                ExpiresIn=cfg["expiry"],
            )
            return {
                "status": "ok",
                "action": "take_photo",
                "image_url": get_url,
                "s3_key": s3_key,
            }
        except s3.exceptions.ClientError:
            pass
        time.sleep(2.0)

    log.warning("Timed out waiting for XGO2 photo: %s", s3_key)
    return {
        "status": "timeout",
        "action": "take_photo",
        "note": "Photo capture was requested but the upload did not complete in time.",
    }


def handle_xgo_analyze_photo(tool_input: dict) -> dict:
    """Analyze a photo using Bedrock Claude (cloud-side).

    Reuses the same analyze_photo logic as the Zumi iot_client.
    Delegates to iot_client._analyze_photo if available.
    """
    try:
        from iot_client import send_tool_command as _zumi_send
        return _zumi_send("analyze_photo", tool_input)
    except ImportError:
        return {
            "status": "error",
            "action": "analyze_photo",
            "message": "analyze_photo not available (iot_client not importable)",
        }


def send_xgo_tool_command(tool_name: str, tool_input: dict) -> dict:
    """Map a Bedrock tool call to an XGO2 command and execute it.

    This is the single dispatch point for all XGO2 tools, following
    the same pattern as the Zumi ``send_tool_command`` in
    ``robolink-zumi/chatbot/iot_client.py``.

    Parameters
    ----------
    tool_name : str
        The tool name from the Bedrock Converse API response.
    tool_input : dict
        The tool input parameters.

    Returns
    -------
    dict
        Result dict to send back to Bedrock as tool output.
    """
    if tool_name == "xgo_navigate_to_target":
        return handle_xgo_navigate(tool_input)

    elif tool_name == "xgo_check_navigation_status":
        return handle_xgo_check_status()

    elif tool_name == "xgo_stop_navigation":
        return handle_xgo_stop()

    elif tool_name == "xgo_arm":
        return handle_xgo_arm(tool_input)

    elif tool_name == "xgo_claw":
        return handle_xgo_claw(tool_input)

    elif tool_name == "xgo_action":
        return handle_xgo_action(tool_input)

    elif tool_name == "take_photo":
        return handle_xgo_take_photo(tool_input)

    elif tool_name == "analyze_photo":
        return handle_xgo_analyze_photo(tool_input)

    elif tool_name == "xgo_start_grip":
        return handle_xgo_start_grip(tool_input)

    elif tool_name == "xgo_check_grip_status":
        return handle_xgo_check_grip_status()

    elif tool_name == "xgo_stop_grip":
        return handle_xgo_stop_grip()

    else:
        return {"status": "error", "message": f"Unknown XGO tool: {tool_name}"}
