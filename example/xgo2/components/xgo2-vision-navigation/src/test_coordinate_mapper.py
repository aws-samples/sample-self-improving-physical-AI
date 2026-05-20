"""
Property-based tests for coordinate_mapper.py using Hypothesis.

Feature: xgo2-ball-grip-calibration
Tests properties P2 through P10 from the design document.
"""
from __future__ import annotations

import math
import os
import sys

# Make coordinate_mapper importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from coordinate_mapper import (
    ARM_X_MAX,
    ARM_X_MIN,
    ARM_Z_MAX,
    ARM_Z_MIN,
    BallPositionEstimate,
    CalibrationProfile,
    GripStatus,
    arm_coords_to_ball_position,
    ball_position_to_arm_coords,
    compute_arm_step,
    compute_ball_position,
    is_grip_confirmed,
)


# ---------------------------------------------------------------------------
# Reusable Hypothesis strategies
# ---------------------------------------------------------------------------

def valid_bbox_strategy():
    """Generate a valid bounding box with top < bottom, left < right, all in [0.0, 1.0]."""
    return st.tuples(
        st.floats(min_value=0.0, max_value=1.0),
        st.floats(min_value=0.0, max_value=1.0),
    ).filter(
        lambda pair: pair[0] < pair[1]
    ).flatmap(
        lambda tb: st.tuples(
            st.just(tb),
            st.tuples(
                st.floats(min_value=0.0, max_value=1.0),
                st.floats(min_value=0.0, max_value=1.0),
            ).filter(lambda pair: pair[0] < pair[1]),
        )
    ).map(
        lambda parts: {
            "top": parts[0][0],
            "bottom": parts[0][1],
            "left": parts[1][0],
            "right": parts[1][1],
        }
    )


def depth_map_strategy(min_h=10, max_h=60, min_w=10, max_w=80):
    """Generate a random 2D depth map with values in [0.0, 1.0].

    Uses np.random inside a composite strategy to avoid exceeding
    Hypothesis's internal buffer size limit for large arrays.
    """
    @st.composite
    def _build(draw):
        h = draw(st.integers(min_value=min_h, max_value=max_h))
        w = draw(st.integers(min_value=min_w, max_value=max_w))
        seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
        rng = np.random.RandomState(seed)
        return rng.random_sample((h, w)).astype(np.float64)
    return _build()


def ball_position_estimate_strategy():
    """Generate a random BallPositionEstimate with valid ranges."""
    return st.builds(
        BallPositionEstimate,
        depth=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        height=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        h_offset=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )


def calibration_profile_strategy():
    """Generate a random CalibrationProfile with arbitrary scale and offset values."""
    return st.builds(
        CalibrationProfile,
        depth_to_x_scale=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        height_to_z_scale=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        depth_offset=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        height_offset=st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        arm_x_min=st.just(-80),
        arm_x_max=st.just(155),
        arm_z_min=st.just(-95),
        arm_z_max=st.just(155),
    )


def grip_status_strategy():
    """Generate a random GripStatus instance."""
    return st.builds(
        GripStatus,
        step=st.integers(min_value=0, max_value=10000),
        ball_detected=st.booleans(),
        ball_position=st.one_of(st.none(), ball_position_estimate_strategy()),
        arm_x=st.integers(min_value=-80, max_value=155),
        arm_z=st.integers(min_value=-95, max_value=155),
        error_magnitude=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        convergence_state=st.sampled_from(["seeking", "converging", "confirmed", "lost"]),
        termination_reason=st.one_of(st.none(), st.sampled_from([
            "grip_success", "grip_uncertain", "ball_lost", "timeout", "stopped", "error",
        ])),
        timestamp=st.text(
            alphabet=st.sampled_from("0123456789-T:Z."),
            min_size=10,
            max_size=30,
        ),
    )


# ---------------------------------------------------------------------------
# P2: Ball position estimate output ranges
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 2: Ball position estimate output ranges
@given(
    bbox=valid_bbox_strategy(),
    depth_map=depth_map_strategy(),
    frame_width=st.integers(min_value=1, max_value=1920),
    frame_height=st.integers(min_value=1, max_value=1080),
)
@settings(max_examples=30)
def test_ball_position_estimate_output_ranges(bbox, depth_map, frame_width, frame_height):
    """**Validates: Requirements 4.1, 4.3, 4.4, 4.5**

    For any valid bbox and depth map, compute_ball_position() must produce
    depth in [0,1], height in [-1,1], h_offset in [-1,1].
    """
    result = compute_ball_position(bbox, depth_map, frame_width, frame_height)

    assert 0.0 <= result.depth <= 1.0, f"depth {result.depth} out of [0, 1]"
    assert -1.0 <= result.height <= 1.0, f"height {result.height} out of [-1, 1]"
    assert -1.0 <= result.h_offset <= 1.0, f"h_offset {result.h_offset} out of [-1, 1]"


# ---------------------------------------------------------------------------
# P3: Depth extraction uses median of patch
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 3: Depth extraction uses median of patch
@given(
    bbox=valid_bbox_strategy(),
    depth_map=depth_map_strategy(),
    frame_width=st.integers(min_value=1, max_value=1920),
    frame_height=st.integers(min_value=1, max_value=1080),
)
@settings(max_examples=100)
def test_depth_extraction_uses_median_of_patch(bbox, depth_map, frame_width, frame_height):
    """**Validates: Requirements 4.2**

    The depth value returned by compute_ball_position() must equal the median
    of the 5x5 patch at the bbox centroid (clamped to frame boundaries).
    """
    patch_size = 5
    result = compute_ball_position(bbox, depth_map, frame_width, frame_height, patch_size=patch_size)

    # Independently compute the expected median
    centroid_x = ((bbox["left"] + bbox["right"]) / 2.0) * frame_width
    centroid_y = ((bbox["top"] + bbox["bottom"]) / 2.0) * frame_height
    cx = int(round(centroid_x))
    cy = int(round(centroid_y))

    depth_h, depth_w = depth_map.shape[:2]
    half = patch_size // 2

    y_start = max(0, cy - half)
    y_end = min(depth_h, cy + half + 1)
    x_start = max(0, cx - half)
    x_end = min(depth_w, cx + half + 1)

    patch = depth_map[y_start:y_end, x_start:x_end]
    if patch.size > 0:
        expected_depth = float(np.median(patch))
    else:
        expected_depth = 0.0

    assert abs(result.depth - expected_depth) < 1e-9, (
        f"depth {result.depth} != expected median {expected_depth}"
    )


# ---------------------------------------------------------------------------
# P4: Arm coordinate clamping invariant
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 4: Arm coordinate clamping invariant
@given(
    estimate=ball_position_estimate_strategy(),
    profile=calibration_profile_strategy(),
)
@settings(max_examples=100)
def test_arm_coordinate_clamping_invariant(estimate, profile):
    """**Validates: Requirements 5.3, 5.4, 13.1**

    For any BallPositionEstimate and CalibrationProfile,
    ball_position_to_arm_coords() must return arm_x in [-80, 155] and arm_z in [-95, 155].
    """
    arm_x, arm_z = ball_position_to_arm_coords(estimate, profile)

    assert ARM_X_MIN <= arm_x <= ARM_X_MAX, f"arm_x {arm_x} out of [{ARM_X_MIN}, {ARM_X_MAX}]"
    assert ARM_Z_MIN <= arm_z <= ARM_Z_MAX, f"arm_z {arm_z} out of [{ARM_Z_MIN}, {ARM_Z_MAX}]"


# ---------------------------------------------------------------------------
# P5: Arm step clamping
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 5: Arm step clamping
@given(
    error_x=st.integers(min_value=-10000, max_value=10000),
    error_z=st.integers(min_value=-10000, max_value=10000),
    gain=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
    max_step=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=100)
def test_arm_step_clamping(error_x, error_z, gain, max_step):
    """**Validates: Requirements 6.4, 13.2**

    For any error vector, positive gain, and positive max_step,
    compute_arm_step() must return |delta_x| <= max_step and |delta_z| <= max_step.
    """
    delta_x, delta_z = compute_arm_step(error_x, error_z, gain, max_step)

    assert abs(delta_x) <= max_step, f"|delta_x| = {abs(delta_x)} > max_step = {max_step}"
    assert abs(delta_z) <= max_step, f"|delta_z| = {abs(delta_z)} > max_step = {max_step}"


# ---------------------------------------------------------------------------
# P6: Coordinate mapping round-trip
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 6: Coordinate mapping round-trip
@given(
    estimate=st.builds(
        BallPositionEstimate,
        depth=st.floats(min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False),
        height=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
        h_offset=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    ),
    profile=st.builds(
        CalibrationProfile,
        depth_to_x_scale=st.floats(min_value=100.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        height_to_z_scale=st.floats(min_value=100.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        depth_offset=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        height_offset=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        arm_x_min=st.just(-80),
        arm_x_max=st.just(155),
        arm_z_min=st.just(-95),
        arm_z_max=st.just(155),
    ),
)
@settings(max_examples=100)
def test_coordinate_mapping_round_trip(estimate, profile):
    """**Validates: Requirements 5.5**

    For inputs where the forward mapping does NOT hit clamp boundaries,
    converting to arm coords and back must produce depth and height within 0.01 tolerance.
    """
    # Compute raw (unclamped) arm coordinates
    raw_arm_x = estimate.depth * profile.depth_to_x_scale + profile.depth_offset
    raw_arm_z = estimate.height * profile.height_to_z_scale + profile.height_offset

    # Filter to cases where the forward mapping does NOT hit clamp boundaries
    assume(-80 < raw_arm_x < 155)
    assume(-95 < raw_arm_z < 155)

    arm_x, arm_z = ball_position_to_arm_coords(estimate, profile)
    recovered = arm_coords_to_ball_position(arm_x, arm_z, profile)

    assert abs(recovered.depth - estimate.depth) <= 0.01, (
        f"round-trip depth: {recovered.depth} vs {estimate.depth}"
    )
    assert abs(recovered.height - estimate.height) <= 0.01, (
        f"round-trip height: {recovered.height} vs {estimate.height}"
    )


# ---------------------------------------------------------------------------
# P7: CalibrationProfile serialization round-trip
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 7: CalibrationProfile serialization round-trip
@given(profile=calibration_profile_strategy())
@settings(max_examples=100)
def test_calibration_profile_serialization_round_trip(profile):
    """**Validates: Requirements 14.1**

    Serializing a CalibrationProfile via to_dict() and deserializing via from_dict()
    must produce all numeric fields matching within 1e-6.
    """
    d = profile.to_dict()
    restored = CalibrationProfile.from_dict(d)

    assert abs(restored.depth_to_x_scale - profile.depth_to_x_scale) < 1e-6
    assert abs(restored.height_to_z_scale - profile.height_to_z_scale) < 1e-6
    assert abs(restored.depth_offset - profile.depth_offset) < 1e-6
    assert abs(restored.height_offset - profile.height_offset) < 1e-6
    assert restored.arm_x_min == profile.arm_x_min
    assert restored.arm_x_max == profile.arm_x_max
    assert restored.arm_z_min == profile.arm_z_min
    assert restored.arm_z_max == profile.arm_z_max


# ---------------------------------------------------------------------------
# P8: BallPositionEstimate serialization round-trip
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 8: BallPositionEstimate serialization round-trip
@given(estimate=ball_position_estimate_strategy())
@settings(max_examples=100)
def test_ball_position_estimate_serialization_round_trip(estimate):
    """**Validates: Requirements 14.2**

    Serializing a BallPositionEstimate via to_dict() and deserializing via from_dict()
    must produce depth, height, h_offset matching within 1e-6.
    """
    d = estimate.to_dict()
    restored = BallPositionEstimate.from_dict(d)

    assert abs(restored.depth - estimate.depth) < 1e-6
    assert abs(restored.height - estimate.height) < 1e-6
    assert abs(restored.h_offset - estimate.h_offset) < 1e-6


# ---------------------------------------------------------------------------
# P9: GripStatus serialization round-trip
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 9: GripStatus serialization round-trip
@given(status=grip_status_strategy())
@settings(max_examples=100)
def test_grip_status_serialization_round_trip(status):
    """**Validates: Requirements 14.4**

    Serializing a GripStatus via to_dict() and deserializing via from_dict()
    must produce all fields matching (numeric within 1e-6).
    """
    d = status.to_dict()
    restored = GripStatus.from_dict(d)

    assert restored.step == status.step
    assert restored.ball_detected == status.ball_detected
    assert restored.arm_x == status.arm_x
    assert restored.arm_z == status.arm_z
    assert abs(restored.error_magnitude - status.error_magnitude) < 1e-6
    assert restored.convergence_state == status.convergence_state
    assert restored.termination_reason == status.termination_reason
    assert restored.timestamp == status.timestamp

    # Check ball_position sub-object
    if status.ball_position is None:
        assert restored.ball_position is None
    else:
        assert restored.ball_position is not None
        assert abs(restored.ball_position.depth - status.ball_position.depth) < 1e-6
        assert abs(restored.ball_position.height - status.ball_position.height) < 1e-6
        assert abs(restored.ball_position.h_offset - status.ball_position.h_offset) < 1e-6


# ---------------------------------------------------------------------------
# P10: Grip confirmation logic
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 10: Grip confirmation logic
@given(
    bbox=valid_bbox_strategy(),
    target_x_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    target_y_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    pixel_tolerance=st.integers(min_value=1, max_value=500),
    min_area_fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    frame_width=st.integers(min_value=1, max_value=1920),
    frame_height=st.integers(min_value=1, max_value=1080),
)
@settings(max_examples=100)
def test_grip_confirmation_logic(
    bbox, target_x_norm, target_y_norm, pixel_tolerance, min_area_fraction,
    frame_width, frame_height,
):
    """**Validates: Requirements 7.1**

    is_grip_confirmed() must return True iff:
    (a) Euclidean distance between bbox centroid and target <= pixel_tolerance, AND
    (b) bbox area fraction >= min_area_fraction.
    """
    result = is_grip_confirmed(
        bbox, target_x_norm, target_y_norm,
        pixel_tolerance, min_area_fraction,
        frame_width, frame_height,
    )

    # Independently compute the conditions
    cx = ((bbox["left"] + bbox["right"]) / 2.0) * frame_width
    cy = ((bbox["top"] + bbox["bottom"]) / 2.0) * frame_height
    tx = target_x_norm * frame_width
    ty = target_y_norm * frame_height

    distance = math.sqrt((cx - tx) ** 2 + (cy - ty) ** 2)
    area_fraction = (bbox["bottom"] - bbox["top"]) * (bbox["right"] - bbox["left"])

    expected = (distance <= pixel_tolerance) and (area_fraction >= min_area_fraction)

    assert result == expected, (
        f"is_grip_confirmed returned {result}, expected {expected}; "
        f"distance={distance}, pixel_tolerance={pixel_tolerance}, "
        f"area_fraction={area_fraction}, min_area_fraction={min_area_fraction}"
    )
