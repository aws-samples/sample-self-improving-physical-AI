"""
Monocular depth estimation engine for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Supports DLR (Neo-compiled) and TFLite backends for depth estimation.
Follows the same DLR-first/TFLite-fallback pattern as InferenceEngine
in vision_inference.py.

Requirements: 3.1-3.6
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Input dimensions for the depth model (MiDaS small)
DEPTH_MODEL_INPUT_WIDTH = 256
DEPTH_MODEL_INPUT_HEIGHT = 256


class DepthEstimator:
    """Monocular depth estimation engine with multi-backend support.

    Supports two backends:
        - "dlr": Neo-compiled model via DLR runtime
        - "tflite": TFLite model via tflite_runtime (or tensorflow.lite)

    When backend="auto", tries DLR first, then falls back to TFLite.

    Args:
        model_dir: Path to directory containing depth model files.
        backend: One of "auto", "dlr", "tflite".

    Raises:
        RuntimeError: If no model can be loaded.
    """

    def __init__(
        self,
        model_dir: str,
        backend: str = "auto",
    ) -> None:
        self._model_dir = model_dir
        self._backend = None  # type: Optional[str]
        self._model = None  # DLR model or TFLite interpreter

        # Initialize the requested backend
        if backend == "dlr":
            self._init_dlr(model_dir)
        elif backend == "tflite":
            self._init_tflite(model_dir)
        elif backend == "auto":
            self._init_auto(model_dir)
        else:
            raise RuntimeError(
                "Unknown backend '{}'. Choose from: auto, dlr, tflite".format(
                    backend
                )
            )

    # ------------------------------------------------------------------
    # Backend initialization
    # ------------------------------------------------------------------

    def _init_dlr(self, model_dir: str) -> None:
        """Initialize DLR backend for Neo-compiled depth models."""
        try:
            from dlr import DLRModel  # type: ignore[import-untyped]

            self._model = DLRModel(model_dir, "cpu")
            self._backend = "dlr"
            logger.info("DLR depth backend loaded from %s", model_dir)
        except Exception as exc:
            raise RuntimeError(
                "Failed to load DLR depth model from {}: {}".format(
                    model_dir, exc
                )
            ) from exc

    def _init_tflite(self, model_dir: str) -> None:
        """Initialize TFLite backend.

        Tries tflite_runtime first, then falls back to tensorflow.lite.
        Looks for a .tflite file in model_dir.
        """
        tflite_path = self._find_tflite_model(model_dir)
        if tflite_path is None:
            raise RuntimeError(
                "No .tflite depth model file found in {}".format(model_dir)
            )

        interpreter = self._create_tflite_interpreter(tflite_path)
        interpreter.allocate_tensors()
        self._model = interpreter
        self._backend = "tflite"
        logger.info("TFLite depth backend loaded from %s", tflite_path)

    def _init_auto(self, model_dir: str) -> None:
        """Auto-detect backend: try DLR first, fall back to TFLite."""
        # Try DLR
        try:
            self._init_dlr(model_dir)
            return
        except Exception as dlr_exc:
            logger.warning(
                "DLR depth backend failed, falling back to TFLite: %s",
                dlr_exc,
            )

        # Try TFLite
        try:
            self._init_tflite(model_dir)
            return
        except Exception as tflite_exc:
            raise RuntimeError(
                "No depth inference backend available. "
                "DLR failed, TFLite also failed: {}".format(tflite_exc)
            ) from tflite_exc

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _find_tflite_model(model_dir: str) -> Optional[str]:
        """Find the first .tflite file in model_dir."""
        if not os.path.isdir(model_dir):
            return None
        for fname in sorted(os.listdir(model_dir)):
            if fname.endswith(".tflite"):
                return os.path.join(model_dir, fname)
        return None

    @staticmethod
    def _create_tflite_interpreter(model_path: str):
        """Create a TFLite interpreter, trying tflite_runtime first."""
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore[import-untyped]

            return Interpreter(model_path=model_path)
        except ImportError:
            pass

        try:
            import tensorflow as tf  # type: ignore[import-untyped]

            return tf.lite.Interpreter(model_path=model_path)
        except ImportError:
            raise RuntimeError(
                "Neither tflite_runtime nor tensorflow is installed"
            )

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Resize and normalize a camera frame for depth model input.

        Args:
            frame: BGR numpy array from OpenCV with shape (H, W, 3).

        Returns:
            Numpy array with shape (1, DEPTH_MODEL_INPUT_HEIGHT,
            DEPTH_MODEL_INPUT_WIDTH, 3) and values in [0.0, 1.0].
        """
        import cv2  # type: ignore[import-untyped]

        resized = cv2.resize(
            frame, (DEPTH_MODEL_INPUT_WIDTH, DEPTH_MODEL_INPUT_HEIGHT)
        )
        normalized = resized.astype(np.float32) / 255.0
        batched = np.expand_dims(normalized, axis=0)
        return batched

    # ------------------------------------------------------------------
    # Depth estimation
    # ------------------------------------------------------------------

    def estimate_depth(self, frame: np.ndarray) -> np.ndarray:
        """Run depth inference on a camera frame.

        Args:
            frame: BGR numpy array from OpenCV, typically (240, 320, 3).

        Returns:
            2D numpy array (H, W) with depth values in [0.0, 1.0].
            Higher values represent closer objects.
        """
        if self._backend == "dlr":
            return self._estimate_dlr(frame)
        elif self._backend == "tflite":
            return self._estimate_tflite(frame)
        else:
            raise RuntimeError("No depth backend initialized")

    def _estimate_dlr(self, frame: np.ndarray) -> np.ndarray:
        """Run depth estimation using DLR backend."""
        preprocessed = self._preprocess(frame)
        outputs = self._model.run(preprocessed)

        # DLR returns a list of output arrays; take the first one
        raw_depth = outputs[0]
        return self._postprocess(raw_depth)

    def _estimate_tflite(self, frame: np.ndarray) -> np.ndarray:
        """Run depth estimation using TFLite backend."""
        import cv2  # type: ignore[import-untyped]

        interpreter = self._model
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()

        # Resize frame to model input dimensions
        resized = cv2.resize(
            frame, (DEPTH_MODEL_INPUT_WIDTH, DEPTH_MODEL_INPUT_HEIGHT)
        )

        # Match the model's expected input dtype
        input_dtype = input_details[0]["dtype"]
        if input_dtype == np.uint8:
            input_data = np.expand_dims(resized.astype(np.uint8), axis=0)
        else:
            input_data = np.expand_dims(
                resized.astype(np.float32) / 255.0, axis=0
            )

        interpreter.set_tensor(input_details[0]["index"], input_data)
        interpreter.invoke()

        raw_depth = interpreter.get_tensor(output_details[0]["index"])
        return self._postprocess(raw_depth)

    # ------------------------------------------------------------------
    # Postprocessing
    # ------------------------------------------------------------------

    @staticmethod
    def _postprocess(raw_depth: np.ndarray) -> np.ndarray:
        """Normalize raw depth output to a 2D array with values in [0.0, 1.0].

        Handles various output shapes:
            - (1, H, W, 1) — batched single-channel
            - (1, H, W) — batched without channel dim
            - (1, 1, H, W) — batched NCHW single-channel
            - (H, W) — already 2D

        Returns:
            2D numpy float32 array with values clamped to [0.0, 1.0].
        """
        depth = raw_depth.copy().astype(np.float32)

        # Squeeze batch and channel dimensions to get 2D
        depth = np.squeeze(depth)

        # If still >2D after squeeze (e.g. multi-channel), take first channel
        while depth.ndim > 2:
            depth = depth[0]

        # Normalize to [0.0, 1.0]
        d_min = depth.min()
        d_max = depth.max()
        if d_max - d_min > 1e-8:
            depth = (depth - d_min) / (d_max - d_min)
        else:
            # Constant depth map — return zeros
            depth = np.zeros_like(depth)

        return np.clip(depth, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_backend_name(self) -> str:
        """Return the name of the active depth inference backend.

        Returns:
            One of "dlr", "tflite", or "none".
        """
        if self._backend is None:
            return "none"
        return self._backend
