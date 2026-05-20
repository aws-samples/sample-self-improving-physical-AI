"""
Main entry point for the XGO2 Vision Navigation Greengrass component.

Device-side module. Python 3.9 compatible.
Initializes hardware, inference engine, navigation controller,
grip calibration controller, and Greengrass IPC. Subscribes to MQTT
commands and dispatches navigation and grip actions.

Requirements: 7.1-7.7, 12.4-12.6
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from typing import Any, Dict, Optional

# Add device-specific library paths so xgolib, xgoedu, LCD_2inch are importable
# when running as a Greengrass component (root user, no /home/pi in PYTHONPATH)
sys.path.insert(0, "/home/pi/cm4-main")

logger = logging.getLogger("com.xgo.VisionNavigation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMAND_TOPIC = "xgo-robodog/vision/command"
GRIP_COMMAND_TOPIC = "xgo-robodog/grip/command"
THING_NAME = "xgo-robodog"
CAMERA_INDEX = 0
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240


def parse_args():
    # type: () -> argparse.Namespace
    """Parse command-line arguments.

    Returns:
        Namespace with ``model_dir`` and ``confidence_threshold`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="XGO2 Vision Navigation — Greengrass component entry point"
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        help="Path to directory containing model files and labels.txt",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.75,
        help="Minimum detection confidence (0.0-1.0). Default 0.75.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Hardware initialisation
# ---------------------------------------------------------------------------

def init_dog():
    # type: () -> Any
    """Initialize the XGO quadruped robot.

    Returns:
        An ``xgolib.XGO`` instance.

    Raises:
        RuntimeError: If the XGO library cannot be loaded or the serial
            port is unavailable.
    """
    try:
        from xgolib import XGO  # type: ignore[import-untyped]

        dog = XGO(port="/dev/ttyAMA0", version="xgolite")
        logger.info("XGO dog initialized (port=/dev/ttyAMA0, version=xgolite)")
        return dog
    except Exception as exc:
        raise RuntimeError(
            "Failed to initialize XGO dog: {}".format(exc)
        )


def init_camera():
    # type: () -> Any
    """Open the camera via OpenCV.

    Returns:
        An ``cv2.VideoCapture`` instance.

    Raises:
        RuntimeError: If the camera cannot be opened.
    """
    import cv2  # type: ignore[import-untyped]

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    if not cap.isOpened():
        raise RuntimeError(
            "Failed to open camera at index {}".format(CAMERA_INDEX)
        )

    logger.info(
        "Camera opened: index=%d, resolution=%dx%d",
        CAMERA_INDEX,
        CAMERA_WIDTH,
        CAMERA_HEIGHT,
    )
    return cap


# ---------------------------------------------------------------------------
# Greengrass IPC
# ---------------------------------------------------------------------------

def init_ipc_client():
    # type: () -> Any
    """Create a Greengrass IPC client.

    Returns:
        A ``GreengrassCoreIPCClientV2`` instance.

    Raises:
        RuntimeError: If the IPC connection cannot be established.
    """
    try:
        from awsiot.greengrasscoreipc.clientv2 import (  # type: ignore[import-untyped]
            GreengrassCoreIPCClientV2,
        )

        client = GreengrassCoreIPCClientV2()
        logger.info("Greengrass IPC client initialized")
        return client
    except Exception as exc:
        raise RuntimeError(
            "Failed to initialize Greengrass IPC client: {}".format(exc)
        )


def subscribe_to_commands(ipc_client, callback):
    # type: (Any, Any) -> None
    """Subscribe to the vision command MQTT topic via IPC.

    Args:
        ipc_client: Greengrass IPC client.
        callback: Callable invoked with the parsed JSON payload dict
            for each incoming message.
    """
    try:
        ipc_client.subscribe_to_iot_core(
            topic_name=COMMAND_TOPIC,
            qos="1",
            on_stream_event=lambda event: _on_command_message(event, callback),
            on_stream_error=_on_command_error,
            on_stream_closed=_on_command_closed,
        )
        logger.info("Subscribed to MQTT topic: %s", COMMAND_TOPIC)
    except Exception as exc:
        logger.error(
            "Failed to subscribe to %s: %s", COMMAND_TOPIC, exc
        )
        raise


def subscribe_to_grip_commands(ipc_client, callback):
    # type: (Any, Any) -> None
    """Subscribe to the grip command MQTT topic via IPC.

    Args:
        ipc_client: Greengrass IPC client.
        callback: Callable invoked with the parsed JSON payload dict
            for each incoming message on ``xgo-robodog/grip/command``.
    """
    try:
        ipc_client.subscribe_to_iot_core(
            topic_name=GRIP_COMMAND_TOPIC,
            qos="1",
            on_stream_event=lambda event: _on_command_message(event, callback),
            on_stream_error=_on_command_error,
            on_stream_closed=_on_command_closed,
        )
        logger.info("Subscribed to MQTT topic: %s", GRIP_COMMAND_TOPIC)
    except Exception as exc:
        logger.error(
            "Failed to subscribe to %s: %s", GRIP_COMMAND_TOPIC, exc
        )
        raise


def _on_command_message(event, callback):
    # type: (Any, Any) -> None
    """Handle an incoming IoT Core message event.

    Parses the JSON payload and forwards it to the callback.
    """
    try:
        message = event.message
        payload_str = message.payload.decode("utf-8") if isinstance(
            message.payload, (bytes, bytearray)
        ) else str(message.payload)

        payload = json.loads(payload_str)
        logger.info("Received command: %s", payload.get("action", "unknown"))
        callback(payload)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse command payload: %s", exc)
    except Exception as exc:
        logger.error("Error handling command message: %s", exc)


def _on_command_error(error):
    # type: (Any) -> bool
    """Handle a subscription stream error."""
    logger.error("Command subscription stream error: %s", error)
    return True  # Return True to keep the subscription alive


def _on_command_closed():
    # type: () -> None
    """Handle subscription stream closure."""
    logger.warning("Command subscription stream closed")


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

class CommandHandler:
    """Dispatches incoming MQTT commands to navigation and grip controllers.

    Handles ``navigate_to_target``, ``stop``, ``start_grip``, and
    ``stop_grip`` actions. Enforces mutual exclusion between navigation
    and grip sessions (Req 12.6). Shows the standby screen on the LCD
    when no session is active.

    Args:
        nav_controller: NavigationController instance.
        lcd_display: LCDDisplay instance (may be None).
        dog: XGO instance for reading battery on standby screen.
        grip_controller: GripCalibrationController instance (may be None).
    """

    def __init__(self, nav_controller, lcd_display, dog, grip_controller=None):
        # type: (Any, Any, Any, Any) -> None
        self._nav = nav_controller
        self._lcd = lcd_display
        self._dog = dog
        self._grip = grip_controller

    def handle(self, payload):
        # type: (Dict[str, Any]) -> None
        """Dispatch a command payload.

        Args:
            payload: Parsed JSON dict with at least an ``action`` key.
        """
        action = payload.get("action")

        if action == "navigate_to_target":
            self._handle_navigate(payload)
        elif action == "stop":
            self._handle_stop()
        elif action == "start_grip":
            self._handle_start_grip(payload)
        elif action == "stop_grip":
            self._handle_stop_grip()
        elif action == "take_photo":
            self._handle_take_photo(payload)
        elif action == "arm":
            self._handle_arm(payload)
        elif action == "claw":
            self._handle_claw(payload)
        elif action == "xgo_action":
            self._handle_action(payload)
        else:
            logger.warning("Unknown command action: %s", action)

    def _handle_navigate(self, payload):
        # type: (Dict[str, Any]) -> None
        """Start a navigation session from a command payload.

        Rejects the command if a grip session is active (Req 12.6).
        Extracts optional parameters and delegates to the navigation
        controller. The controller handles stopping any active session
        before starting a new one (Req 7.7).
        """
        # Mutual exclusion: reject if grip is active (Req 12.6)
        if self._grip is not None and self._grip.is_active():
            logger.warning(
                "navigate_to_target rejected: grip session is active"
            )
            return

        target_label = payload.get("target_label")
        if not target_label:
            logger.warning(
                "navigate_to_target command missing target_label, ignoring"
            )
            return

        kwargs = {}  # type: Dict[str, Any]

        max_steps = payload.get("max_steps")
        if max_steps is not None:
            kwargs["max_steps"] = int(max_steps)

        speed = payload.get("speed")
        if speed is not None:
            kwargs["speed"] = int(speed)

        confidence_threshold = payload.get("confidence_threshold")
        if confidence_threshold is not None:
            kwargs["confidence_threshold"] = float(confidence_threshold)

        logger.info(
            "Starting navigation: target=%s, params=%s",
            target_label,
            kwargs,
        )
        self._nav.start_navigation(target_label, **kwargs)

    def _handle_start_grip(self, payload):
        # type: (Dict[str, Any]) -> None
        """Start a grip calibration session from a command payload.

        Rejects the command if a navigation session is active (Req 12.6).
        Extracts optional parameters and delegates to the grip controller.
        """
        if self._grip is None:
            logger.warning("start_grip: grip controller not initialized")
            return

        # Mutual exclusion: reject if navigation is active (Req 12.6)
        if self._nav is not None and self._nav.is_active():
            logger.warning(
                "start_grip rejected: navigation session is active"
            )
            return

        kwargs = {}  # type: Dict[str, Any]

        max_iterations = payload.get("max_iterations")
        if max_iterations is not None:
            kwargs["max_iterations"] = int(max_iterations)

        convergence_tolerance = payload.get("convergence_tolerance")
        if convergence_tolerance is not None:
            kwargs["convergence_tolerance"] = int(convergence_tolerance)

        arm_step_limit = payload.get("arm_step_limit")
        if arm_step_limit is not None:
            kwargs["arm_step_limit"] = int(arm_step_limit)

        logger.info("Starting grip session: params=%s", kwargs)
        self._grip.start_grip(**kwargs)

    def _handle_stop_grip(self):
        # type: () -> None
        """Stop the active grip session and show standby screen."""
        if self._grip is None:
            logger.warning("stop_grip: grip controller not initialized")
            return

        logger.info("Stop grip command received")
        self._grip.stop_grip()
        self._show_standby()


    def _handle_take_photo(self, payload):
        # type: (Dict[str, Any]) -> None
        """Capture a photo and upload to S3 via presigned URL."""
        upload_url = payload.get("upload_url", "")
        if not upload_url:
            logger.warning("take_photo: no upload_url in payload")
            return

        cap = self._nav._config.get("camera") if self._nav else None
        if cap is None:
            logger.error("take_photo: no camera available")
            return

        import cv2

        # Show "Cheese!" on LCD
        if self._lcd:
            try:
                self._lcd.show_text("Cheese!", font_size=40)
            except Exception:
                pass

        # Capture frame
        frame = None
        for attempt in range(3):
            ret, frame = cap.read()
            if ret and frame is not None:
                break
            logger.warning("Camera read attempt %d failed", attempt + 1)
            import time
            time.sleep(0.3)

        if frame is None:
            logger.error("take_photo: failed to capture frame")
            if self._lcd:
                try:
                    self._lcd.show_text("Capture failed", font_size=24)
                except Exception:
                    pass
            return

        # Encode as JPEG
        ok, jpeg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            logger.error("take_photo: JPEG encode failed")
            return

        jpeg_bytes = jpeg_buf.tobytes()
        logger.info("Photo captured: %d bytes", len(jpeg_bytes))

        # Upload to S3 via presigned URL
        try:
            from urllib.request import Request, urlopen

            if self._lcd:
                try:
                    self._lcd.show_text("Uploading...", font_size=24)
                except Exception:
                    pass

            req = Request(upload_url, data=jpeg_bytes, method="PUT")
            req.add_header("Content-Type", "image/jpeg")
            req.add_header("Content-Length", str(len(jpeg_bytes)))
            resp = urlopen(req, timeout=30)
            logger.info("S3 upload status: %s", resp.getcode())

            if self._lcd:
                try:
                    self._lcd.show_text("Photo sent!", font_size=24)
                except Exception:
                    pass
        except Exception as e:
            logger.error("take_photo upload error: %s", e)
            if self._lcd:
                try:
                    self._lcd.show_text("Upload err", font_size=24)
                except Exception:
                    pass


    def _handle_arm(self, payload):
        # type: (Dict[str, Any]) -> None
        """Move the robot arm to a position."""
        arm_x = payload.get("arm_x", 0)
        arm_z = payload.get("arm_z", 0)
        logger.info("Arm command: x=%s, z=%s", arm_x, arm_z)
        try:
            self._dog.arm(int(arm_x), int(arm_z))
            if self._lcd:
                try:
                    self._lcd.show_text("Arm: %d,%d" % (int(arm_x), int(arm_z)), font_size=24)
                except Exception:
                    pass
        except Exception as e:
            logger.error("Arm command failed: %s", e)

    def _handle_claw(self, payload):
        # type: (Dict[str, Any]) -> None
        """Open or close the gripper."""
        pos = payload.get("pos", 128)
        logger.info("Claw command: pos=%s", pos)
        try:
            self._dog.claw(int(pos))
            state = "open" if int(pos) > 128 else "closed" if int(pos) < 50 else "partial"
            if self._lcd:
                try:
                    self._lcd.show_text("Claw: %s" % state, font_size=24)
                except Exception:
                    pass
        except Exception as e:
            logger.error("Claw command failed: %s", e)

    def _handle_action(self, payload):
        # type: (Dict[str, Any]) -> None
        """Execute a preset action by ID."""
        action_id = payload.get("action_id", 0)
        logger.info("Action command: id=%s", action_id)
        try:
            self._dog.action(int(action_id))
            if self._lcd:
                try:
                    self._lcd.show_text("Action #%d" % int(action_id), font_size=24)
                except Exception:
                    pass
        except Exception as e:
            logger.error("Action command failed: %s", e)

    def _handle_stop(self):
        # type: () -> None
        """Stop the active navigation session and show standby screen."""
        logger.info("Stop command received")
        self._nav.stop_navigation()
        self._show_standby()

    def _show_standby(self):
        # type: () -> None
        """Display the standby screen on the LCD."""
        if self._lcd is None:
            return

        battery = 0
        try:
            battery = self._dog.read_battery()
        except Exception:
            logger.warning("Failed to read battery for standby screen")

        try:
            self._lcd.show_standby(THING_NAME, battery)
        except Exception:
            logger.warning("Failed to show standby screen")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # type: () -> None
    """Entry point for the Greengrass component.

    1. Parse arguments.
    2. Initialize hardware (XGO dog, camera, LCD).
    3. Initialize inference engine, Bedrock reasoner, LCD display,
       navigation controller.
    4. Set up Greengrass IPC and subscribe to command topic.
    5. Show standby screen.
    6. Block until SIGTERM/SIGINT.
    7. On shutdown: stop navigation, reset dog, clear LCD, release camera.
    """
    # --- Logging ---
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    args = parse_args()
    logger.info("Starting XGO2 Vision Navigation")
    logger.info("Model directory: %s", args.model_dir)

    # --- Hardware ---
    dog = init_dog()
    cap = init_camera()

    # --- Components ---
    from vision_inference import InferenceEngine
    from bedrock_reasoner import BedrockReasoner
    from lcd_display import LCDDisplay
    from nav_controller import NavigationController
    from depth_estimator import DepthEstimator
    from grip_controller import GripCalibrationController
    from grip_reasoner import GripStrategyReasoner
    from coordinate_mapper import CalibrationProfile

    lcd = LCDDisplay()

    inference_engine = InferenceEngine(
        model_dir=args.model_dir,
        confidence_threshold=args.confidence_threshold,
        backend="auto",
    )
    logger.info(
        "Inference engine ready (backend=%s, confidence=%.2f)",
        inference_engine.get_backend_name(),
        args.confidence_threshold,
    )

    bedrock = BedrockReasoner()

    # --- Depth estimator for grip calibration ---
    depth_estimator = None  # type: Optional[Any]
    try:
        depth_estimator = DepthEstimator(
            model_dir=args.model_dir,
            backend="auto",
        )
        logger.info(
            "Depth estimator ready (backend=%s)",
            depth_estimator.get_backend_name(),
        )
    except Exception as exc:
        logger.warning(
            "Depth estimator initialization failed: %s. "
            "Grip calibration will be disabled.",
            exc,
        )

    # --- Grip strategy reasoner ---
    grip_reasoner = None  # type: Optional[Any]
    try:
        grip_reasoner = GripStrategyReasoner(region="us-east-1")
        logger.info("Grip strategy reasoner initialized")
    except Exception as exc:
        logger.warning(
            "Grip strategy reasoner initialization failed: %s. "
            "Grip sessions will use default servoing parameters.",
            exc,
        )

    # --- Greengrass IPC ---
    ipc_client = init_ipc_client()

    # --- Navigation controller ---
    nav_controller = NavigationController(
        dog=dog,
        inference_engine=inference_engine,
        ipc_client=ipc_client,
        lcd_display=lcd,
        bedrock_reasoner=bedrock,
        config={"camera": cap},
    )

    # --- Grip calibration controller ---
    grip_controller = None  # type: Optional[Any]
    if depth_estimator is not None:
        calibration_profile = CalibrationProfile()
        grip_controller = GripCalibrationController(
            dog=dog,
            inference_engine=inference_engine,
            depth_estimator=depth_estimator,
            ipc_client=ipc_client,
            lcd_display=lcd,
            grip_reasoner=grip_reasoner,
            calibration_profile=calibration_profile,
            config={"camera": cap},
        )
        logger.info("Grip calibration controller initialized")
    else:
        logger.warning(
            "Grip calibration controller not initialized "
            "(depth estimator unavailable)"
        )

    # --- Command handler ---
    handler = CommandHandler(
        nav_controller=nav_controller,
        lcd_display=lcd,
        dog=dog,
        grip_controller=grip_controller,
    )

    # --- Subscribe to commands ---
    subscribe_to_commands(ipc_client, handler.handle)
    subscribe_to_grip_commands(ipc_client, handler.handle)

    # --- Standby screen ---
    battery = 0
    try:
        battery = dog.read_battery()
    except Exception:
        logger.warning("Failed to read battery level")

    lcd.show_standby(THING_NAME, battery)
    logger.info("Showing standby screen — waiting for commands")

    # --- Shutdown handling ---
    shutdown_event = threading.Event()

    def _signal_handler(signum, frame):
        # type: (int, Any) -> None
        logger.info("Received signal %d, shutting down", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # --- Block until shutdown — live camera preview when idle ---
    logger.info("Starting live preview mode (inference + LCD when idle)")
    try:
        while not shutdown_event.is_set():
            # Only show live preview when neither navigation nor grip is active
            if nav_controller.is_active():
                shutdown_event.wait(timeout=0.5)
                continue

            if grip_controller is not None and grip_controller.is_active():
                shutdown_event.wait(timeout=0.5)
                continue

            try:
                ret, frame = cap.read()
                if ret and frame is not None:
                    # Run inference on the frame
                    detections = inference_engine.detect(frame)
                    # Show frame with bounding boxes on LCD
                    det_count = len(detections)
                    if det_count > 0:
                        labels = ", ".join(
                            d.class_label if hasattr(d, "class_label") else str(d.get("class_label", ""))
                            for d in detections[:3]
                        )
                        status_text = "Detected: %s" % labels
                    else:
                        status_text = "Live — no objects"
                    lcd.show_frame_with_detections(frame, detections, status=status_text)
                else:
                    shutdown_event.wait(timeout=0.2)
            except Exception:
                # Don't crash the main loop on preview errors
                shutdown_event.wait(timeout=0.5)
    finally:
        logger.info("Shutting down XGO2 Vision Navigation")

        # Stop any active navigation
        try:
            nav_controller.stop_navigation()
        except Exception:
            logger.warning("Error stopping navigation during shutdown")

        # Stop any active grip session
        if grip_controller is not None:
            try:
                grip_controller.stop_grip()
            except Exception:
                logger.warning("Error stopping grip during shutdown")

        # Reset dog to safe posture
        try:
            dog.reset()
            logger.info("Dog reset to standing posture")
        except Exception:
            logger.warning("Failed to reset dog during shutdown")

        # Clear LCD
        try:
            lcd.clear()
            logger.info("LCD cleared")
        except Exception:
            logger.warning("Failed to clear LCD during shutdown")

        # Release camera
        try:
            cap.release()
            logger.info("Camera released")
        except Exception:
            logger.warning("Failed to release camera during shutdown")

        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
