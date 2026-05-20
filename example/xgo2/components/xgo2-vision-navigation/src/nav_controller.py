"""
Navigation controller for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Implements closed-loop vision-guided navigation using quadruped gaits.

Requirements: 5.1-5.9, 11.1-11.6
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SPEED = 25
MAX_DURATION = 1.0
BEARING_DEADZONE = 0.15
TILT_THRESHOLD = 45.0
LOW_BATTERY_THRESHOLD = 20
TURN_DEGREES = 15
SCAN_TURN_DEGREES = 30
STATUS_TOPIC = "xgo-robodog/vision/status"


# ---------------------------------------------------------------------------
# Pure helper functions (testable independently)
# ---------------------------------------------------------------------------

def compute_bearing(bbox):
    # type: (Dict[str, float]) -> float
    """Compute horizontal bearing of a bounding box relative to frame center.

    Args:
        bbox: Dict with keys "left" and "right" as floats in [0.0, 1.0].

    Returns:
        Float bearing where negative means target is left of center,
        positive means right of center. Range roughly [-0.5, 0.5].
    """
    bbox_center_x = (bbox["left"] + bbox["right"]) / 2.0
    return bbox_center_x - 0.5


def compute_steering_action(bearing):
    # type: (float) -> str
    """Determine steering action from a bearing value.

    Args:
        bearing: Horizontal bearing, negative = left, positive = right.

    Returns:
        One of "turn_left", "turn_right", or "forward".
    """
    if bearing < -BEARING_DEADZONE:
        return "turn_left"
    elif bearing > BEARING_DEADZONE:
        return "turn_right"
    else:
        return "forward"


def is_target_reached(bbox, fraction):
    # type: (Dict[str, float], float) -> bool
    """Check if a bounding box area exceeds the target-reached fraction.

    Args:
        bbox: Dict with keys "top", "bottom", "left", "right" in [0.0, 1.0].
        fraction: Area threshold for considering the target reached.

    Returns:
        True if bbox area > fraction.
    """
    area = (bbox["bottom"] - bbox["top"]) * (bbox["right"] - bbox["left"])
    return area > fraction


def is_tilt_detected(roll, pitch):
    # type: (float, float) -> bool
    """Check if IMU roll or pitch exceeds the tilt safety threshold.

    Args:
        roll: IMU roll angle in degrees.
        pitch: IMU pitch angle in degrees.

    Returns:
        True if |roll| > 30 or |pitch| > 30.
    """
    return abs(roll) > TILT_THRESHOLD or abs(pitch) > TILT_THRESHOLD


def clamp_speed(speed):
    # type: (int) -> int
    """Clamp forward speed to the safety maximum of 25.

    Args:
        speed: Requested speed value.

    Returns:
        min(speed, 25).
    """
    return min(speed, MAX_SPEED)


def clamp_duration(duration):
    # type: (float) -> float
    """Clamp movement duration to the safety maximum of 1.0 second.

    Args:
        duration: Requested duration in seconds.

    Returns:
        min(duration, 1.0).
    """
    return min(duration, MAX_DURATION)


# ---------------------------------------------------------------------------
# NavigationSession
# ---------------------------------------------------------------------------

class NavigationSession:
    """Represents a single closed-loop navigation run.

    The session captures frames, runs inference, computes steering,
    executes gait commands, and publishes status until a termination
    condition is met.
    """

    def __init__(
        self,
        dog,            # XGO instance
        inference_engine,  # InferenceEngine
        ipc_client,     # Greengrass IPC client (or None)
        lcd_display,    # LCDDisplay (or None)
        bedrock_reasoner,  # BedrockReasoner (or None)
        target_label,   # type: str
        max_steps=100,  # type: int
        speed=15,       # type: int
        confidence_threshold=0.5,   # type: float
        target_reached_fraction=0.25,  # type: float
        lost_target_limit=10,  # type: int
        bedrock_trigger_threshold=0.7,  # type: float
        camera=None,    # type: Optional[Any]
    ):
        # type: (...) -> None
        """Initialize navigation session parameters.

        Args:
            dog: XGO robot instance for gait commands.
            inference_engine: InferenceEngine for object detection.
            ipc_client: Greengrass IPC client for MQTT publishing (or None).
            lcd_display: LCDDisplay for visual feedback (or None).
            bedrock_reasoner: BedrockReasoner for scene analysis (or None).
            target_label: Object class label to navigate toward.
            max_steps: Maximum navigation loop iterations before timeout.
            speed: Forward walk speed (will be clamped to max 25).
            confidence_threshold: Minimum detection confidence to consider.
            target_reached_fraction: Bbox area fraction to declare target reached.
            lost_target_limit: Consecutive no-detection frames before target lost.
            bedrock_trigger_threshold: Confidence above which to trigger Bedrock.
            camera: Shared OpenCV VideoCapture instance (or None to open new).
        """
        self._dog = dog
        self._inference_engine = inference_engine
        self._ipc_client = ipc_client
        self._lcd_display = lcd_display
        self._bedrock_reasoner = bedrock_reasoner
        self._target_label = target_label
        self._max_steps = max_steps
        self._speed = clamp_speed(speed)
        self._confidence_threshold = confidence_threshold
        self._target_reached_fraction = target_reached_fraction
        self._lost_target_limit = lost_target_limit
        self._bedrock_trigger_threshold = bedrock_trigger_threshold
        self._stop_event = threading.Event()
        self._camera = camera  # type: Optional[Any]
        self._owns_camera = camera is None  # True if we need to open/close it

    def run(self):
        # type: () -> Dict[str, Any]
        """Execute the closed-loop navigation loop. Blocks until termination.

        Returns:
            Dict with termination_reason, steps_completed, target_label, etc.
        """
        import cv2  # type: ignore[import-untyped]

        step = 0
        lost_counter = 0
        termination_reason = "error"

        try:
            # --- Battery check (Req 11.6) ---
            try:
                battery = self._dog.read_battery()
            except Exception:
                logger.error("Battery read failed, assuming low battery")
                battery = 0

            if battery < LOW_BATTERY_THRESHOLD:
                logger.warning(
                    "Battery too low to navigate: %d%% (minimum %d%%)",
                    battery, LOW_BATTERY_THRESHOLD,
                )
                self._publish_final_status("low_battery", 0)
                return {
                    "termination_reason": "low_battery",
                    "steps_completed": 0,
                    "target_label": self._target_label,
                }

            # --- Open camera (only if not shared) ---
            if self._camera is None:
                self._camera = cv2.VideoCapture(0)
                if not self._camera.isOpened():
                    logger.error("Failed to open camera")
                    self._publish_final_status("error", 0)
                    return {
                        "termination_reason": "error",
                        "steps_completed": 0,
                        "target_label": self._target_label,
                    }
            elif not self._camera.isOpened():
                logger.error("Shared camera is not open")
                self._publish_final_status("error", 0)
                return {
                    "termination_reason": "error",
                    "steps_completed": 0,
                    "target_label": self._target_label,
                }

            logger.info(
                "Navigation session started: target=%s, max_steps=%d, speed=%d",
                self._target_label, self._max_steps, self._speed,
            )

            # --- Main navigation loop ---
            for step in range(1, self._max_steps + 1):
                if self._stop_event.is_set():
                    termination_reason = "stopped"
                    break

                # 1. Check IMU (Req 11.1, 11.2)
                try:
                    roll = self._dog.read_roll()
                    pitch = self._dog.read_pitch()
                except Exception:
                    logger.error("IMU read failed, assuming tilt for safety")
                    roll = 999.0
                    pitch = 999.0

                if is_tilt_detected(roll, pitch):
                    logger.warning(
                        "Tilt detected: roll=%.1f, pitch=%.1f", roll, pitch
                    )
                    termination_reason = "tilt_detected"
                    break

                # 2. Capture frame
                ret, frame = self._camera.read()
                if not ret or frame is None:
                    logger.warning("Camera capture failed at step %d", step)
                    lost_counter += 1
                    if lost_counter > self._lost_target_limit:
                        termination_reason = "target_lost"
                        break
                    self._publish_iteration_status(
                        step, False, None, 0.0, 0.0, "no_frame",
                        self._inference_engine.get_backend_name(),
                        roll, pitch,
                    )
                    continue

                # 3. Run inference — filter for target label
                detections = self._inference_engine.detect(frame)
                target_detections = [
                    d for d in detections
                    if d.class_label == self._target_label
                    and d.confidence >= self._confidence_threshold
                ]

                # 4. Update LCD
                if self._lcd_display is not None:
                    try:
                        status_text = "Searching"
                        if target_detections:
                            status_text = "Tracking {}".format(
                                self._target_label
                            )
                        self._lcd_display.show_frame_with_detections(
                            frame, detections, status=status_text
                        )
                    except Exception:
                        logger.warning("LCD update failed")

                # 5. Process detections
                if target_detections:
                    lost_counter = 0
                    best = max(target_detections, key=lambda d: d.confidence)
                    bbox = best.bounding_box
                    bearing = compute_bearing(bbox)
                    action = compute_steering_action(bearing)
                    area = (
                        (bbox["bottom"] - bbox["top"])
                        * (bbox["right"] - bbox["left"])
                    )

                    # 5e. Target reached check (Req 5.5)
                    if is_target_reached(bbox, self._target_reached_fraction):
                        logger.info(
                            "Target reached at step %d (area=%.3f)", step, area
                        )
                        termination_reason = "target_reached"
                        if self._lcd_display is not None:
                            try:
                                self._lcd_display.show_frame_with_detections(
                                    frame, detections, status="Reached!"
                                )
                            except Exception:
                                pass
                        self._publish_iteration_status(
                            step, True, bearing, area, best.confidence,
                            "target_reached",
                            self._inference_engine.get_backend_name(),
                            roll, pitch,
                        )
                        break

                    # 5b-d. Execute steering (Req 5.3, 5.4)
                    self._execute_steering(action)

                    # 5f. Bedrock trigger (Req 6.1)
                    if (
                        best.confidence > self._bedrock_trigger_threshold
                        and self._bedrock_reasoner is not None
                    ):
                        try:
                            response = self._bedrock_reasoner.analyze_scene(
                                frame, detections
                            )
                            if response and self._lcd_display is not None:
                                try:
                                    self._lcd_display.show_bedrock_response(
                                        response
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            logger.warning("Bedrock analysis failed")

                    self._publish_iteration_status(
                        step, True, bearing, area, best.confidence, action,
                        self._inference_engine.get_backend_name(),
                        roll, pitch,
                    )
                else:
                    # 6. Target not detected
                    lost_counter += 1
                    if lost_counter > self._lost_target_limit:
                        # Scan by rotating in place
                        logger.info(
                            "Target lost after %d frames, scanning...",
                            self._lost_target_limit,
                        )
                        found = self._scan_for_target(frame)
                        if not found:
                            termination_reason = "target_lost"
                            if self._lcd_display is not None:
                                try:
                                    self._lcd_display.show_frame_with_detections(
                                        frame, [], status="Lost"
                                    )
                                except Exception:
                                    pass
                            break
                        else:
                            lost_counter = 0

                    self._publish_iteration_status(
                        step, False, None, 0.0, 0.0, "searching",
                        self._inference_engine.get_backend_name(),
                        roll, pitch,
                    )
            else:
                # Loop completed without break — timeout (Req 5.7)
                termination_reason = "timeout"

        except Exception:
            logger.exception("Navigation loop error")
            termination_reason = "error"
        finally:
            # Always reset robot to safe posture (Req 11.5)
            try:
                self._dog.reset()
            except Exception:
                logger.error("dog.reset() failed in finally block")

            # Release camera only if we opened it
            if self._owns_camera and self._camera is not None:
                try:
                    self._camera.release()
                except Exception:
                    pass

        self._publish_final_status(termination_reason, step)

        logger.info(
            "Navigation session ended: reason=%s, steps=%d",
            termination_reason, step,
        )

        return {
            "termination_reason": termination_reason,
            "steps_completed": step,
            "target_label": self._target_label,
        }

    def stop(self):
        # type: () -> None
        """Signal the navigation loop to terminate."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_steering(self, action):
        # type: (str) -> None
        """Execute a steering gait command on the robot.

        Args:
            action: One of "turn_left", "turn_right", or "forward".
        """
        try:
            if action == "turn_left":
                self._dog.turn(-TURN_DEGREES)
            elif action == "turn_right":
                self._dog.turn(TURN_DEGREES)
            else:
                self._dog.move("x", self._speed)
            # Brief pause to let the gait execute (clamped to max duration)
            time.sleep(clamp_duration(0.5))
        except Exception:
            logger.error("Steering command failed: %s", action)

    def _scan_for_target(self, last_frame):
        # type: (Any) -> bool
        """Rotate in place to scan for the target.

        Performs a series of small turns, checking for the target after each.

        Returns:
            True if target found during scan, False otherwise.
        """
        import cv2  # type: ignore[import-untyped]

        scan_steps = 12  # ~360 degrees at 30 degrees per step
        for _ in range(scan_steps):
            if self._stop_event.is_set():
                return False
            try:
                self._dog.turn(SCAN_TURN_DEGREES)
                time.sleep(clamp_duration(0.5))
            except Exception:
                logger.error("Scan turn failed")
                return False

            if self._camera is not None:
                ret, frame = self._camera.read()
                if ret and frame is not None:
                    detections = self._inference_engine.detect(frame)
                    target_detections = [
                        d for d in detections
                        if d.class_label == self._target_label
                        and d.confidence >= self._confidence_threshold
                    ]
                    if target_detections:
                        logger.info("Target re-acquired during scan")
                        return True
        return False

    def _publish_iteration_status(
        self,
        step,       # type: int
        detected,   # type: bool
        bearing,    # type: Optional[float]
        area,       # type: float
        confidence, # type: float
        action,     # type: str
        backend,    # type: str
        roll,       # type: float
        pitch,      # type: float
    ):
        # type: (...) -> None
        """Publish a per-iteration status message via IPC MQTT."""
        payload = {
            "type": "navigation_status",
            "status": "running",
            "step": step,
            "target_detected": detected,
            "target_label": self._target_label,
            "target_bearing": bearing if bearing is not None else 0.0,
            "target_area": area,
            "action": action,
            "backend": backend,
            "imu": {"roll": roll, "pitch": pitch},
            "timestamp": _iso_timestamp(),
        }
        self._publish_status(payload)

    def _publish_final_status(self, reason, steps):
        # type: (str, int) -> None
        """Publish a final termination status message via IPC MQTT (retained)."""
        payload = {
            "type": "navigation_status",
            "status": "completed",
            "termination_reason": reason,
            "steps_completed": steps,
            "target_label": self._target_label,
            "backend": self._inference_engine.get_backend_name(),
            "timestamp": _iso_timestamp(),
        }
        self._publish_status(payload, retain=True)

    def _publish_status(self, payload, retain=False):
        # type: (Dict[str, Any], bool) -> None
        """Publish a JSON payload to the status MQTT topic."""
        if self._ipc_client is None:
            return
        try:
            message = json.dumps(payload)
            kwargs = {
                "topic_name": STATUS_TOPIC,
                "qos": "1",
                "payload": message.encode("utf-8"),
            }
            if retain:
                kwargs["retain"] = True
            self._ipc_client.publish_to_iot_core(**kwargs)
        except Exception:
            logger.warning("Failed to publish status to %s", STATUS_TOPIC)


# ---------------------------------------------------------------------------
# NavigationController
# ---------------------------------------------------------------------------

class NavigationController:
    """Manages navigation sessions in a background thread.

    Provides start/stop/is_active interface for the IPC command handler.
    """

    def __init__(
        self,
        dog,                # XGO instance
        inference_engine,   # InferenceEngine
        ipc_client,         # Greengrass IPC client (or None)
        lcd_display,        # LCDDisplay (or None)
        bedrock_reasoner,   # BedrockReasoner (or None)
        config=None,        # type: Optional[Dict[str, Any]]
    ):
        # type: (...) -> None
        """Initialize with hardware references and config.

        Args:
            dog: XGO robot instance.
            inference_engine: InferenceEngine for detection.
            ipc_client: Greengrass IPC client for MQTT.
            lcd_display: LCDDisplay for visual feedback.
            bedrock_reasoner: BedrockReasoner for scene analysis.
            config: Optional dict with default navigation parameters.
        """
        self._dog = dog
        self._inference_engine = inference_engine
        self._ipc_client = ipc_client
        self._lcd_display = lcd_display
        self._bedrock_reasoner = bedrock_reasoner
        self._config = config if config is not None else {}
        self._session = None  # type: Optional[NavigationSession]
        self._thread = None  # type: Optional[threading.Thread]
        self._lock = threading.Lock()
        self._last_result = None  # type: Optional[Dict[str, Any]]

    def start_navigation(self, target_label, **kwargs):
        # type: (str, **Any) -> Dict[str, Any]
        """Start a new navigation session in a background thread.

        If a session is already active, stops it first (Req 7.7).

        Args:
            target_label: Object class label to navigate toward.
            **kwargs: Optional overrides for max_steps, speed,
                confidence_threshold, target_reached_fraction,
                lost_target_limit, bedrock_trigger_threshold.

        Returns:
            Dict with status='started'.
        """
        with self._lock:
            # Stop any active session first
            if self._session is not None:
                logger.info("Stopping active session before starting new one")
                self._session.stop()
                if self._thread is not None and self._thread.is_alive():
                    self._thread.join(timeout=5.0)

            # Build session parameters from config + kwargs
            params = dict(self._config)
            params.update(kwargs)

            # Extract camera from config — shared with main.py
            camera = self._config.get("camera")

            session = NavigationSession(
                dog=self._dog,
                inference_engine=self._inference_engine,
                ipc_client=self._ipc_client,
                lcd_display=self._lcd_display,
                bedrock_reasoner=self._bedrock_reasoner,
                target_label=target_label,
                max_steps=params.get("max_steps", 100),
                speed=params.get("speed", 15),
                confidence_threshold=params.get("confidence_threshold", 0.5),
                target_reached_fraction=params.get(
                    "target_reached_fraction", 0.25
                ),
                lost_target_limit=params.get("lost_target_limit", 10),
                bedrock_trigger_threshold=params.get(
                    "bedrock_trigger_threshold", 0.7
                ),
                camera=camera,
            )
            self._session = session

            thread = threading.Thread(
                target=self._run_session,
                args=(session,),
                daemon=True,
            )
            thread.start()
            self._thread = thread

        logger.info("Navigation started: target=%s", target_label)
        return {"status": "started", "target_label": target_label}

    def stop_navigation(self):
        # type: () -> Dict[str, Any]
        """Stop the active navigation session.

        Returns:
            Dict with status='stopped' or status='no_active_session'.
        """
        with self._lock:
            if self._session is None:
                return {"status": "no_active_session"}

            self._session.stop()
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=5.0)

            self._session = None
            self._thread = None

        logger.info("Navigation stopped")
        return {"status": "stopped"}

    def is_active(self):
        # type: () -> bool
        """Return True if a navigation session is currently running."""
        with self._lock:
            return (
                self._session is not None
                and self._thread is not None
                and self._thread.is_alive()
            )

    def get_last_result(self):
        # type: () -> Optional[Dict[str, Any]]
        """Return the result of the last completed navigation session."""
        with self._lock:
            return self._last_result

    def _run_session(self, session):
        # type: (NavigationSession) -> None
        """Run a navigation session and store the result."""
        try:
            result = session.run()
            with self._lock:
                self._last_result = result
                # Clear session reference if it is still the current one
                if self._session is session:
                    self._session = None
        except Exception:
            logger.exception("Navigation session thread error")
            with self._lock:
                self._last_result = {
                    "termination_reason": "error",
                    "steps_completed": 0,
                    "target_label": session._target_label,
                }
                if self._session is session:
                    self._session = None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _iso_timestamp():
    # type: () -> str
    """Return the current UTC time as an ISO 8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
