"""
Grip calibration controller for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Implements closed-loop visual servoing for ball grip calibration.
Follows the same session/controller pattern as NavigationSession/NavigationController
in nav_controller.py.

Requirements: 6.1-6.9, 7.1-7.5, 9.1-9.6, 13.1-13.5
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRIP_STATUS_TOPIC = "xgo-robodog/grip/status"
LOW_BATTERY_THRESHOLD = 20
TILT_THRESHOLD = 30.0
BALL_LOST_LIMIT = 10
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_CONVERGENCE_TOLERANCE = 15
DEFAULT_CONVERGENCE_SIZE_TOLERANCE = 0.05
DEFAULT_ARM_STEP_LIMIT = 10
DEFAULT_GRIP_HOLD_FRAMES = 3
DEFAULT_MIN_GRIP_AREA = 0.08
DEFAULT_GAIN = 0.5
CLAW_OPEN = 255
CLAW_CLOSED = 0
ARM_HOME_X = 0
ARM_HOME_Z = 0
CLAW_CLOSE_WAIT = 0.5
FRAME_WIDTH = 320
FRAME_HEIGHT = 240


# ---------------------------------------------------------------------------
# GripSession
# ---------------------------------------------------------------------------

class GripSession:
    """Represents a single closed-loop grip calibration run.

    The session captures frames, detects the ball, estimates depth,
    computes arm target coordinates, applies proportional servoing
    corrections, and checks grip confirmation until a termination
    condition is met.
    """

    def __init__(
        self,
        dog,                    # XGO instance
        inference_engine,       # InferenceEngine (for ball detection)
        depth_estimator,        # DepthEstimator
        ipc_client,             # Greengrass IPC client (or None)
        lcd_display,            # LCDDisplay (or None)
        grip_reasoner,          # GripStrategyReasoner (or None)
        calibration_profile,    # CalibrationProfile
        max_iterations=DEFAULT_MAX_ITERATIONS,
        convergence_tolerance=DEFAULT_CONVERGENCE_TOLERANCE,
        convergence_size_tolerance=DEFAULT_CONVERGENCE_SIZE_TOLERANCE,
        arm_step_limit=DEFAULT_ARM_STEP_LIMIT,
        grip_hold_frames=DEFAULT_GRIP_HOLD_FRAMES,
        min_grip_area=DEFAULT_MIN_GRIP_AREA,
        gain=DEFAULT_GAIN,
        camera=None,
    ):
        # type: (...) -> None
        """Initialize grip session parameters.

        Args:
            dog: XGO robot instance for arm/claw commands.
            inference_engine: InferenceEngine for ball detection.
            depth_estimator: DepthEstimator for monocular depth.
            ipc_client: Greengrass IPC client for MQTT publishing (or None).
            lcd_display: LCDDisplay for visual feedback (or None).
            grip_reasoner: GripStrategyReasoner for Bedrock advice (or None).
            calibration_profile: CalibrationProfile for coordinate mapping.
            max_iterations: Maximum servoing loop iterations before timeout.
            convergence_tolerance: Pixel distance threshold for convergence.
            convergence_size_tolerance: Bbox area fraction tolerance.
            arm_step_limit: Maximum arm step per axis per iteration.
            grip_hold_frames: Consecutive converged frames before grip.
            min_grip_area: Minimum bbox area fraction for grip confirmation.
            gain: Proportional gain for servoing error correction.
            camera: Shared OpenCV VideoCapture instance (or None to open new).
        """
        self._dog = dog
        self._inference_engine = inference_engine
        self._depth_estimator = depth_estimator
        self._ipc_client = ipc_client
        self._lcd_display = lcd_display
        self._grip_reasoner = grip_reasoner
        self._calibration_profile = calibration_profile
        self._max_iterations = max_iterations
        self._convergence_tolerance = convergence_tolerance
        self._convergence_size_tolerance = convergence_size_tolerance
        self._arm_step_limit = arm_step_limit
        self._grip_hold_frames = grip_hold_frames
        self._min_grip_area = min_grip_area
        self._gain = gain
        self._stop_event = threading.Event()
        self._camera = camera
        self._owns_camera = camera is None

        # Current arm position
        self._arm_x = ARM_HOME_X
        self._arm_z = ARM_HOME_Z

    def run(self):
        # type: () -> Dict[str, Any]
        """Execute the closed-loop visual servoing loop. Blocks until termination.

        Returns:
            Dict with termination_reason, steps_completed, grip_result, etc.
        """
        from coordinate_mapper import (
            compute_ball_position,
            ball_position_to_arm_coords,
            compute_servoing_error,
            compute_arm_step,
            clamp_arm_position,
            is_grip_confirmed,
            GripStatus,
        )

        step = 0
        lost_counter = 0
        hold_counter = 0
        termination_reason = "error"
        grip_result = None  # type: Optional[str]

        try:
            # --- Safety: Battery check (Req 13.5) ---
            try:
                battery = self._dog.read_battery()
            except Exception:
                logger.error("Battery read failed, assuming low battery")
                battery = 0

            if battery < LOW_BATTERY_THRESHOLD:
                logger.warning(
                    "Battery too low for grip: %d%% (minimum %d%%)",
                    battery, LOW_BATTERY_THRESHOLD,
                )
                self._publish_final_status(
                    "low_battery", 0, termination_reason="low_battery"
                )
                return {
                    "termination_reason": "low_battery",
                    "steps_completed": 0,
                    "grip_result": None,
                }

            # --- Safety: Open claw at start (Req 6.8) ---
            try:
                self._dog.claw(CLAW_OPEN)
            except Exception:
                logger.error("Failed to open claw at start")

            # --- Open camera if needed ---
            if self._camera is None:
                import cv2  # type: ignore[import-untyped]
                self._camera = cv2.VideoCapture(0)
                if not self._camera.isOpened():
                    logger.error("Failed to open camera")
                    self._publish_final_status(
                        "error", 0, termination_reason="error"
                    )
                    return {
                        "termination_reason": "error",
                        "steps_completed": 0,
                        "grip_result": None,
                    }
            elif not self._camera.isOpened():
                logger.error("Shared camera is not open")
                self._publish_final_status(
                    "error", 0, termination_reason="error"
                )
                return {
                    "termination_reason": "error",
                    "steps_completed": 0,
                    "grip_result": None,
                }

            logger.info(
                "Grip session started: max_iter=%d, tolerance=%d, step_limit=%d",
                self._max_iterations, self._convergence_tolerance,
                self._arm_step_limit,
            )

            # --- Main servoing loop ---
            for step in range(1, self._max_iterations + 1):
                if self._stop_event.is_set():
                    termination_reason = "stopped"
                    break

                # 1. Check IMU (Req 13.3)
                try:
                    roll = self._dog.read_roll()
                    pitch = self._dog.read_pitch()
                except Exception:
                    logger.error("IMU read failed, assuming tilt for safety")
                    roll = 999.0
                    pitch = 999.0

                if abs(roll) > TILT_THRESHOLD or abs(pitch) > TILT_THRESHOLD:
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
                    hold_counter = 0
                    if lost_counter >= BALL_LOST_LIMIT:
                        termination_reason = "ball_lost"
                        break
                    self._publish_iteration_status(
                        step=step,
                        ball_detected=False,
                        ball_position=None,
                        arm_x=self._arm_x,
                        arm_z=self._arm_z,
                        error_magnitude=0.0,
                        convergence_state="lost",
                    )
                    continue

                # 3. Detect ball
                detections = self._inference_engine.detect(frame)
                ball_detections = [
                    d for d in detections
                    if d.class_label == "red_ball"
                ]

                if not ball_detections:
                    lost_counter += 1
                    hold_counter = 0
                    if lost_counter >= BALL_LOST_LIMIT:
                        termination_reason = "ball_lost"
                        break
                    self._publish_iteration_status(
                        step=step,
                        ball_detected=False,
                        ball_position=None,
                        arm_x=self._arm_x,
                        arm_z=self._arm_z,
                        error_magnitude=0.0,
                        convergence_state="seeking",
                    )
                    continue

                # Ball detected — reset lost counter
                lost_counter = 0
                best = max(ball_detections, key=lambda d: d.confidence)
                bbox = best.bounding_box

                # 4. Estimate depth
                try:
                    depth_map = self._depth_estimator.estimate_depth(frame)
                except Exception:
                    logger.error("Depth estimation failed at step %d", step)
                    self._publish_iteration_status(
                        step=step,
                        ball_detected=True,
                        ball_position=None,
                        arm_x=self._arm_x,
                        arm_z=self._arm_z,
                        error_magnitude=0.0,
                        convergence_state="seeking",
                    )
                    continue

                # 5. Compute ball position
                ball_pos = compute_ball_position(
                    bbox=bbox,
                    depth_map=depth_map,
                    frame_width=FRAME_WIDTH,
                    frame_height=FRAME_HEIGHT,
                )

                # 6. Map to arm coordinates
                target_x, target_z = ball_position_to_arm_coords(
                    ball_pos, self._calibration_profile
                )

                # 7. Compute servoing error
                error_x, error_z = compute_servoing_error(
                    self._arm_x, self._arm_z, target_x, target_z
                )
                error_magnitude = math.sqrt(error_x ** 2 + error_z ** 2)

                # 8. Check grip confirmation (Req 7.1)
                # Target position in normalized frame coords: center of frame
                target_x_norm = 0.5
                target_y_norm = 0.5
                confirmed = is_grip_confirmed(
                    bbox=bbox,
                    target_x_norm=target_x_norm,
                    target_y_norm=target_y_norm,
                    pixel_tolerance=self._convergence_tolerance,
                    min_area_fraction=self._min_grip_area,
                    frame_width=FRAME_WIDTH,
                    frame_height=FRAME_HEIGHT,
                )

                if confirmed:
                    hold_counter += 1
                else:
                    hold_counter = 0

                # Determine convergence state
                if hold_counter >= self._grip_hold_frames:
                    convergence_state = "confirmed"
                elif confirmed:
                    convergence_state = "converging"
                else:
                    convergence_state = "seeking"

                # 9. Publish iteration status
                self._publish_iteration_status(
                    step=step,
                    ball_detected=True,
                    ball_position=ball_pos,
                    arm_x=self._arm_x,
                    arm_z=self._arm_z,
                    error_magnitude=error_magnitude,
                    convergence_state=convergence_state,
                )

                # 10. If confirmed for enough frames, attempt grip
                if hold_counter >= self._grip_hold_frames:
                    grip_result = self._attempt_grip(frame)
                    termination_reason = "grip_success" if grip_result == "grip_success" else "grip_uncertain"
                    break

                # 11. Apply arm step (Req 6.4)
                delta_x, delta_z = compute_arm_step(
                    error_x, error_z, self._gain, self._arm_step_limit
                )
                new_x = self._arm_x + delta_x
                new_z = self._arm_z + delta_z

                # Clamp to workspace bounds (Req 13.1)
                new_x, new_z = clamp_arm_position(new_x, new_z)

                # Execute arm command
                try:
                    self._dog.arm(new_x, new_z)
                    self._arm_x = new_x
                    self._arm_z = new_z
                except Exception:
                    logger.error("Arm command failed at step %d", step)

                # Update LCD
                if self._lcd_display is not None:
                    try:
                        self._lcd_display.show_frame_with_detections(
                            frame, detections,
                            status="Grip: err=%.1f %s" % (
                                error_magnitude, convergence_state
                            ),
                        )
                    except Exception:
                        logger.warning("LCD update failed")

            else:
                # Loop completed without break — timeout (Req 6.6)
                termination_reason = "timeout"

        except Exception:
            logger.exception("Grip servoing loop error")
            termination_reason = "error"
        finally:
            # Safety: always open claw and return arm home (Req 6.7, 13.4)
            try:
                self._dog.claw(CLAW_OPEN)
            except Exception:
                logger.error("Failed to open claw in finally block")

            try:
                self._dog.arm(ARM_HOME_X, ARM_HOME_Z)
            except Exception:
                logger.error("Failed to home arm in finally block")

            # Release camera only if we opened it
            if self._owns_camera and self._camera is not None:
                try:
                    self._camera.release()
                except Exception:
                    pass

        self._publish_final_status(
            termination_reason, step,
            termination_reason=termination_reason,
            grip_result=grip_result,
        )

        logger.info(
            "Grip session ended: reason=%s, steps=%d, grip_result=%s",
            termination_reason, step, grip_result,
        )

        return {
            "termination_reason": termination_reason,
            "steps_completed": step,
            "grip_result": grip_result,
        }

    def stop(self):
        # type: () -> None
        """Signal the servoing loop to terminate."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _attempt_grip(self, pre_grip_frame):
        # type: (Any) -> str
        """Close the claw and check if the ball was gripped.

        Args:
            pre_grip_frame: The last frame before grip attempt.

        Returns:
            "grip_success" if ball detected post-grip, "grip_uncertain" otherwise.
        """
        # Close claw (Req 7.2)
        try:
            self._dog.claw(CLAW_CLOSED)
        except Exception:
            logger.error("Failed to close claw during grip attempt")
            return "grip_uncertain"

        # Wait for claw to close mechanically
        time.sleep(CLAW_CLOSE_WAIT)

        # Capture post-grip frame (Req 7.3)
        if self._camera is not None:
            try:
                ret, post_frame = self._camera.read()
                if ret and post_frame is not None:
                    detections = self._inference_engine.detect(post_frame)
                    ball_detections = [
                        d for d in detections
                        if d.class_label == "red_ball"
                    ]
                    if ball_detections:
                        # Ball still visible in gripper region (Req 7.4)
                        logger.info("Post-grip check: ball detected — grip_success")
                        return "grip_success"
                    else:
                        # Ball not visible (Req 7.5)
                        logger.info("Post-grip check: ball not detected — grip_uncertain")
                        return "grip_uncertain"
            except Exception:
                logger.error("Post-grip frame capture/detection failed")

        return "grip_uncertain"

    def _publish_iteration_status(
        self,
        step,               # type: int
        ball_detected,      # type: bool
        ball_position,      # type: Any
        arm_x,              # type: int
        arm_z,              # type: int
        error_magnitude,    # type: float
        convergence_state,  # type: str
    ):
        # type: (...) -> None
        """Publish a per-iteration GripStatus message via IPC MQTT."""
        from coordinate_mapper import GripStatus

        status = GripStatus(
            step=step,
            ball_detected=ball_detected,
            ball_position=ball_position,
            arm_x=arm_x,
            arm_z=arm_z,
            error_magnitude=error_magnitude,
            convergence_state=convergence_state,
            termination_reason=None,
            timestamp=_iso_timestamp(),
        )
        self._publish_status(status.to_dict())

    def _publish_final_status(
        self,
        reason,     # type: str
        steps,      # type: int
        termination_reason=None,  # type: Optional[str]
        grip_result=None,         # type: Optional[str]
    ):
        # type: (...) -> None
        """Publish a final termination status message via IPC MQTT (retained)."""
        payload = {
            "type": "grip_status",
            "status": "completed",
            "termination_reason": termination_reason or reason,
            "steps_completed": steps,
            "grip_result": grip_result,
            "timestamp": _iso_timestamp(),
        }
        self._publish_status(payload, retain=True)

    def _publish_status(self, payload, retain=False):
        # type: (Dict[str, Any], bool) -> None
        """Publish a JSON payload to the grip status MQTT topic."""
        if self._ipc_client is None:
            return
        try:
            message = json.dumps(payload)
            kwargs = {
                "topic_name": GRIP_STATUS_TOPIC,
                "qos": "1",
                "payload": message.encode("utf-8"),
            }  # type: Dict[str, Any]
            if retain:
                kwargs["retain"] = True
            self._ipc_client.publish_to_iot_core(**kwargs)
        except Exception:
            logger.warning("Failed to publish grip status to %s", GRIP_STATUS_TOPIC)


# ---------------------------------------------------------------------------
# GripCalibrationController
# ---------------------------------------------------------------------------

class GripCalibrationController:
    """Manages grip sessions in a background thread.

    Provides start/stop/is_active/get_last_result interface for the
    IPC command handler. Follows the same pattern as NavigationController.
    """

    def __init__(
        self,
        dog,                    # XGO instance
        inference_engine,       # InferenceEngine
        depth_estimator,        # DepthEstimator
        ipc_client,             # Greengrass IPC client (or None)
        lcd_display,            # LCDDisplay (or None)
        grip_reasoner,          # GripStrategyReasoner (or None)
        calibration_profile,    # CalibrationProfile
        config=None,            # type: Optional[Dict[str, Any]]
    ):
        # type: (...) -> None
        """Initialize with hardware references and config.

        Args:
            dog: XGO robot instance.
            inference_engine: InferenceEngine for ball detection.
            depth_estimator: DepthEstimator for depth inference.
            ipc_client: Greengrass IPC client for MQTT.
            lcd_display: LCDDisplay for visual feedback.
            grip_reasoner: GripStrategyReasoner for Bedrock advice.
            calibration_profile: CalibrationProfile for coordinate mapping.
            config: Optional dict with default grip parameters.
        """
        self._dog = dog
        self._inference_engine = inference_engine
        self._depth_estimator = depth_estimator
        self._ipc_client = ipc_client
        self._lcd_display = lcd_display
        self._grip_reasoner = grip_reasoner
        self._calibration_profile = calibration_profile
        self._config = config if config is not None else {}
        self._session = None  # type: Optional[GripSession]
        self._thread = None  # type: Optional[threading.Thread]
        self._lock = threading.Lock()
        self._last_result = None  # type: Optional[Dict[str, Any]]

    def start_grip(self, **kwargs):
        # type: (**Any) -> Dict[str, Any]
        """Start a new grip session in a background thread.

        If a session is already active, stops it first.

        Args:
            **kwargs: Optional overrides for max_iterations,
                convergence_tolerance, arm_step_limit, grip_hold_frames,
                min_grip_area, gain.

        Returns:
            Dict with status='started'.
        """
        with self._lock:
            # Stop any active session first
            if self._session is not None:
                logger.info("Stopping active grip session before starting new one")
                self._session.stop()
                if self._thread is not None and self._thread.is_alive():
                    self._thread.join(timeout=5.0)

            # Build session parameters from config + kwargs
            params = dict(self._config)
            params.update(kwargs)

            # Extract camera from config — shared with main.py
            camera = self._config.get("camera")

            session = GripSession(
                dog=self._dog,
                inference_engine=self._inference_engine,
                depth_estimator=self._depth_estimator,
                ipc_client=self._ipc_client,
                lcd_display=self._lcd_display,
                grip_reasoner=self._grip_reasoner,
                calibration_profile=self._calibration_profile,
                max_iterations=params.get("max_iterations", DEFAULT_MAX_ITERATIONS),
                convergence_tolerance=params.get(
                    "convergence_tolerance", DEFAULT_CONVERGENCE_TOLERANCE
                ),
                convergence_size_tolerance=params.get(
                    "convergence_size_tolerance", DEFAULT_CONVERGENCE_SIZE_TOLERANCE
                ),
                arm_step_limit=params.get("arm_step_limit", DEFAULT_ARM_STEP_LIMIT),
                grip_hold_frames=params.get(
                    "grip_hold_frames", DEFAULT_GRIP_HOLD_FRAMES
                ),
                min_grip_area=params.get("min_grip_area", DEFAULT_MIN_GRIP_AREA),
                gain=params.get("gain", DEFAULT_GAIN),
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

        logger.info("Grip session started in background thread")
        return {"status": "started"}

    def stop_grip(self):
        # type: () -> Dict[str, Any]
        """Stop the active grip session.

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

        logger.info("Grip session stopped")
        return {"status": "stopped"}

    def is_active(self):
        # type: () -> bool
        """Return True if a grip session is currently running."""
        with self._lock:
            return (
                self._session is not None
                and self._thread is not None
                and self._thread.is_alive()
            )

    def get_last_result(self):
        # type: () -> Optional[Dict[str, Any]]
        """Return the result of the last completed grip session."""
        with self._lock:
            return self._last_result

    def _run_session(self, session):
        # type: (GripSession) -> None
        """Run a grip session and store the result."""
        try:
            result = session.run()
            with self._lock:
                self._last_result = result
                if self._session is session:
                    self._session = None
        except Exception:
            logger.exception("Grip session thread error")
            with self._lock:
                self._last_result = {
                    "termination_reason": "error",
                    "steps_completed": 0,
                    "grip_result": None,
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
