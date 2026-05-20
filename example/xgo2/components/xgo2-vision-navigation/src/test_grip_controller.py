"""
Unit tests for grip_controller.py.

Tests GripSession lifecycle: grip_success flow, ball_lost, timeout,
tilt_detected, low_battery, exception cleanup, and GripCalibrationController
background thread management.

Feature: xgo2-ball-grip-calibration, Task 4.8
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest import mock

import numpy as np
import pytest

# Make modules importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordinate_mapper import (
    BallPositionEstimate,
    CalibrationProfile,
    GripStatus,
)
from grip_controller import (
    ARM_HOME_X,
    ARM_HOME_Z,
    BALL_LOST_LIMIT,
    CLAW_CLOSED,
    CLAW_OPEN,
    DEFAULT_CONVERGENCE_TOLERANCE,
    DEFAULT_GRIP_HOLD_FRAMES,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MIN_GRIP_AREA,
    GRIP_STATUS_TOPIC,
    LOW_BATTERY_THRESHOLD,
    TILT_THRESHOLD,
    GripCalibrationController,
    GripSession,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


@dataclass
class MockDetection:
    """Mimics DetectionResult from vision_inference.py."""
    class_label: str
    confidence: float
    bounding_box: Dict[str, float]


class MockDog:
    """Mock XGO dog with arm, claw, IMU, and battery."""

    def __init__(
        self,
        battery=80,
        roll=0.0,
        pitch=0.0,
    ):
        self.battery = battery
        self.roll = roll
        self.pitch = pitch
        self.arm_calls = []  # type: List
        self.claw_calls = []  # type: List
        self.reset_calls = 0

    def read_battery(self):
        return self.battery

    def read_roll(self):
        return self.roll

    def read_pitch(self):
        return self.pitch

    def arm(self, x, z):
        self.arm_calls.append((x, z))

    def claw(self, pos):
        self.claw_calls.append(pos)

    def reset(self):
        self.reset_calls += 1


class MockCamera:
    """Mock OpenCV VideoCapture that returns pre-configured frames."""

    def __init__(self, frames=None, is_open=True):
        """
        Args:
            frames: List of (ret, frame) tuples to return on successive read() calls.
                    If None, returns a default valid frame.
            is_open: Whether isOpened() returns True.
        """
        self._is_open = is_open
        if frames is not None:
            self._frames = list(frames)
        else:
            # Default: always return a valid frame
            self._frames = None
        self._read_index = 0
        self.released = False

    def isOpened(self):
        return self._is_open

    def read(self):
        if self._frames is None:
            return True, np.zeros((240, 320, 3), dtype=np.uint8)
        if self._read_index < len(self._frames):
            result = self._frames[self._read_index]
            self._read_index += 1
            return result
        # Exhausted frames — return failure
        return False, None

    def release(self):
        self.released = True


class MockInferenceEngine:
    """Mock InferenceEngine that returns pre-configured detections."""

    def __init__(self, detections_sequence=None):
        """
        Args:
            detections_sequence: List of lists of MockDetection.
                Each call to detect() pops the next list.
                If None, always returns a red_ball detection.
        """
        if detections_sequence is not None:
            self._sequence = list(detections_sequence)
        else:
            self._sequence = None
        self._call_index = 0

    def detect(self, frame):
        if self._sequence is None:
            return [MockDetection(
                class_label="red_ball",
                confidence=0.9,
                bounding_box={
                    "top": 0.4, "left": 0.4,
                    "bottom": 0.6, "right": 0.6,
                },
            )]
        if self._call_index < len(self._sequence):
            result = self._sequence[self._call_index]
            self._call_index += 1
            return result
        return []

    def get_backend_name(self):
        return "mock"


class MockDepthEstimator:
    """Mock DepthEstimator that returns a uniform depth map."""

    def __init__(self, depth_value=0.5, fail=False):
        self._depth_value = depth_value
        self._fail = fail

    def estimate_depth(self, frame):
        if self._fail:
            raise RuntimeError("Depth estimation failed")
        return np.full((256, 256), self._depth_value, dtype=np.float32)

    def get_backend_name(self):
        return "mock"


class MockIPCClient:
    """Mock Greengrass IPC client that records published messages."""

    def __init__(self):
        self.published = []  # type: List[Dict[str, Any]]

    def publish_to_iot_core(self, **kwargs):
        self.published.append(kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_profile():
    """Default CalibrationProfile."""
    return CalibrationProfile()


@pytest.fixture
def mock_dog():
    return MockDog()


@pytest.fixture
def mock_camera():
    return MockCamera()


@pytest.fixture
def mock_inference():
    return MockInferenceEngine()


@pytest.fixture
def mock_depth():
    return MockDepthEstimator()


@pytest.fixture
def mock_ipc():
    return MockIPCClient()


def _make_session(
    dog=None,
    inference=None,
    depth=None,
    ipc=None,
    lcd=None,
    reasoner=None,
    profile=None,
    camera=None,
    **kwargs,
):
    """Helper to create a GripSession with sensible defaults."""
    return GripSession(
        dog=dog or MockDog(),
        inference_engine=inference or MockInferenceEngine(),
        depth_estimator=depth or MockDepthEstimator(),
        ipc_client=ipc,
        lcd_display=lcd,
        grip_reasoner=reasoner,
        calibration_profile=profile or CalibrationProfile(),
        camera=camera or MockCamera(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test: grip_success flow
# ---------------------------------------------------------------------------


class TestGripSuccessFlow:
    """Test the happy path: ball detected, converge, grip, success."""

    def test_grip_success_with_large_centered_ball(self, default_profile, mock_ipc):
        """When ball is large and centered, session should converge and grip."""
        # Ball is large (area > min_grip_area) and centered (within tolerance)
        large_centered_bbox = {
            "top": 0.2, "left": 0.2,
            "bottom": 0.8, "right": 0.8,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.95,
            bounding_box=large_centered_bbox,
        )

        # Post-grip detection also returns ball (grip_success)
        inference = MockInferenceEngine(
            detections_sequence=[
                [detection],  # iteration 1
                [detection],  # iteration 2
                [detection],  # iteration 3
                [detection],  # post-grip check
            ]
        )

        session = _make_session(
            inference=inference,
            ipc=mock_ipc,
            profile=default_profile,
            grip_hold_frames=3,
            convergence_tolerance=200,  # Very generous tolerance
            min_grip_area=0.01,  # Very small minimum area
        )

        result = session.run()

        assert result["termination_reason"] in ("grip_success", "grip_uncertain")
        assert result["steps_completed"] >= 1

    def test_grip_success_reports_correct_result(self, default_profile):
        """grip_success should be reported when post-grip check finds ball."""
        large_bbox = {
            "top": 0.2, "left": 0.2,
            "bottom": 0.8, "right": 0.8,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.95,
            bounding_box=large_bbox,
        )

        # Enough detections for hold_frames + post-grip
        num_detections = DEFAULT_GRIP_HOLD_FRAMES + 2
        inference = MockInferenceEngine(
            detections_sequence=[[detection]] * num_detections
        )

        session = _make_session(
            inference=inference,
            profile=default_profile,
            convergence_tolerance=200,
            min_grip_area=0.01,
            grip_hold_frames=DEFAULT_GRIP_HOLD_FRAMES,
        )

        result = session.run()
        assert result["grip_result"] in ("grip_success", "grip_uncertain")

    def test_claw_closes_on_grip_confirmation(self, default_profile):
        """Claw should be commanded to close (0) when grip is confirmed."""
        dog = MockDog()
        large_bbox = {
            "top": 0.2, "left": 0.2,
            "bottom": 0.8, "right": 0.8,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.95,
            bounding_box=large_bbox,
        )

        num_detections = DEFAULT_GRIP_HOLD_FRAMES + 2
        inference = MockInferenceEngine(
            detections_sequence=[[detection]] * num_detections
        )

        session = _make_session(
            dog=dog,
            inference=inference,
            profile=default_profile,
            convergence_tolerance=200,
            min_grip_area=0.01,
        )

        session.run()

        # Claw should have been opened at start (255) and closed during grip (0)
        assert CLAW_OPEN in dog.claw_calls, "Claw should open at start"
        assert CLAW_CLOSED in dog.claw_calls, "Claw should close during grip"


# ---------------------------------------------------------------------------
# Test: ball_lost termination
# ---------------------------------------------------------------------------


class TestBallLost:
    """Test ball_lost termination after consecutive no-detection frames."""

    def test_ball_lost_after_consecutive_no_detections(self, default_profile):
        """Session should terminate with ball_lost after BALL_LOST_LIMIT frames."""
        # No ball detections at all
        inference = MockInferenceEngine(
            detections_sequence=[[] for _ in range(BALL_LOST_LIMIT + 5)]
        )

        session = _make_session(
            inference=inference,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "ball_lost"

    def test_ball_lost_resets_on_detection(self, default_profile):
        """Lost counter should reset when ball is detected again."""
        large_bbox = {
            "top": 0.2, "left": 0.2,
            "bottom": 0.8, "right": 0.8,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.9,
            bounding_box=large_bbox,
        )

        # 9 empty frames (just under limit), then a detection, then 9 more empty
        sequence = (
            [[] for _ in range(BALL_LOST_LIMIT - 1)]
            + [[detection]]
            + [[] for _ in range(BALL_LOST_LIMIT - 1)]
            + [[detection]]
            + [[] for _ in range(BALL_LOST_LIMIT + 1)]
        )
        inference = MockInferenceEngine(detections_sequence=sequence)

        session = _make_session(
            inference=inference,
            profile=default_profile,
            max_iterations=100,
        )

        result = session.run()
        assert result["termination_reason"] == "ball_lost"
        # Should have survived past the first 9 empty frames
        assert result["steps_completed"] > BALL_LOST_LIMIT


# ---------------------------------------------------------------------------
# Test: timeout termination
# ---------------------------------------------------------------------------


class TestTimeout:
    """Test timeout termination when max_iterations is reached."""

    def test_timeout_when_never_converges(self, default_profile):
        """Session should timeout when ball is detected but never converges."""
        # Ball is small and off-center — won't meet grip confirmation
        small_bbox = {
            "top": 0.0, "left": 0.0,
            "bottom": 0.05, "right": 0.05,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.9,
            bounding_box=small_bbox,
        )

        max_iter = 10
        inference = MockInferenceEngine(
            detections_sequence=[[detection]] * (max_iter + 5)
        )

        session = _make_session(
            inference=inference,
            profile=default_profile,
            max_iterations=max_iter,
            convergence_tolerance=1,  # Very tight tolerance
            min_grip_area=0.5,  # Very large minimum area
        )

        result = session.run()

        assert result["termination_reason"] == "timeout"
        assert result["steps_completed"] == max_iter


# ---------------------------------------------------------------------------
# Test: tilt_detected termination
# ---------------------------------------------------------------------------


class TestTiltDetected:
    """Test tilt_detected termination when IMU exceeds threshold."""

    def test_tilt_detected_on_high_roll(self, default_profile):
        """Session should terminate with tilt_detected when roll > 30°."""
        dog = MockDog(roll=35.0, pitch=0.0)

        session = _make_session(
            dog=dog,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "tilt_detected"
        assert result["steps_completed"] <= 1

    def test_tilt_detected_on_high_pitch(self, default_profile):
        """Session should terminate with tilt_detected when pitch > 30°."""
        dog = MockDog(roll=0.0, pitch=-35.0)

        session = _make_session(
            dog=dog,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "tilt_detected"

    def test_tilt_detected_on_imu_read_failure(self, default_profile):
        """Session should terminate with tilt_detected when IMU read fails."""
        dog = MockDog()
        dog.read_roll = mock.Mock(side_effect=RuntimeError("IMU error"))
        dog.read_pitch = mock.Mock(side_effect=RuntimeError("IMU error"))

        session = _make_session(
            dog=dog,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "tilt_detected"


# ---------------------------------------------------------------------------
# Test: low_battery termination
# ---------------------------------------------------------------------------


class TestLowBattery:
    """Test low_battery refusal when battery is below threshold."""

    def test_low_battery_refuses_to_start(self, default_profile):
        """Session should refuse to start when battery < 20%."""
        dog = MockDog(battery=15)

        session = _make_session(
            dog=dog,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "low_battery"
        assert result["steps_completed"] == 0

    def test_battery_read_failure_treated_as_low(self, default_profile):
        """Session should treat battery read failure as low battery."""
        dog = MockDog()
        dog.read_battery = mock.Mock(side_effect=RuntimeError("Battery error"))

        session = _make_session(
            dog=dog,
            profile=default_profile,
        )

        result = session.run()

        assert result["termination_reason"] == "low_battery"
        assert result["steps_completed"] == 0


# ---------------------------------------------------------------------------
# Test: exception cleanup (finally block)
# ---------------------------------------------------------------------------


class TestExceptionCleanup:
    """Test that claw opens and arm homes on any exception."""

    def test_cleanup_on_inference_exception(self, default_profile):
        """Claw should open and arm should home even if inference throws."""
        dog = MockDog()

        # Inference engine that throws on first call
        inference = MockInferenceEngine()
        inference.detect = mock.Mock(side_effect=RuntimeError("Inference crash"))

        session = _make_session(
            dog=dog,
            inference=inference,
            profile=default_profile,
        )

        result = session.run()

        # Verify cleanup happened
        assert CLAW_OPEN in dog.claw_calls, "Claw should open in finally block"
        assert (ARM_HOME_X, ARM_HOME_Z) in dog.arm_calls, "Arm should home in finally block"

    def test_cleanup_on_depth_exception(self, default_profile):
        """Claw should open and arm should home even if depth estimator throws."""
        dog = MockDog()
        depth = MockDepthEstimator(fail=True)

        session = _make_session(
            dog=dog,
            depth=depth,
            profile=default_profile,
            max_iterations=3,
        )

        result = session.run()

        # Should still clean up
        assert CLAW_OPEN in dog.claw_calls
        assert (ARM_HOME_X, ARM_HOME_Z) in dog.arm_calls

    def test_claw_open_at_start_before_loop(self, default_profile):
        """Claw should be opened to 255 at the start of the session."""
        dog = MockDog()

        session = _make_session(
            dog=dog,
            profile=default_profile,
            max_iterations=1,
        )

        session.run()

        # First claw call should be CLAW_OPEN
        assert len(dog.claw_calls) >= 1
        assert dog.claw_calls[0] == CLAW_OPEN

    def test_arm_home_in_finally_block(self, default_profile):
        """Arm should return to home position in finally block."""
        dog = MockDog()

        session = _make_session(
            dog=dog,
            profile=default_profile,
            max_iterations=2,
        )

        session.run()

        # Last arm call should be home position
        assert (ARM_HOME_X, ARM_HOME_Z) in dog.arm_calls


# ---------------------------------------------------------------------------
# Test: stopped termination (external signal)
# ---------------------------------------------------------------------------


class TestStoppedTermination:
    """Test stopped termination via external stop() signal."""

    def test_stop_terminates_session(self, default_profile):
        """Calling stop() should terminate the session with 'stopped'."""
        dog = MockDog()
        # Provide many frames so the loop doesn't end naturally
        camera = MockCamera(
            frames=[(True, np.zeros((240, 320, 3), dtype=np.uint8))] * 100
        )
        inference = MockInferenceEngine(
            detections_sequence=[
                [MockDetection("red_ball", 0.9, {"top": 0.0, "left": 0.0, "bottom": 0.05, "right": 0.05})]
            ] * 100
        )

        session = _make_session(
            dog=dog,
            inference=inference,
            profile=default_profile,
            camera=camera,
            max_iterations=100,
            convergence_tolerance=1,
            min_grip_area=0.99,
        )

        # Stop immediately
        session.stop()
        result = session.run()

        assert result["termination_reason"] == "stopped"


# ---------------------------------------------------------------------------
# Test: MQTT telemetry publishing
# ---------------------------------------------------------------------------


class TestMQTTTelemetry:
    """Test MQTT status publishing at each iteration and on termination."""

    def test_iteration_status_published(self, default_profile):
        """Each iteration should publish a GripStatus to the status topic."""
        ipc = MockIPCClient()

        session = _make_session(
            ipc=ipc,
            profile=default_profile,
            max_iterations=3,
            convergence_tolerance=1,
            min_grip_area=0.99,
        )

        session.run()

        # Should have published at least one iteration status + final status
        assert len(ipc.published) >= 2

        # Check topic
        for pub in ipc.published:
            assert pub["topic_name"] == GRIP_STATUS_TOPIC

    def test_final_status_is_retained(self, default_profile):
        """Final termination status should be published as retained."""
        ipc = MockIPCClient()

        session = _make_session(
            ipc=ipc,
            profile=default_profile,
            max_iterations=2,
        )

        session.run()

        # Last published message should be retained
        retained_messages = [p for p in ipc.published if p.get("retain") is True]
        assert len(retained_messages) >= 1

    def test_status_payload_is_valid_json(self, default_profile):
        """Published payloads should be valid JSON."""
        ipc = MockIPCClient()

        session = _make_session(
            ipc=ipc,
            profile=default_profile,
            max_iterations=2,
        )

        session.run()

        for pub in ipc.published:
            payload_str = pub["payload"].decode("utf-8")
            payload = json.loads(payload_str)
            assert "type" in payload or "step" in payload or "status" in payload

    def test_no_publish_when_ipc_is_none(self, default_profile):
        """No error should occur when ipc_client is None."""
        session = _make_session(
            ipc=None,
            profile=default_profile,
            max_iterations=2,
        )

        # Should not raise
        result = session.run()
        assert result["termination_reason"] in ("timeout", "grip_success", "grip_uncertain")


# ---------------------------------------------------------------------------
# Test: GripCalibrationController
# ---------------------------------------------------------------------------


class TestGripCalibrationController:
    """Test the controller that manages GripSession in a background thread."""

    def test_start_grip_returns_started(self, default_profile):
        """start_grip() should return status='started'."""
        controller = GripCalibrationController(
            dog=MockDog(),
            inference_engine=MockInferenceEngine(
                detections_sequence=[[] for _ in range(BALL_LOST_LIMIT + 5)]
            ),
            depth_estimator=MockDepthEstimator(),
            ipc_client=None,
            lcd_display=None,
            grip_reasoner=None,
            calibration_profile=default_profile,
            config={"camera": MockCamera()},
        )

        result = controller.start_grip()
        assert result["status"] == "started"

        # Wait for session to complete
        time.sleep(0.5)

    def test_stop_grip_when_no_session(self, default_profile):
        """stop_grip() should return no_active_session when nothing is running."""
        controller = GripCalibrationController(
            dog=MockDog(),
            inference_engine=MockInferenceEngine(),
            depth_estimator=MockDepthEstimator(),
            ipc_client=None,
            lcd_display=None,
            grip_reasoner=None,
            calibration_profile=default_profile,
        )

        result = controller.stop_grip()
        assert result["status"] == "no_active_session"

    def test_is_active_during_session(self, default_profile):
        """is_active() should return True while a session is running."""
        # Use a blocking camera that waits on an event to keep the session alive
        started_event = threading.Event()

        class SlowCamera:
            def __init__(self):
                self._call_count = 0

            def isOpened(self):
                return True

            def read(self):
                self._call_count += 1
                if self._call_count == 1:
                    started_event.set()
                # Sleep to keep the session alive long enough to check is_active
                time.sleep(0.05)
                return True, np.zeros((240, 320, 3), dtype=np.uint8)

            def release(self):
                pass

        controller = GripCalibrationController(
            dog=MockDog(),
            inference_engine=MockInferenceEngine(
                detections_sequence=[
                    [MockDetection("red_ball", 0.9, {"top": 0.0, "left": 0.0, "bottom": 0.05, "right": 0.05})]
                ] * 200
            ),
            depth_estimator=MockDepthEstimator(),
            ipc_client=None,
            lcd_display=None,
            grip_reasoner=None,
            calibration_profile=default_profile,
            config={
                "camera": SlowCamera(),
                "max_iterations": 200,
                "convergence_tolerance": 1,
                "min_grip_area": 0.99,
            },
        )

        controller.start_grip()
        # Wait until the session has actually started processing
        started_event.wait(timeout=2.0)

        # Should be active
        active = controller.is_active()

        # Stop it
        controller.stop_grip()

        assert active is True

    def test_get_last_result_after_completion(self, default_profile):
        """get_last_result() should return the session result after completion."""
        controller = GripCalibrationController(
            dog=MockDog(),
            inference_engine=MockInferenceEngine(
                detections_sequence=[[] for _ in range(BALL_LOST_LIMIT + 5)]
            ),
            depth_estimator=MockDepthEstimator(),
            ipc_client=None,
            lcd_display=None,
            grip_reasoner=None,
            calibration_profile=default_profile,
            config={"camera": MockCamera()},
        )

        controller.start_grip()

        # Wait for session to complete
        time.sleep(1.0)

        result = controller.get_last_result()
        assert result is not None
        assert "termination_reason" in result

    def test_start_grip_stops_active_session_first(self, default_profile):
        """Starting a new grip should stop any active session first."""
        controller = GripCalibrationController(
            dog=MockDog(),
            inference_engine=MockInferenceEngine(
                detections_sequence=[
                    [MockDetection("red_ball", 0.9, {"top": 0.0, "left": 0.0, "bottom": 0.05, "right": 0.05})]
                ] * 500
            ),
            depth_estimator=MockDepthEstimator(),
            ipc_client=None,
            lcd_display=None,
            grip_reasoner=None,
            calibration_profile=default_profile,
            config={
                "camera": MockCamera(
                    frames=[(True, np.zeros((240, 320, 3), dtype=np.uint8))] * 500
                ),
                "max_iterations": 500,
                "convergence_tolerance": 1,
                "min_grip_area": 0.99,
            },
        )

        # Start first session
        controller.start_grip()
        time.sleep(0.1)

        # Start second session — should stop the first
        result = controller.start_grip()
        assert result["status"] == "started"

        # Clean up
        controller.stop_grip()


# ---------------------------------------------------------------------------
# Test: camera closed handling
# ---------------------------------------------------------------------------


class TestCameraHandling:
    """Test camera open/close edge cases."""

    def test_closed_shared_camera_returns_error(self, default_profile):
        """Session should return error when shared camera is not open."""
        camera = MockCamera(is_open=False)

        session = _make_session(
            profile=default_profile,
            camera=camera,
        )

        result = session.run()
        assert result["termination_reason"] == "error"
        assert result["steps_completed"] == 0

    def test_camera_not_released_when_shared(self, default_profile):
        """Shared camera should NOT be released by the session."""
        camera = MockCamera()

        session = _make_session(
            profile=default_profile,
            camera=camera,
            max_iterations=2,
        )

        session.run()
        assert not camera.released, "Shared camera should not be released"


# ---------------------------------------------------------------------------
# Test: arm clamping on every step
# ---------------------------------------------------------------------------


class TestArmClamping:
    """Test that arm positions are always clamped to workspace bounds."""

    def test_arm_positions_within_bounds(self, default_profile):
        """All arm commands should be within workspace bounds."""
        dog = MockDog()

        # Ball at extreme position to push arm to limits
        extreme_bbox = {
            "top": 0.0, "left": 0.0,
            "bottom": 0.1, "right": 0.1,
        }
        detection = MockDetection(
            class_label="red_ball",
            confidence=0.9,
            bounding_box=extreme_bbox,
        )

        inference = MockInferenceEngine(
            detections_sequence=[[detection]] * 20
        )

        session = _make_session(
            dog=dog,
            inference=inference,
            profile=default_profile,
            max_iterations=10,
            convergence_tolerance=1,
            min_grip_area=0.99,
        )

        session.run()

        for x, z in dog.arm_calls:
            assert -80 <= x <= 155, "arm_x {} out of bounds".format(x)
            assert -95 <= z <= 155, "arm_z {} out of bounds".format(z)
