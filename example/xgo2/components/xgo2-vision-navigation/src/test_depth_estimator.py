"""
Unit tests for depth_estimator.py.

Tests DepthEstimator initialization (DLR, TFLite fallback, missing model),
inference output shape and range validation.

Feature: xgo2-ball-grip-calibration, Task 3.5
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import numpy as np
import pytest

# Make depth_estimator importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from depth_estimator import (
    DEPTH_MODEL_INPUT_HEIGHT,
    DEPTH_MODEL_INPUT_WIDTH,
    DepthEstimator,
)


# ---------------------------------------------------------------------------
# Helpers: mock DLR model and TFLite interpreter
# ---------------------------------------------------------------------------


class MockDLRModel:
    """Mock DLR model that returns a plausible depth map."""

    def __init__(self, model_dir, device):
        self._model_dir = model_dir
        self._device = device

    def run(self, input_data):
        """Return a single-channel depth output shaped (1, H, W, 1)."""
        h = DEPTH_MODEL_INPUT_HEIGHT
        w = DEPTH_MODEL_INPUT_WIDTH
        # Produce a gradient depth map for predictable output
        depth = np.linspace(0.0, 10.0, h * w).reshape(1, h, w, 1).astype(
            np.float32
        )
        return [depth]


class MockTFLiteInterpreter:
    """Mock TFLite interpreter that returns a plausible depth map."""

    def __init__(self, model_path=None):
        self._model_path = model_path
        self._input_tensor = None

    def allocate_tensors(self):
        pass

    def get_input_details(self):
        return [
            {
                "index": 0,
                "dtype": np.float32,
                "shape": [
                    1,
                    DEPTH_MODEL_INPUT_HEIGHT,
                    DEPTH_MODEL_INPUT_WIDTH,
                    3,
                ],
            }
        ]

    def get_output_details(self):
        return [{"index": 0}]

    def set_tensor(self, index, data):
        self._input_tensor = data

    def invoke(self):
        pass

    def get_tensor(self, index):
        h = DEPTH_MODEL_INPUT_HEIGHT
        w = DEPTH_MODEL_INPUT_WIDTH
        depth = np.linspace(0.2, 5.0, h * w).reshape(1, h, w, 1).astype(
            np.float32
        )
        return depth


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_frame():
    """A 320x240 BGR frame (typical camera resolution)."""
    return np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)


@pytest.fixture
def small_frame():
    """A small 64x48 BGR frame for quick tests."""
    return np.random.randint(0, 256, (48, 64, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Test: init with mock DLR
# ---------------------------------------------------------------------------


class TestDepthEstimatorDLRInit:
    """Test DepthEstimator initialization with DLR backend."""

    def test_dlr_backend_loads_successfully(self, tmp_path):
        """DLR backend should load when dlr module is available."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")

        assert estimator.get_backend_name() == "dlr"

    def test_dlr_backend_raises_on_import_error(self, tmp_path):
        """DLR backend should raise RuntimeError when dlr is not installed."""
        with mock.patch.dict("sys.modules", {"dlr": None}):
            with pytest.raises(RuntimeError, match="Failed to load DLR"):
                DepthEstimator(str(tmp_path), backend="dlr")

    def test_dlr_backend_raises_on_model_load_error(self, tmp_path):
        """DLR backend should raise RuntimeError when model fails to load."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel.side_effect = ValueError("bad model")

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            with pytest.raises(RuntimeError, match="Failed to load DLR"):
                DepthEstimator(str(tmp_path), backend="dlr")


# ---------------------------------------------------------------------------
# Test: init with TFLite fallback
# ---------------------------------------------------------------------------


class TestDepthEstimatorTFLiteFallback:
    """Test DepthEstimator initialization with TFLite backend."""

    def test_tflite_backend_loads_successfully(self, tmp_path):
        """TFLite backend should load when a .tflite file exists."""
        # Create a dummy .tflite file
        tflite_file = tmp_path / "depth_model.tflite"
        tflite_file.write_bytes(b"dummy")

        mock_tflite_module = mock.MagicMock()
        mock_tflite_module.interpreter.Interpreter = MockTFLiteInterpreter

        with mock.patch.dict(
            "sys.modules",
            {"tflite_runtime": mock_tflite_module, "tflite_runtime.interpreter": mock_tflite_module.interpreter},
        ):
            estimator = DepthEstimator(str(tmp_path), backend="tflite")

        assert estimator.get_backend_name() == "tflite"

    def test_tflite_backend_raises_when_no_model_file(self, tmp_path):
        """TFLite backend should raise RuntimeError when no .tflite file exists."""
        with pytest.raises(RuntimeError, match="No .tflite depth model"):
            DepthEstimator(str(tmp_path), backend="tflite")

    def test_auto_falls_back_to_tflite_when_dlr_fails(self, tmp_path):
        """Auto mode should fall back to TFLite when DLR is unavailable."""
        # Create a dummy .tflite file
        tflite_file = tmp_path / "depth_model.tflite"
        tflite_file.write_bytes(b"dummy")

        mock_tflite_module = mock.MagicMock()
        mock_tflite_module.interpreter.Interpreter = MockTFLiteInterpreter

        with mock.patch.dict(
            "sys.modules",
            {
                "dlr": None,  # DLR not available
                "tflite_runtime": mock_tflite_module,
                "tflite_runtime.interpreter": mock_tflite_module.interpreter,
            },
        ):
            estimator = DepthEstimator(str(tmp_path), backend="auto")

        assert estimator.get_backend_name() == "tflite"

    def test_auto_prefers_dlr_when_available(self, tmp_path):
        """Auto mode should use DLR when it's available."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            estimator = DepthEstimator(str(tmp_path), backend="auto")

        assert estimator.get_backend_name() == "dlr"


# ---------------------------------------------------------------------------
# Test: missing model error
# ---------------------------------------------------------------------------


class TestDepthEstimatorMissingModel:
    """Test DepthEstimator raises RuntimeError when no backend can load."""

    def test_auto_raises_when_both_backends_fail(self, tmp_path):
        """Auto mode should raise RuntimeError when both DLR and TFLite fail."""
        # No .tflite file, DLR not available
        with mock.patch.dict("sys.modules", {"dlr": None}):
            with pytest.raises(RuntimeError, match="No depth inference backend"):
                DepthEstimator(str(tmp_path), backend="auto")

    def test_unknown_backend_raises(self, tmp_path):
        """Unknown backend name should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Unknown backend"):
            DepthEstimator(str(tmp_path), backend="xgoedu")

    def test_missing_model_dir_tflite(self):
        """TFLite backend should raise when model_dir doesn't exist."""
        with pytest.raises(RuntimeError, match="No .tflite depth model"):
            DepthEstimator("/nonexistent/path/to/model", backend="tflite")


# ---------------------------------------------------------------------------
# Test: output shape and range validation
# ---------------------------------------------------------------------------


class TestDepthEstimatorOutput:
    """Test estimate_depth output shape and value range."""

    def test_dlr_output_is_2d_with_valid_range(self, tmp_path, sample_frame):
        """DLR backend should return a 2D depth map with values in [0, 1]."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        mock_cv2 = mock.MagicMock()
        mock_cv2.resize.return_value = np.zeros(
            (DEPTH_MODEL_INPUT_HEIGHT, DEPTH_MODEL_INPUT_WIDTH, 3),
            dtype=np.uint8,
        )

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module, "cv2": mock_cv2}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")
            depth_map = estimator.estimate_depth(sample_frame)

        assert depth_map.ndim == 2, "Depth map should be 2D"
        assert depth_map.min() >= 0.0, "Depth values should be >= 0.0"
        assert depth_map.max() <= 1.0, "Depth values should be <= 1.0"

    def test_tflite_output_is_2d_with_valid_range(self, tmp_path, sample_frame):
        """TFLite backend should return a 2D depth map with values in [0, 1]."""
        tflite_file = tmp_path / "depth_model.tflite"
        tflite_file.write_bytes(b"dummy")

        mock_tflite_module = mock.MagicMock()
        mock_tflite_module.interpreter.Interpreter = MockTFLiteInterpreter

        mock_cv2 = mock.MagicMock()
        mock_cv2.resize.return_value = np.zeros(
            (DEPTH_MODEL_INPUT_HEIGHT, DEPTH_MODEL_INPUT_WIDTH, 3),
            dtype=np.uint8,
        )

        with mock.patch.dict(
            "sys.modules",
            {
                "tflite_runtime": mock_tflite_module,
                "tflite_runtime.interpreter": mock_tflite_module.interpreter,
                "cv2": mock_cv2,
            },
        ):
            estimator = DepthEstimator(str(tmp_path), backend="tflite")
            depth_map = estimator.estimate_depth(sample_frame)

        assert depth_map.ndim == 2, "Depth map should be 2D"
        assert depth_map.min() >= 0.0, "Depth values should be >= 0.0"
        assert depth_map.max() <= 1.0, "Depth values should be <= 1.0"

    def test_output_shape_matches_model_input(self, tmp_path, sample_frame):
        """Depth map dimensions should match the model input dimensions."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        mock_cv2 = mock.MagicMock()
        mock_cv2.resize.return_value = np.zeros(
            (DEPTH_MODEL_INPUT_HEIGHT, DEPTH_MODEL_INPUT_WIDTH, 3),
            dtype=np.uint8,
        )

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module, "cv2": mock_cv2}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")
            depth_map = estimator.estimate_depth(sample_frame)

        assert depth_map.shape == (
            DEPTH_MODEL_INPUT_HEIGHT,
            DEPTH_MODEL_INPUT_WIDTH,
        ), "Depth map shape should be (256, 256)"

    def test_constant_depth_returns_zeros(self, tmp_path, sample_frame):
        """A constant raw depth output should normalize to all zeros."""

        class ConstantDLRModel:
            def __init__(self, model_dir, device):
                pass

            def run(self, input_data):
                h = DEPTH_MODEL_INPUT_HEIGHT
                w = DEPTH_MODEL_INPUT_WIDTH
                # All same value — no depth variation
                depth = np.full((1, h, w, 1), 5.0, dtype=np.float32)
                return [depth]

        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = ConstantDLRModel

        mock_cv2 = mock.MagicMock()
        mock_cv2.resize.return_value = np.zeros(
            (DEPTH_MODEL_INPUT_HEIGHT, DEPTH_MODEL_INPUT_WIDTH, 3),
            dtype=np.uint8,
        )

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module, "cv2": mock_cv2}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")
            depth_map = estimator.estimate_depth(sample_frame)

        assert np.allclose(depth_map, 0.0), "Constant depth should normalize to zeros"

    def test_no_backend_raises_on_estimate(self, tmp_path):
        """Calling estimate_depth with no backend should raise RuntimeError."""
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")

        # Manually break the backend to simulate edge case
        estimator._backend = None
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        with pytest.raises(RuntimeError, match="No depth backend"):
            estimator.estimate_depth(frame)


# ---------------------------------------------------------------------------
# Test: get_backend_name accessor
# ---------------------------------------------------------------------------


class TestGetBackendName:
    """Test get_backend_name returns correct backend string."""

    def test_returns_dlr_for_dlr_backend(self, tmp_path):
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")

        assert estimator.get_backend_name() == "dlr"

    def test_returns_tflite_for_tflite_backend(self, tmp_path):
        tflite_file = tmp_path / "depth_model.tflite"
        tflite_file.write_bytes(b"dummy")

        mock_tflite_module = mock.MagicMock()
        mock_tflite_module.interpreter.Interpreter = MockTFLiteInterpreter

        with mock.patch.dict(
            "sys.modules",
            {"tflite_runtime": mock_tflite_module, "tflite_runtime.interpreter": mock_tflite_module.interpreter},
        ):
            estimator = DepthEstimator(str(tmp_path), backend="tflite")

        assert estimator.get_backend_name() == "tflite"

    def test_returns_none_when_backend_cleared(self, tmp_path):
        mock_dlr_module = mock.MagicMock()
        mock_dlr_module.DLRModel = MockDLRModel

        with mock.patch.dict("sys.modules", {"dlr": mock_dlr_module}):
            estimator = DepthEstimator(str(tmp_path), backend="dlr")

        estimator._backend = None
        assert estimator.get_backend_name() == "none"


# ---------------------------------------------------------------------------
# Test: postprocess edge cases
# ---------------------------------------------------------------------------


class TestPostprocess:
    """Test the _postprocess static method with various input shapes."""

    def test_postprocess_4d_batched_single_channel(self):
        """Shape (1, H, W, 1) should produce (H, W) output."""
        raw = np.random.rand(1, 64, 64, 1).astype(np.float32) * 10.0
        result = DepthEstimator._postprocess(raw)
        assert result.ndim == 2
        assert result.shape == (64, 64)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_postprocess_3d_batched(self):
        """Shape (1, H, W) should produce (H, W) output."""
        raw = np.random.rand(1, 32, 32).astype(np.float32) * 5.0
        result = DepthEstimator._postprocess(raw)
        assert result.ndim == 2
        assert result.shape == (32, 32)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_postprocess_2d_passthrough(self):
        """Shape (H, W) should pass through and normalize."""
        raw = np.array([[0.0, 5.0], [10.0, 2.5]], dtype=np.float32)
        result = DepthEstimator._postprocess(raw)
        assert result.ndim == 2
        assert result.shape == (2, 2)
        assert np.isclose(result.min(), 0.0)
        assert np.isclose(result.max(), 1.0)

    def test_postprocess_nchw_format(self):
        """Shape (1, 1, H, W) — NCHW single-channel — should produce (H, W)."""
        raw = np.random.rand(1, 1, 48, 48).astype(np.float32) * 3.0
        result = DepthEstimator._postprocess(raw)
        assert result.ndim == 2
        assert result.shape == (48, 48)
        assert result.min() >= 0.0
        assert result.max() <= 1.0


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# Feature: xgo2-ball-grip-calibration, Property 1: Depth estimator output invariant
# ---------------------------------------------------------------------------

import tempfile

from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st


def _random_depth_output_strategy():
    """Strategy that produces random raw depth arrays in various output shapes.

    Covers the shapes handled by DepthEstimator._postprocess:
        - (1, H, W, 1) — batched single-channel (NHWC)
        - (1, H, W)    — batched without channel dim
        - (1, 1, H, W) — batched NCHW single-channel
        - (H, W)        — already 2D
    """
    # Use small spatial dims to keep generation fast
    h_w = st.tuples(
        st.integers(min_value=2, max_value=64),
        st.integers(min_value=2, max_value=64),
    )

    @st.composite
    def _build(draw):
        h, w = draw(h_w)
        shape_choice = draw(st.sampled_from(["nhwc", "nhw", "nchw", "hw"]))
        # Random positive values (postprocess normalises, so range doesn't matter)
        vals = draw(
            st.lists(
                st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
                min_size=h * w,
                max_size=h * w,
            )
        )
        flat = np.array(vals, dtype=np.float32)
        if shape_choice == "nhwc":
            return flat.reshape(1, h, w, 1)
        elif shape_choice == "nhw":
            return flat.reshape(1, h, w)
        elif shape_choice == "nchw":
            return flat.reshape(1, 1, h, w)
        else:
            return flat.reshape(h, w)

    return _build()


class _MockDLRModelForPBT:
    """Mock DLR model whose run() returns a pre-set raw depth array."""

    def __init__(self, raw_depth_output: np.ndarray):
        self._output = raw_depth_output

    def run(self, input_data):
        return [self._output]


# Strategy for random BGR frames of various sizes
_bgr_frame_strategy = st.tuples(
    st.integers(min_value=1, max_value=480),  # height
    st.integers(min_value=1, max_value=640),  # width
).flatmap(
    lambda hw: st.just(
        np.random.randint(0, 256, (hw[0], hw[1], 3), dtype=np.uint8)
    )
)


class TestDepthEstimatorOutputProperty:
    """Property-based test: P1 — Depth estimator output invariant.

    For any valid BGR camera frame (non-empty numpy array with 3 channels),
    DepthEstimator.estimate_depth() SHALL return a 2D numpy array with all
    values in [0.0, 1.0].

    **Validates: Requirements 3.2, 3.3**
    """

    @given(
        frame_hw=st.tuples(
            st.integers(min_value=1, max_value=480),
            st.integers(min_value=1, max_value=640),
        ),
        raw_depth=_random_depth_output_strategy(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
        deadline=None,
    )
    def test_estimate_depth_returns_2d_array_in_unit_range(
        self, frame_hw, raw_depth
    ):
        """estimate_depth() output is always 2D with values in [0.0, 1.0].

        **Validates: Requirements 3.2, 3.3**
        """
        h, w = frame_hw
        frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

        # Use a temporary directory for the model_dir argument
        with tempfile.TemporaryDirectory() as model_dir:
            # Build a DepthEstimator with a mock DLR model
            mock_dlr_module = mock.MagicMock()
            mock_dlr_module.DLRModel = MockDLRModel  # use existing mock for init

            mock_cv2 = mock.MagicMock()
            mock_cv2.resize.return_value = np.zeros(
                (DEPTH_MODEL_INPUT_HEIGHT, DEPTH_MODEL_INPUT_WIDTH, 3),
                dtype=np.uint8,
            )

            with mock.patch.dict(
                "sys.modules", {"dlr": mock_dlr_module, "cv2": mock_cv2}
            ):
                estimator = DepthEstimator(model_dir, backend="dlr")

            # Replace the model with our PBT mock that returns the generated depth
            estimator._model = _MockDLRModelForPBT(raw_depth)

            # Patch cv2 for the preprocess call inside estimate_depth
            with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
                depth_map = estimator.estimate_depth(frame)

        # --- Assertions (the property) ---
        assert isinstance(depth_map, np.ndarray), "Output must be a numpy array"
        assert depth_map.ndim == 2, (
            "Depth map must be 2D, got shape {}".format(depth_map.shape)
        )
        assert depth_map.min() >= 0.0, (
            "All depth values must be >= 0.0, got min={}".format(depth_map.min())
        )
        assert depth_map.max() <= 1.0, (
            "All depth values must be <= 1.0, got max={}".format(depth_map.max())
        )
