"""
Device-side navigation controller for the Zumi robot.

Implements closed-loop vision-guided navigation: capture frame, detect
target, read IR sensors, compute drive action, execute. Integrates with
the existing zumi_iot.py MQTT command handler.

Python 3.5.3 compatible — no f-strings, no dataclasses, no type hints.
"""

import json
import logging
import time
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure helper functions — testable without hardware
# ---------------------------------------------------------------------------

MAX_SPEED = 40
MAX_DURATION = 0.5
BEARING_DEAD_ZONE = 0.15


def compute_bearing(bounding_box):
    """Compute target bearing from bounding box center relative to frame center.

    Args:
        bounding_box: dict with 'left' and 'right' keys (floats 0.0-1.0).

    Returns:
        float: bearing value. Negative = target is left, positive = right.
    """
    center_x = (bounding_box["left"] + bounding_box["right"]) / 2.0
    return center_x - 0.5


def compute_steering_action(bearing):
    """Determine steering action from bearing value.

    Args:
        bearing: float from compute_bearing().

    Returns:
        str: 'turn_left', 'turn_right', or 'forward'.
    """
    if bearing < -BEARING_DEAD_ZONE:
        return "turn_left"
    elif bearing > BEARING_DEAD_ZONE:
        return "turn_right"
    else:
        return "forward"


def check_obstacle(ir_data, threshold):
    """Check if front IR sensors detect an obstacle.

    Args:
        ir_data: list of 6 IR values [FR, BR, BackR, BL, BackL, FL].
        threshold: int, readings below this indicate an obstacle.

    Returns:
        bool: True if obstacle detected.
    """
    front_right = ir_data[0]
    front_left = ir_data[5]
    return front_right < threshold or front_left < threshold


def check_dropoff(ir_data, threshold):
    """Check if bottom IR sensors detect a drop-off.

    Args:
        ir_data: list of 6 IR values [FR, BR, BackR, BL, BackL, FL].
        threshold: int, readings above this indicate a drop-off.

    Returns:
        bool: True if drop-off detected.
    """
    bottom_right = ir_data[1]
    bottom_left = ir_data[3]
    return bottom_right > threshold or bottom_left > threshold


def check_target_reached(bounding_box, fraction):
    """Check if target bounding box area exceeds the reached fraction.

    Args:
        bounding_box: dict with 'top', 'bottom', 'left', 'right' keys.
        fraction: float in (0.0, 1.0].

    Returns:
        bool: True if target is close enough to be considered reached.
    """
    height = bounding_box["bottom"] - bounding_box["top"]
    width = bounding_box["right"] - bounding_box["left"]
    area = height * width
    return area > fraction


def clamp_speed(speed):
    """Clamp speed to maximum allowed value.

    Args:
        speed: int or float, requested speed.

    Returns:
        int or float: clamped speed (max 40).
    """
    if speed > MAX_SPEED:
        return MAX_SPEED
    return speed


def clamp_duration(duration):
    """Clamp duration to maximum allowed value.

    Args:
        duration: float, requested duration in seconds.

    Returns:
        float: clamped duration (max 0.5s).
    """
    if duration > MAX_DURATION:
        return MAX_DURATION
    return duration


# ---------------------------------------------------------------------------
# NavigationSession — single navigation run
# ---------------------------------------------------------------------------

class NavigationSession(object):
    """Represents a single closed-loop navigation run.

    Captures frames, runs inference, reads IR sensors, computes drive
    actions, and executes them in a loop until termination.
    """

    # Scan rotation parameters
    SCAN_TURN_ANGLE = 30       # degrees per scan step
    SCAN_STEPS_FULL = 12       # 360 / 30 = 12 steps for full rotation

    def __init__(self, zumi, screen, inference_engine, mqtt_connection,
                 thing_name, target_label, max_steps=50, speed=30,
                 obstacle_threshold=100, confidence_threshold=0.5,
                 target_reached_fraction=0.25, lost_target_limit=5,
                 dropoff_threshold=200):
        self._zumi = zumi
        self._screen = screen
        self._inference_engine = inference_engine
        self._mqtt_connection = mqtt_connection
        self._thing_name = thing_name
        self._target_label = target_label
        self._max_steps = max_steps
        self._speed = clamp_speed(speed)
        self._obstacle_threshold = obstacle_threshold
        self._confidence_threshold = confidence_threshold
        self._target_reached_fraction = target_reached_fraction
        self._lost_target_limit = lost_target_limit
        self._dropoff_threshold = dropoff_threshold

        self._stop_event = threading.Event()
        self._step = 0
        self._lost_counter = 0
        self._camera = None
        self._telemetry_topic = "zumi/%s/telemetry" % thing_name

    def run(self):
        """Execute the navigation loop. Blocks until termination.

        Returns:
            dict with termination_reason, steps_completed, target_label,
            and backend.
        """
        termination_reason = "error"
        try:
            self._camera = self._init_camera()
            self._screen.draw_text_center("Nav: %s" % self._target_label)

            while not self._stop_event.is_set():
                # Check step limit
                if self._step >= self._max_steps:
                    termination_reason = "timeout"
                    logger.info("Navigation timeout after %d steps", self._step)
                    break

                self._step += 1

                # 1. Capture frame
                frame = self._capture_frame()

                # 2. Run inference — filter for target_label
                target_detection = None
                if frame is not None:
                    try:
                        detections = self._inference_engine.detect(frame)
                        for det in detections:
                            if (det.class_label == self._target_label
                                    and det.confidence >= self._confidence_threshold):
                                if (target_detection is None
                                        or det.confidence > target_detection.confidence):
                                    target_detection = det
                    except Exception as e:
                        logger.error("Inference error: %s", e)

                # 3. Read IR sensors
                ir_data = self._read_ir_sensors()

                # 4. Safety checks
                obstacle_detected = check_obstacle(ir_data, self._obstacle_threshold)
                dropoff_detected = check_dropoff(ir_data, self._dropoff_threshold)

                # 5. Compute and execute action
                target_detected = target_detection is not None
                bearing = 0.0
                target_area = 0.0
                action = "none"

                if obstacle_detected or dropoff_detected:
                    # Safety: stop, reverse, turn away
                    action = "evasive"
                    self._zumi.stop()

                    if obstacle_detected:
                        # Determine which side the obstacle is on
                        fr = ir_data[0]
                        fl = ir_data[5]
                        self._zumi.reverse(
                            speed=clamp_speed(self._speed),
                            duration=clamp_duration(0.3)
                        )
                        if fr < fl:
                            # Obstacle more on the right, turn left
                            self._zumi.turn_left(desired_angle=30)
                        else:
                            # Obstacle more on the left, turn right
                            self._zumi.turn_right(desired_angle=30)

                        if not dropoff_detected:
                            # Publish and continue loop
                            self._publish_status(
                                target_detected, bearing, target_area,
                                obstacle_detected, dropoff_detected, action
                            )
                            continue

                    if dropoff_detected:
                        # Drop-off: stop immediately, reverse
                        self._zumi.reverse(
                            speed=clamp_speed(self._speed),
                            duration=clamp_duration(0.3)
                        )
                        self._zumi.turn_left(desired_angle=45)

                    self._publish_status(
                        target_detected, bearing, target_area,
                        obstacle_detected, dropoff_detected, action
                    )
                    continue

                elif target_detected:
                    bbox = target_detection.bounding_box
                    bearing = compute_bearing(bbox)
                    target_area = (
                        (bbox["bottom"] - bbox["top"])
                        * (bbox["right"] - bbox["left"])
                    )

                    # Check if target is reached
                    if check_target_reached(bbox, self._target_reached_fraction):
                        action = "target_reached"
                        self._zumi.stop()
                        termination_reason = "target_reached"
                        logger.info(
                            "Target '%s' reached at step %d",
                            self._target_label, self._step
                        )
                        self._publish_status(
                            target_detected, bearing, target_area,
                            obstacle_detected, dropoff_detected, action
                        )
                        break

                    # Steer toward target
                    action = compute_steering_action(bearing)
                    if action == "turn_left":
                        self._zumi.turn_left(desired_angle=15)
                    elif action == "turn_right":
                        self._zumi.turn_right(desired_angle=15)
                    else:
                        self._zumi.forward(
                            speed=clamp_speed(self._speed),
                            duration=clamp_duration(0.3)
                        )

                    # Reset lost counter on detection
                    self._lost_counter = 0

                else:
                    # Target not detected
                    self._lost_counter += 1
                    action = "searching"

                    if self._lost_counter > self._lost_target_limit:
                        # Scan rotation
                        action = "scanning"
                        found = False
                        for scan_step in range(self.SCAN_STEPS_FULL):
                            if self._stop_event.is_set():
                                break
                            self._zumi.turn_left(desired_angle=self.SCAN_TURN_ANGLE)
                            scan_frame = self._capture_frame()
                            if scan_frame is not None:
                                try:
                                    scan_detections = self._inference_engine.detect(
                                        scan_frame
                                    )
                                    for det in scan_detections:
                                        if (det.class_label == self._target_label
                                                and det.confidence >= self._confidence_threshold):
                                            found = True
                                            break
                                except Exception as e:
                                    logger.error("Scan inference error: %s", e)
                            if found:
                                self._lost_counter = 0
                                break

                        if not found:
                            termination_reason = "target_lost"
                            logger.info(
                                "Target '%s' lost after full scan at step %d",
                                self._target_label, self._step
                            )
                            self._publish_status(
                                False, bearing, target_area,
                                obstacle_detected, dropoff_detected, action
                            )
                            break

                # 7. Publish status
                self._publish_status(
                    target_detected, bearing, target_area,
                    obstacle_detected, dropoff_detected, action
                )

            # Check if stopped by external signal
            if self._stop_event.is_set() and termination_reason == "error":
                termination_reason = "stopped"

        except Exception as e:
            logger.error("Navigation loop error: %s", e)
            termination_reason = "error"

        finally:
            # Always stop motors
            try:
                self._zumi.stop()
            except Exception as e:
                logger.error("Error stopping zumi in finally block: %s", e)

            # Close camera
            self._close_camera()

            # Publish final status
            self._publish_final_status(termination_reason)

        return {
            "termination_reason": termination_reason,
            "steps_completed": self._step,
            "target_label": self._target_label,
            "backend": self._inference_engine.get_backend_name(),
        }

    def stop(self):
        """Signal the navigation loop to terminate."""
        self._stop_event.set()

    # -- Internal helpers --------------------------------------------------

    def _init_camera(self):
        """Initialize the PiCamera for frame capture."""
        from zumi.util.camera import Camera
        cam = Camera(320, 240)
        cam.start_camera()
        time.sleep(1)  # sensor warmup
        return cam

    def _capture_frame(self):
        """Capture a single frame from the camera.

        Returns:
            numpy array (BGR) or None on failure.
        """
        if self._camera is None:
            return None
        try:
            return self._camera.capture()
        except Exception as e:
            logger.error("Camera capture error: %s", e)
            return None

    def _close_camera(self):
        """Close the camera if open."""
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:
                pass
            self._camera = None

    def _read_ir_sensors(self):
        """Read all IR sensor data from the Zumi.

        Returns:
            list of 6 int values [FR, BR, BackR, BL, BackL, FL].
            On failure, returns safe defaults (all zeros = obstacle assumed).
        """
        try:
            return self._zumi.get_all_IR_data()
        except Exception as e:
            logger.error("IR sensor read error: %s — assuming obstacle", e)
            return [0, 0, 0, 0, 0, 0]

    def _publish_status(self, target_detected, bearing, target_area,
                        obstacle_detected, dropoff_detected, action):
        """Publish a navigation status update to the telemetry topic."""
        try:
            from awscrt import mqtt
        except ImportError:
            logger.warning("awscrt not available, skipping status publish")
            return

        status = {
            "type": "navigation_status",
            "status": "running",
            "step": self._step,
            "target_detected": target_detected,
            "target_label": self._target_label,
            "target_bearing": round(bearing, 4),
            "target_area": round(target_area, 4),
            "obstacle_detected": obstacle_detected,
            "dropoff_detected": dropoff_detected,
            "action": action,
            "backend": self._inference_engine.get_backend_name(),
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        try:
            self._mqtt_connection.publish(
                topic=self._telemetry_topic,
                payload=json.dumps(status),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
        except Exception as e:
            logger.error("Failed to publish navigation status: %s", e)

    def _publish_final_status(self, termination_reason):
        """Publish the final navigation status when the session ends."""
        try:
            from awscrt import mqtt
        except ImportError:
            logger.warning("awscrt not available, skipping final status publish")
            return

        status = {
            "type": "navigation_status",
            "status": "completed",
            "termination_reason": termination_reason,
            "steps_completed": self._step,
            "target_label": self._target_label,
            "backend": self._inference_engine.get_backend_name(),
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        try:
            self._mqtt_connection.publish(
                topic=self._telemetry_topic,
                payload=json.dumps(status),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
        except Exception as e:
            logger.error("Failed to publish final navigation status: %s", e)



# ---------------------------------------------------------------------------
# NavigationController — manages sessions in background thread
# ---------------------------------------------------------------------------

class NavigationController(object):
    """Manages navigation sessions, integrates with MQTT command handler.

    Runs NavigationSession in a background thread so the main MQTT
    command handler stays responsive for stop commands.
    """

    def __init__(self, zumi, screen, inference_engine, mqtt_connection,
                 thing_name, config):
        self._zumi = zumi
        self._screen = screen
        self._inference_engine = inference_engine
        self._mqtt_connection = mqtt_connection
        self._thing_name = thing_name
        self._config = config

        self._session = None
        self._thread = None
        self._result = None
        self._lock = threading.Lock()

    def start_navigation(self, target_label, **kwargs):
        """Start a new navigation session in a background thread.

        If a session is already active, stops it first.

        Args:
            target_label: str, the object class label to navigate toward.
            **kwargs: optional overrides for session parameters
                (max_steps, speed, obstacle_threshold, confidence_threshold,
                 target_reached_fraction, lost_target_limit, dropoff_threshold).

        Returns:
            dict with status='started'.
        """
        with self._lock:
            # Stop any existing session
            if self._session is not None:
                self._stop_current_session()

            # Build session parameters from config + overrides
            max_steps = kwargs.get(
                "max_steps",
                self._config.get("nav_max_steps", 50)
            )
            speed = kwargs.get(
                "speed",
                self._config.get("nav_default_speed", 30)
            )
            obstacle_threshold = kwargs.get(
                "obstacle_threshold",
                self._config.get("nav_obstacle_threshold", 100)
            )
            confidence_threshold = kwargs.get(
                "confidence_threshold",
                self._config.get("nav_confidence_threshold", 0.5)
            )
            target_reached_fraction = kwargs.get(
                "target_reached_fraction",
                self._config.get("nav_target_reached_fraction", 0.25)
            )
            lost_target_limit = kwargs.get(
                "lost_target_limit",
                self._config.get("nav_lost_target_limit", 5)
            )
            dropoff_threshold = kwargs.get(
                "dropoff_threshold",
                self._config.get("nav_dropoff_threshold", 200)
            )

            session = NavigationSession(
                zumi=self._zumi,
                screen=self._screen,
                inference_engine=self._inference_engine,
                mqtt_connection=self._mqtt_connection,
                thing_name=self._thing_name,
                target_label=target_label,
                max_steps=max_steps,
                speed=speed,
                obstacle_threshold=obstacle_threshold,
                confidence_threshold=confidence_threshold,
                target_reached_fraction=target_reached_fraction,
                lost_target_limit=lost_target_limit,
                dropoff_threshold=dropoff_threshold,
            )
            self._session = session
            self._result = None

            thread = threading.Thread(target=self._run_session, args=(session,))
            thread.daemon = True
            thread.start()
            self._thread = thread

        logger.info("Navigation started: target='%s'", target_label)
        return {"status": "started", "target_label": target_label}

    def stop_navigation(self):
        """Stop the active navigation session.

        Returns:
            dict with status and result, or None if no session was active.
        """
        with self._lock:
            if self._session is None:
                logger.info("No active navigation session to stop")
                return {"status": "no_session"}
            self._stop_current_session()
            result = self._result
        logger.info("Navigation stopped")
        return {"status": "stopped", "result": result}

    def is_active(self):
        """Return True if a navigation session is currently running."""
        with self._lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )

    def get_result(self):
        """Return the result of the last completed session, or None."""
        with self._lock:
            return self._result

    # -- Internal helpers --------------------------------------------------

    def _run_session(self, session):
        """Run a navigation session (called in background thread)."""
        try:
            result = session.run()
            with self._lock:
                self._result = result
            logger.info(
                "Navigation session completed: reason=%s, steps=%d",
                result.get("termination_reason", "unknown"),
                result.get("steps_completed", 0),
            )
        except Exception as e:
            logger.error("Navigation session error: %s", e)
            with self._lock:
                self._result = {
                    "termination_reason": "error",
                    "steps_completed": 0,
                    "error": str(e),
                }

    def _stop_current_session(self):
        """Stop the current session and wait for the thread to finish.

        Must be called while holding self._lock.
        """
        session = self._session
        thread = self._thread

        if session is not None:
            session.stop()

        # Release lock temporarily to let the thread finish
        # (the thread may need the lock to store its result)
        self._lock.release()
        try:
            if thread is not None and thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning(
                        "Navigation thread did not stop within 5 seconds"
                    )
        finally:
            self._lock.acquire()

        self._session = None
        self._thread = None
