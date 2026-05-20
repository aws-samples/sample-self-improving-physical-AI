"""
Coordinate mapper for XGO2 ball grip calibration.

Device-side module. Python 3.9 compatible.
Pure functions — no side effects, no I/O, no hardware dependencies.

Maps ball detection bounding boxes + depth maps to arm workspace coordinates
and provides servoing helpers for the closed-loop grip controller.

Requirements: 4.1-4.6, 5.1-5.6, 6.4, 7.1, 13.1, 13.2, 14.1-14.4
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARM_X_MIN = -80
ARM_X_MAX = 155
ARM_Z_MIN = -95
ARM_Z_MAX = 155


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BallPositionEstimate:
    """Estimated 3D position of the red ball in camera-frame coordinates.

    Attributes:
        depth: Relative depth from depth map, 0.0 (far) to 1.0 (close).
        height: Normalized vertical position, -1.0 (top) to 1.0 (bottom).
        h_offset: Normalized horizontal offset, -1.0 (left) to 1.0 (right).
    """

    depth: float
    height: float
    h_offset: float

    def to_dict(self) -> Dict[str, float]:
        """Serialize to a JSON-compatible dict."""
        return {
            "depth": self.depth,
            "height": self.height,
            "h_offset": self.h_offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BallPositionEstimate":
        """Deserialize from a dict."""
        return cls(
            depth=d["depth"],
            height=d["height"],
            h_offset=d["h_offset"],
        )


@dataclass
class CalibrationProfile:
    """Camera-to-arm coordinate mapping parameters.

    Contains the scaling factors and offsets used to convert
    ball position estimates into arm workspace coordinates.

    Attributes:
        depth_to_x_scale: Maps depth [0,1] to arm_x range.
        height_to_z_scale: Maps height [-1,1] to arm_z range.
        depth_offset: arm_x offset at depth=0.
        height_offset: arm_z offset at height=0.
        arm_x_min: Minimum arm_x value.
        arm_x_max: Maximum arm_x value.
        arm_z_min: Minimum arm_z value.
        arm_z_max: Maximum arm_z value.
    """

    depth_to_x_scale: float = 200.0
    height_to_z_scale: float = 200.0
    depth_offset: float = -80.0
    height_offset: float = 30.0
    arm_x_min: int = -80
    arm_x_max: int = 155
    arm_z_min: int = -95
    arm_z_max: int = 155

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "depth_to_x_scale": self.depth_to_x_scale,
            "height_to_z_scale": self.height_to_z_scale,
            "depth_offset": self.depth_offset,
            "height_offset": self.height_offset,
            "arm_x_min": self.arm_x_min,
            "arm_x_max": self.arm_x_max,
            "arm_z_min": self.arm_z_min,
            "arm_z_max": self.arm_z_max,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CalibrationProfile":
        """Deserialize from a dict."""
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class GripStatus:
    """MQTT telemetry payload for a single servoing iteration.

    Attributes:
        step: Current iteration number.
        ball_detected: Whether the ball was detected this frame.
        ball_position: Estimated ball position, or None if not detected.
        arm_x: Current arm x coordinate.
        arm_z: Current arm z coordinate.
        error_magnitude: Euclidean magnitude of the servoing error.
        convergence_state: One of "seeking", "converging", "confirmed", "lost".
        termination_reason: None while running; set on completion.
        timestamp: ISO 8601 timestamp string.
    """

    step: int
    ball_detected: bool
    ball_position: Optional[BallPositionEstimate]
    arm_x: int
    arm_z: int
    error_magnitude: float
    convergence_state: str
    termination_reason: Optional[str]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "type": "grip_status",
            "step": self.step,
            "ball_detected": self.ball_detected,
            "ball_position": self.ball_position.to_dict() if self.ball_position else None,
            "arm_x": self.arm_x,
            "arm_z": self.arm_z,
            "error_magnitude": self.error_magnitude,
            "convergence_state": self.convergence_state,
            "termination_reason": self.termination_reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GripStatus":
        """Deserialize from a dict."""
        bp = d.get("ball_position")
        return cls(
            step=d["step"],
            ball_detected=d["ball_detected"],
            ball_position=BallPositionEstimate.from_dict(bp) if bp else None,
            arm_x=d["arm_x"],
            arm_z=d["arm_z"],
            error_magnitude=d["error_magnitude"],
            convergence_state=d["convergence_state"],
            termination_reason=d.get("termination_reason"),
            timestamp=d["timestamp"],
        )


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def compute_ball_position(
    bbox: Dict[str, float],
    depth_map: np.ndarray,
    frame_width: int,
    frame_height: int,
    patch_size: int = 5,
) -> BallPositionEstimate:
    """Combine bounding box + depth map into a 3D position estimate.

    Args:
        bbox: Dict with keys "top", "left", "bottom", "right" as floats
            in [0.0, 1.0] relative to frame dimensions.
        depth_map: 2D numpy array with depth values in [0.0, 1.0].
        frame_width: Width of the camera frame in pixels.
        frame_height: Height of the camera frame in pixels.
        patch_size: Size of the square patch for median depth sampling.

    Returns:
        BallPositionEstimate with depth, height, and h_offset.
    """
    # Extract centroid pixel coordinates from bbox
    centroid_x = ((bbox["left"] + bbox["right"]) / 2.0) * frame_width
    centroid_y = ((bbox["top"] + bbox["bottom"]) / 2.0) * frame_height

    # Sample depth via median of a patch_size x patch_size patch at centroid
    cx = int(round(centroid_x))
    cy = int(round(centroid_y))

    depth_h, depth_w = depth_map.shape[:2]
    half = patch_size // 2

    # Clamp patch boundaries to depth map dimensions
    y_start = max(0, cy - half)
    y_end = min(depth_h, cy + half + 1)
    x_start = max(0, cx - half)
    x_end = min(depth_w, cx + half + 1)

    patch = depth_map[y_start:y_end, x_start:x_end]
    if patch.size > 0:
        depth = float(np.median(patch))
    else:
        depth = 0.0

    # Compute normalized height: -1.0 (top) to 1.0 (bottom)
    height = (centroid_y / frame_height) * 2.0 - 1.0

    # Compute horizontal offset: -1.0 (left) to 1.0 (right)
    h_offset = (centroid_x / frame_width) * 2.0 - 1.0

    return BallPositionEstimate(depth=depth, height=height, h_offset=h_offset)


def ball_position_to_arm_coords(
    estimate: BallPositionEstimate,
    profile: CalibrationProfile,
) -> Tuple[int, int]:
    """Map ball position to arm workspace coordinates with clamping.

    Args:
        estimate: Ball position in camera-frame coordinates.
        profile: Calibration parameters for the mapping.

    Returns:
        Tuple of (arm_x, arm_z) clamped to workspace bounds.
    """
    arm_x = estimate.depth * profile.depth_to_x_scale + profile.depth_offset
    arm_z = estimate.height * profile.height_to_z_scale + profile.height_offset

    # Clamp to workspace bounds
    arm_x = max(profile.arm_x_min, min(profile.arm_x_max, arm_x))
    arm_z = max(profile.arm_z_min, min(profile.arm_z_max, arm_z))

    return (int(arm_x), int(arm_z))


def arm_coords_to_ball_position(
    arm_x: int,
    arm_z: int,
    profile: CalibrationProfile,
) -> BallPositionEstimate:
    """Inverse mapping: arm coords back to estimated ball position.

    Args:
        arm_x: Arm x coordinate.
        arm_z: Arm z coordinate.
        profile: Calibration parameters for the inverse mapping.

    Returns:
        BallPositionEstimate with depth, height, and h_offset=0.0.
    """
    depth = (arm_x - profile.depth_offset) / profile.depth_to_x_scale
    height = (arm_z - profile.height_offset) / profile.height_to_z_scale

    return BallPositionEstimate(depth=depth, height=height, h_offset=0.0)


def compute_servoing_error(
    current_arm_x: int,
    current_arm_z: int,
    target_arm_x: int,
    target_arm_z: int,
) -> Tuple[int, int]:
    """Compute the servoing error vector.

    Args:
        current_arm_x: Current arm x position.
        current_arm_z: Current arm z position.
        target_arm_x: Target arm x position.
        target_arm_z: Target arm z position.

    Returns:
        Tuple of (error_x, error_z) where positive means target is ahead/above.
    """
    return (target_arm_x - current_arm_x, target_arm_z - current_arm_z)


def compute_arm_step(
    error_x: int,
    error_z: int,
    gain: float,
    max_step: int,
) -> Tuple[int, int]:
    """Compute proportional arm correction clamped to max_step per axis.

    Args:
        error_x: Servoing error in x axis.
        error_z: Servoing error in z axis.
        gain: Proportional gain factor.
        max_step: Maximum step size per axis.

    Returns:
        Tuple of (delta_x, delta_z) as integers, each clamped to [-max_step, max_step].
    """
    delta_x = error_x * gain
    delta_z = error_z * gain

    # Clamp to max_step
    delta_x = max(-max_step, min(max_step, delta_x))
    delta_z = max(-max_step, min(max_step, delta_z))

    return (int(delta_x), int(delta_z))


def clamp_arm_position(arm_x: int, arm_z: int) -> Tuple[int, int]:
    """Clamp arm position to workspace bounds.

    Args:
        arm_x: Arm x coordinate.
        arm_z: Arm z coordinate.

    Returns:
        Tuple of (clamped_x, clamped_z) within [-80, 155] x [-95, 155].
    """
    clamped_x = max(ARM_X_MIN, min(ARM_X_MAX, arm_x))
    clamped_z = max(ARM_Z_MIN, min(ARM_Z_MAX, arm_z))
    return (clamped_x, clamped_z)


def is_grip_confirmed(
    bbox: Dict[str, float],
    target_x_norm: float,
    target_y_norm: float,
    pixel_tolerance: int,
    min_area_fraction: float,
    frame_width: int,
    frame_height: int,
) -> bool:
    """Check if the ball bbox meets grip confirmation criteria.

    Grip is confirmed when:
    1. The bbox centroid is within pixel_tolerance of the target position.
    2. The bbox area fraction exceeds min_area_fraction.

    Args:
        bbox: Dict with keys "top", "left", "bottom", "right" in [0.0, 1.0].
        target_x_norm: Target x position normalized to [0.0, 1.0].
        target_y_norm: Target y position normalized to [0.0, 1.0].
        pixel_tolerance: Maximum Euclidean distance in pixels for convergence.
        min_area_fraction: Minimum bbox area as fraction of frame area.
        frame_width: Frame width in pixels.
        frame_height: Frame height in pixels.

    Returns:
        True if both centroid distance and area conditions are met.
    """
    # Compute bbox centroid in pixels
    cx = ((bbox["left"] + bbox["right"]) / 2.0) * frame_width
    cy = ((bbox["top"] + bbox["bottom"]) / 2.0) * frame_height

    # Compute target in pixels
    tx = target_x_norm * frame_width
    ty = target_y_norm * frame_height

    # Euclidean distance between centroid and target
    distance = math.sqrt((cx - tx) ** 2 + (cy - ty) ** 2)

    # Compute bbox area fraction
    area_fraction = (bbox["bottom"] - bbox["top"]) * (bbox["right"] - bbox["left"])

    return distance <= pixel_tolerance and area_fraction >= min_area_fraction
