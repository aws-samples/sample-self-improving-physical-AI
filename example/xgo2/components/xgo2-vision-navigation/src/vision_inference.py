"""
Vision inference engine for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Supports DLR (Neo-compiled), TFLite, and xgoedu backends for object detection.

Requirements: 2.1-2.6, 4.1-4.7, 13.1, 13.2
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Input dimensions for MobileNet V2 SSD
MODEL_INPUT_WIDTH = 300
MODEL_INPUT_HEIGHT = 300


@dataclass
class DetectionResult:
    """A single object detection result.

    Attributes:
        class_label: Detected object class name (e.g. "person", "cup").
        confidence: Detection confidence score, 0.0 to 1.0.
        bounding_box: Dict with keys "top", "left", "bottom", "right"
            as floats in [0.0, 1.0] relative to frame dimensions.
    """

    class_label: str
    confidence: float
    bounding_box: Dict[str, float]

    def to_dict(self) -> Dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "class_label": self.class_label,
            "confidence": self.confidence,
            "bounding_box": dict(self.bounding_box),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "DetectionResult":
        """Deserialize from a dict."""
        return cls(
            class_label=d["class_label"],
            confidence=d["confidence"],
            bounding_box=dict(d["bounding_box"]),
        )


class InferenceEngine:
    """Object detection inference engine with multi-backend support.

    Supports three backends:
        - "dlr": Neo-compiled model via DLR runtime
        - "tflite": TFLite model via tflite_runtime (or tensorflow.lite)
        - "xgoedu": Built-in XGOEDU detectors (yoloFast, face_detect, etc.)

    When backend="auto", tries DLR first, then falls back to TFLite.

    Args:
        model_dir: Path to directory containing model files and labels.txt.
        confidence_threshold: Minimum confidence to include a detection (default 0.5).
        backend: One of "auto", "dlr", "tflite", "xgoedu".

    Raises:
        RuntimeError: If no model can be loaded or labels.txt is missing.
    """

    def __init__(
        self,
        model_dir: str,
        confidence_threshold: float = 0.5,
        backend: str = "auto",
    ) -> None:
        self._model_dir = model_dir
        self._confidence_threshold = confidence_threshold
        self._backend: Optional[str] = None
        self._model = None  # DLR or TFLite interpreter
        self._edu = None  # XGOEDU instance
        self._labels: List[str] = []

        # Load labels first — required for all backends
        self._labels = self._load_labels(model_dir)

        # Initialize the requested backend
        if backend == "xgoedu":
            self._init_xgoedu()
        elif backend == "dlr":
            self._init_dlr(model_dir)
        elif backend == "tflite":
            self._init_tflite(model_dir)
        elif backend == "auto":
            self._init_auto(model_dir)
        else:
            raise RuntimeError(
                "Unknown backend '{}'. Choose from: auto, dlr, tflite, xgoedu".format(
                    backend
                )
            )

    # ------------------------------------------------------------------
    # Label loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_labels(model_dir: str) -> List[str]:
        """Load class labels from {model_dir}/labels.txt.

        Each line is one class name, zero-indexed.
        Raises RuntimeError if the file is missing or empty.
        """
        labels_path = os.path.join(model_dir, "labels.txt")
        if not os.path.isfile(labels_path):
            raise RuntimeError(
                "Labels file not found: {}".format(labels_path)
            )

        labels: List[str] = []
        with open(labels_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    labels.append(stripped)

        if not labels:
            raise RuntimeError(
                "Labels file is empty: {}".format(labels_path)
            )

        logger.info("Loaded %d labels from %s", len(labels), labels_path)
        return labels

    # ------------------------------------------------------------------
    # Backend initialization
    # ------------------------------------------------------------------

    def _init_dlr(self, model_dir: str) -> None:
        """Initialize DLR backend for Neo-compiled models."""
        try:
            from dlr import DLRModel  # type: ignore[import-untyped]

            self._model = DLRModel(model_dir, "cpu")
            self._backend = "dlr"
            logger.info("DLR backend loaded from %s", model_dir)
        except Exception as exc:
            raise RuntimeError(
                "Failed to load DLR model from {}: {}".format(model_dir, exc)
            ) from exc

    def _init_tflite(self, model_dir: str) -> None:
        """Initialize TFLite backend.

        Tries tflite_runtime first, then falls back to tensorflow.lite.
        Looks for a .tflite file in model_dir.
        """
        tflite_path = self._find_tflite_model(model_dir)
        if tflite_path is None:
            raise RuntimeError(
                "No .tflite model file found in {}".format(model_dir)
            )

        interpreter = self._create_tflite_interpreter(tflite_path)
        interpreter.allocate_tensors()
        self._model = interpreter
        self._backend = "tflite"
        logger.info("TFLite backend loaded from %s", tflite_path)

    def _init_xgoedu(self) -> None:
        """Initialize XGOEDU backend for built-in detectors."""
        try:
            from xgoedu import XGOEDU  # type: ignore[import-untyped]

            self._edu = XGOEDU()
            self._backend = "xgoedu"
            logger.info("XGOEDU backend initialized")
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize XGOEDU: {}".format(exc)
            ) from exc

    def _init_auto(self, model_dir: str) -> None:
        """Auto-detect backend: try DLR first, fall back to TFLite."""
        # Try DLR
        try:
            self._init_dlr(model_dir)
            return
        except Exception as dlr_exc:
            logger.warning(
                "DLR backend failed, falling back to TFLite: %s", dlr_exc
            )

        # Try TFLite
        try:
            self._init_tflite(model_dir)
            return
        except Exception as tflite_exc:
            raise RuntimeError(
                "No inference backend available. "
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

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Resize and normalize a camera frame for model input.

        Args:
            frame: BGR numpy array from OpenCV with shape (H, W, 3).

        Returns:
            Numpy array with shape (1, 300, 300, 3) and values in [0.0, 1.0].
        """
        import cv2  # type: ignore[import-untyped]

        resized = cv2.resize(
            frame, (MODEL_INPUT_WIDTH, MODEL_INPUT_HEIGHT)
        )
        normalized = resized.astype(np.float32) / 255.0
        batched = np.expand_dims(normalized, axis=0)
        return batched

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self, frame: Optional[np.ndarray]) -> List[DetectionResult]:
        """Run object detection on a camera frame.

        Runs the ML model first, then appends color-based detections
        for solid-colored objects (e.g. red ball) that the COCO model
        cannot recognize.

        Args:
            frame: BGR numpy array from OpenCV, or None.

        Returns:
            List of DetectionResult objects with confidence >= threshold.
            Returns empty list for None/empty frames or on error.
        """
        if frame is None or frame.size == 0:
            logger.warning("Received None or empty frame, returning no detections")
            return []

        detections = []  # type: List[DetectionResult]

        # Run ML model
        try:
            if self._backend == "xgoedu":
                detections = self._detect_xgoedu(frame)
            elif self._backend == "dlr":
                detections = self._detect_dlr(frame)
            elif self._backend == "tflite":
                detections = self._detect_tflite(frame)
            else:
                logger.error("No backend initialized")
        except Exception:
            logger.exception("Inference failed")

        # Run color-based detection as supplement
        try:
            color_dets = self._detect_by_color(frame)
            detections.extend(color_dets)
        except Exception:
            pass

        return detections

    def _detect_dlr(self, frame: np.ndarray) -> List[DetectionResult]:
        """Run detection using DLR backend."""
        preprocessed = self.preprocess(frame)
        outputs = self._model.run(preprocessed)
        return self._parse_ssd_outputs(outputs)

    def _detect_tflite(self, frame: np.ndarray) -> List[DetectionResult]:
        """Run detection using TFLite backend."""
        import cv2  # type: ignore[import-untyped]

        interpreter = self._model
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()

        # Resize frame to model input dimensions
        resized = cv2.resize(frame, (MODEL_INPUT_WIDTH, MODEL_INPUT_HEIGHT))

        # Match the model's expected input dtype
        input_dtype = input_details[0]["dtype"]
        if input_dtype == np.uint8:
            # Quantized model — keep as uint8 (0-255)
            input_data = np.expand_dims(resized.astype(np.uint8), axis=0)
        else:
            # Float model — normalize to [0.0, 1.0]
            input_data = np.expand_dims(
                resized.astype(np.float32) / 255.0, axis=0
            )

        interpreter.set_tensor(input_details[0]["index"], input_data)
        interpreter.invoke()

        # Standard SSD output order: boxes, classes, scores, count
        boxes = interpreter.get_tensor(output_details[0]["index"])    # [1, N, 4]
        classes = interpreter.get_tensor(output_details[1]["index"])  # [1, N]
        scores = interpreter.get_tensor(output_details[2]["index"])   # [1, N]
        count = interpreter.get_tensor(output_details[3]["index"])    # [1]

        outputs = [boxes, classes, scores, count]
        return self._parse_ssd_outputs(outputs)

    def _detect_xgoedu(self, frame: np.ndarray) -> List[DetectionResult]:
        """Run detection using XGOEDU built-in yoloFast detector.

        The xgoedu yoloFast returns a list of dicts with detection info.
        """
        try:
            results = self._edu.yoloFast(frame)
            if not results:
                return []

            detections: List[DetectionResult] = []
            for item in results:
                confidence = float(item.get("confidence", 0.0))
                if confidence < self._confidence_threshold:
                    continue

                label = str(item.get("class", "unknown"))
                bbox = item.get("bbox", {})

                detection = DetectionResult(
                    class_label=label,
                    confidence=confidence,
                    bounding_box={
                        "top": float(bbox.get("top", 0.0)),
                        "left": float(bbox.get("left", 0.0)),
                        "bottom": float(bbox.get("bottom", 1.0)),
                        "right": float(bbox.get("right", 1.0)),
                    },
                )
                detections.append(detection)

            return detections
        except Exception:
            logger.exception("XGOEDU detection failed")
            return []

    # ------------------------------------------------------------------
    # Color-based detection (supplement for solid-colored objects)
    # ------------------------------------------------------------------

    # Minimum contour area in pixels to count as a detection
    _COLOR_MIN_AREA = 300

    # HSV ranges for colors we want to detect.
    # Each entry: (label, [(lower_hsv, upper_hsv), ...])
    _COLOR_RANGES = [
        ("red_ball", [
            (np.array([0, 80, 80]), np.array([15, 255, 255])),
            (np.array([165, 80, 80]), np.array([180, 255, 255])),
        ]),
    ]

    def _detect_by_color(self, frame: np.ndarray) -> List[DetectionResult]:
        """Detect solid-colored objects using HSV color segmentation.

        Finds contours of specific colors and returns them as
        DetectionResult objects. Useful for objects the COCO model
        cannot recognize (e.g. a plain red ball).

        Args:
            frame: BGR numpy array from OpenCV.

        Returns:
            List of DetectionResult for color-detected objects.
        """
        import cv2  # type: ignore[import-untyped]

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w = frame.shape[:2]
        detections = []  # type: List[DetectionResult]

        for label, ranges in self._COLOR_RANGES:
            # Build combined mask for all HSV ranges of this color
            mask = np.zeros((h, w), dtype=np.uint8)
            for lower, upper in ranges:
                mask = mask | cv2.inRange(hsv, lower, upper)

            # Clean up noise
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            # Find contours
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self._COLOR_MIN_AREA:
                    continue

                # Compute circularity — balls should be roughly circular
                perimeter = cv2.arcLength(contour, True)
                if perimeter == 0:
                    continue
                circularity = 4 * 3.14159 * area / (perimeter * perimeter)
                if circularity < 0.5:
                    continue  # Not circular enough

                x, y, cw, ch = cv2.boundingRect(contour)

                # Confidence based on area fraction and circularity
                area_fraction = area / (h * w)
                confidence = min(0.95, 0.5 + area_fraction * 10 + circularity * 0.3)

                if confidence < self._confidence_threshold:
                    continue

                detections.append(DetectionResult(
                    class_label=label,
                    confidence=confidence,
                    bounding_box={
                        "top": float(y) / h,
                        "left": float(x) / w,
                        "bottom": float(y + ch) / h,
                        "right": float(x + cw) / w,
                    },
                ))

        return detections

    # ------------------------------------------------------------------
    # SSD output parsing (shared by DLR and TFLite)
    # ------------------------------------------------------------------

    def _parse_ssd_outputs(
        self, outputs: List[np.ndarray]
    ) -> List[DetectionResult]:
        """Parse standard SSD model output tensors into DetectionResult list.

        Expected output format:
            outputs[0]: bounding boxes [1, N, 4] — (top, left, bottom, right)
            outputs[1]: class IDs [1, N]
            outputs[2]: confidence scores [1, N]
            outputs[3]: detection count [1]

        Returns:
            Filtered list of DetectionResult objects above confidence threshold.
        """
        try:
            boxes = np.squeeze(outputs[0])     # (N, 4)
            classes = np.squeeze(outputs[1])    # (N,)
            scores = np.squeeze(outputs[2])     # (N,)
            count_raw = outputs[3]

            # Handle scalar or array count
            if isinstance(count_raw, np.ndarray):
                num_detections = int(np.squeeze(count_raw))
            else:
                num_detections = int(count_raw)

            # Handle single-detection edge case (squeeze collapses dimensions)
            if boxes.ndim == 1:
                boxes = np.expand_dims(boxes, axis=0)
            if classes.ndim == 0:
                classes = np.expand_dims(classes, axis=0)
            if scores.ndim == 0:
                scores = np.expand_dims(scores, axis=0)

            num_detections = min(num_detections, len(scores))

        except (IndexError, ValueError) as exc:
            logger.error("Unexpected model output format: %s", exc)
            return []

        detections: List[DetectionResult] = []
        for i in range(num_detections):
            confidence = float(scores[i])
            if confidence < self._confidence_threshold:
                continue

            class_id = int(classes[i])
            if 0 <= class_id < len(self._labels):
                label = self._labels[class_id]
            else:
                label = "class_{}".format(class_id)

            box = boxes[i]
            detection = DetectionResult(
                class_label=label,
                confidence=confidence,
                bounding_box={
                    "top": float(np.clip(box[0], 0.0, 1.0)),
                    "left": float(np.clip(box[1], 0.0, 1.0)),
                    "bottom": float(np.clip(box[2], 0.0, 1.0)),
                    "right": float(np.clip(box[3], 0.0, 1.0)),
                },
            )
            detections.append(detection)

        return detections

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_backend_name(self) -> str:
        """Return the name of the active inference backend.

        Returns:
            One of "dlr", "tflite", or "xgoedu".
        """
        if self._backend is None:
            return "none"
        return self._backend
