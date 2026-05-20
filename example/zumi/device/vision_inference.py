"""
Device-side inference engine for object detection on the Zumi robot.

Loads a TFLite or Neo-compiled (DLR) model and runs object detection
on camera frames. Returns bounding boxes, class labels, and confidence
scores as DetectionResult objects.

Python 3.5.3 compatible — no f-strings, no dataclasses, no type hints.
"""

import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DetectionResult(object):
    """A single object detection result."""

    def __init__(self, class_label, confidence, bounding_box):
        # class_label: str — e.g. "person", "cup"
        # confidence: float 0.0-1.0
        # bounding_box: dict with keys top, left, bottom, right (floats 0.0-1.0)
        self.class_label = class_label
        self.confidence = confidence
        self.bounding_box = bounding_box

    def __repr__(self):
        return (
            "DetectionResult(label=%r, confidence=%.3f, bbox=%r)"
            % (self.class_label, self.confidence, self.bounding_box)
        )


class InferenceEngine(object):
    """Loads a vision model and runs object detection on camera frames.

    Tries DLR (Neo-compiled) first, falls back to TFLite.
    Raises RuntimeError if no model can be loaded or labels file is missing.
    """

    DEFAULT_INPUT_SIZE = 128  # fallback if model shape cannot be read

    def __init__(self, model_dir, confidence_threshold=0.5):
        # model_dir: str — path to directory containing model files
        # confidence_threshold: float — minimum confidence to include a detection
        self._model_dir = model_dir
        self._confidence_threshold = confidence_threshold
        self._backend = None  # "dlr" or "tflite"
        self._dlr_model = None
        self._tflite_interpreter = None
        self._tflite_input_details = None
        self._tflite_output_details = None
        self._labels = []
        self._input_height = self.DEFAULT_INPUT_SIZE
        self._input_width = self.DEFAULT_INPUT_SIZE
        self._input_dtype = np.float32
        self._input_is_quantized = False

        # Try loading model backends
        self._load_model()

        # Read model input shape dynamically
        self._read_input_shape()

        # Load label map
        self._load_labels()

    def _load_model(self):
        """Try DLR first, fall back to TFLite. Raise RuntimeError if both fail."""
        dlr_error = None
        tflite_error = None

        # Attempt DLR (Neo-compiled model)
        try:
            import dlr
            self._dlr_model = dlr.DLRModel(self._model_dir, "cpu")
            self._backend = "dlr"
            logger.info("Loaded Neo-compiled model via DLR from %s", self._model_dir)
            return
        except Exception as e:
            dlr_error = e
            logger.warning(
                "Failed to load DLR model from %s: %s. "
                "Falling back to TFLite.",
                self._model_dir, str(e)
            )

        # Attempt TFLite
        tflite_path = os.path.join(self._model_dir, "model.tflite")
        try:
            tflite_interp_class = None
            # Try tflite_runtime first (preferred, lightweight)
            try:
                import tflite_runtime.interpreter as tflite_mod
                tflite_interp_class = tflite_mod.Interpreter
            except ImportError:
                pass

            # Try tensorflow.lite (TF 2.x style)
            if tflite_interp_class is None:
                try:
                    import tensorflow as tf
                    tflite_interp_class = tf.lite.Interpreter
                except (ImportError, AttributeError):
                    pass

            # Try tensorflow.contrib.lite (TF 1.x style)
            if tflite_interp_class is None:
                try:
                    from tensorflow.contrib.lite.python import lite
                    tflite_interp_class = lite.Interpreter
                except (ImportError, AttributeError):
                    pass

            if tflite_interp_class is None:
                raise ImportError("No TFLite interpreter available")

            self._tflite_interpreter = tflite_interp_class(model_path=tflite_path)
            self._tflite_interpreter.allocate_tensors()
            self._tflite_input_details = self._tflite_interpreter.get_input_details()
            self._tflite_output_details = self._tflite_interpreter.get_output_details()
            self._backend = "tflite"
            logger.info("Loaded TFLite model from %s", tflite_path)
            return
        except Exception as e:
            tflite_error = e
            logger.error(
                "Failed to load TFLite model from %s: %s",
                tflite_path, str(e)
            )

        raise RuntimeError(
            "Could not load any model from %s. "
            "DLR error: %s. TFLite error: %s."
            % (self._model_dir, str(dlr_error), str(tflite_error))
        )

    def _read_input_shape(self):
        """Read the model's actual input shape and dtype dynamically.

        Sets _input_height, _input_width, _input_dtype, and
        _input_is_quantized based on the loaded model.
        """
        if self._backend == "tflite" and self._tflite_input_details:
            shape = self._tflite_input_details[0]["shape"]
            # Shape is typically [batch, height, width, channels]
            if len(shape) == 4:
                self._input_height = int(shape[1])
                self._input_width = int(shape[2])
            self._input_dtype = self._tflite_input_details[0]["dtype"]
            self._input_is_quantized = (self._input_dtype == np.uint8)
            logger.info(
                "Model input: %dx%d, dtype=%s, quantized=%s",
                self._input_height, self._input_width,
                str(self._input_dtype), str(self._input_is_quantized)
            )
        else:
            # DLR or fallback — use default
            logger.info(
                "Using default input size: %dx%d",
                self._input_height, self._input_width
            )

    def _load_labels(self):
        """Load label map from labels.txt. Raise RuntimeError if missing."""
        labels_path = os.path.join(self._model_dir, "labels.txt")
        if not os.path.isfile(labels_path):
            raise RuntimeError(
                "Labels file not found: %s" % labels_path
            )
        with open(labels_path, "r") as f:
            self._labels = [line.strip() for line in f.readlines()]
        logger.info(
            "Loaded %d labels from %s", len(self._labels), labels_path
        )

    def detect(self, frame):
        """Run object detection on a camera frame (numpy array, BGR).

        Returns a list of DetectionResult objects above the confidence threshold.
        Returns an empty list if the frame is None or empty.
        """
        if frame is None or frame.size == 0:
            logger.warning("Received None or empty frame, returning no detections")
            return []

        # Preprocess
        input_data = self._preprocess(frame)

        # Run inference
        if self._backend == "dlr":
            output_tensors = self._run_dlr(input_data)
        else:
            output_tensors = self._run_tflite(input_data)

        # Parse and filter results
        return self._parse_detections(output_tensors, self._confidence_threshold)

    def _preprocess(self, frame):
        """Resize frame to model input size and prepare for inference.

        Dynamically uses the model's actual input shape and dtype.

        Args:
            frame: numpy array (H, W, 3), BGR format, uint8 values 0-255.

        Returns:
            numpy array with shape (1, H, W, 3) matching model input requirements.
        """
        resized = cv2.resize(
            frame,
            (self._input_width, self._input_height)
        )
        if self._input_is_quantized:
            # Quantized model expects uint8 input (0-255)
            batched = np.expand_dims(resized.astype(np.uint8), axis=0)
        else:
            # Float model expects normalized float32 input (0.0-1.0)
            normalized = resized.astype(np.float32) / 255.0
            batched = np.expand_dims(normalized, axis=0)
        return batched

    def _run_dlr(self, input_data):
        """Run inference via DLR backend.

        Returns a list of output tensors.
        """
        output = self._dlr_model.run(input_data)
        return output

    def _run_tflite(self, input_data):
        """Run inference via TFLite backend.

        Returns a list of output tensors in standard SSD order:
        [bounding_boxes, class_ids, scores, detection_count].
        """
        input_index = self._tflite_input_details[0]["index"]
        self._tflite_interpreter.set_tensor(input_index, input_data)
        self._tflite_interpreter.invoke()

        outputs = []
        for detail in self._tflite_output_details:
            tensor = self._tflite_interpreter.get_tensor(detail["index"])
            outputs.append(tensor)
        return outputs

    def _parse_detections(self, output_tensors, confidence_threshold):
        """Parse raw model output tensors into DetectionResult objects.

        Standard SSD detection model outputs:
            tensor 0: bounding boxes [1, N, 4] (top, left, bottom, right)
            tensor 1: class IDs [1, N]
            tensor 2: confidence scores [1, N]
            tensor 3: detection count [1] or scalar

        Args:
            output_tensors: list of numpy arrays from the model.
            confidence_threshold: float, minimum confidence to include.

        Returns:
            list of DetectionResult objects.
        """
        if len(output_tensors) < 4:
            logger.error(
                "Expected 4 output tensors, got %d. Returning no detections.",
                len(output_tensors)
            )
            return []

        boxes = np.squeeze(output_tensors[0])     # shape (N, 4)
        class_ids = np.squeeze(output_tensors[1])  # shape (N,)
        scores = np.squeeze(output_tensors[2])     # shape (N,)
        count_raw = output_tensors[3]

        # detection count may be scalar or array
        if hasattr(count_raw, "flatten"):
            count = int(count_raw.flatten()[0])
        else:
            count = int(count_raw)

        # Handle edge case where squeeze reduces to scalar for single detection
        if boxes.ndim == 1:
            boxes = np.expand_dims(boxes, axis=0)
        if class_ids.ndim == 0:
            class_ids = np.expand_dims(class_ids, axis=0)
        if scores.ndim == 0:
            scores = np.expand_dims(scores, axis=0)

        results = []
        num_detections = min(count, len(scores))

        for i in range(num_detections):
            score = float(scores[i])
            if score < confidence_threshold:
                continue

            class_id = int(class_ids[i])
            if 0 <= class_id < len(self._labels):
                label = self._labels[class_id]
            else:
                label = "unknown_%d" % class_id

            box = boxes[i]
            bounding_box = {
                "top": float(np.clip(box[0], 0.0, 1.0)),
                "left": float(np.clip(box[1], 0.0, 1.0)),
                "bottom": float(np.clip(box[2], 0.0, 1.0)),
                "right": float(np.clip(box[3], 0.0, 1.0)),
            }

            results.append(DetectionResult(
                class_label=label,
                confidence=score,
                bounding_box=bounding_box,
            ))

        return results

    def get_backend_name(self):
        """Return 'dlr' or 'tflite' indicating which runtime is active."""
        return self._backend
