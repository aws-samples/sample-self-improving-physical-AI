"""
Hardware inference test script for Zumi Pi Zero W.

Loads the model via InferenceEngine, captures a camera frame,
runs detection, and prints results with timing.

Usage (on device):
    python3 /home/pi/zumi-iot/test_inference_hw.py

Python 3.5.3 compatible.
"""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("inference-test")

# Add the zumi-iot directory to path so we can import our modules
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

MODEL_DIR = "/home/pi/models"


def main():
    log.info("=== Inference Hardware Test ===")

    # 1. Check model directory
    if not os.path.isdir(MODEL_DIR):
        log.error("Model directory not found: %s", MODEL_DIR)
        sys.exit(1)

    log.info("Model directory contents:")
    for f in os.listdir(MODEL_DIR):
        fpath = os.path.join(MODEL_DIR, f)
        size = os.path.getsize(fpath) if os.path.isfile(fpath) else 0
        log.info("  %s (%d bytes)", f, size)

    # 2. Load inference engine
    log.info("Loading InferenceEngine from %s ...", MODEL_DIR)
    t0 = time.time()
    try:
        from vision_inference import InferenceEngine
        engine = InferenceEngine(MODEL_DIR, confidence_threshold=0.3)
    except Exception as e:
        log.error("Failed to load InferenceEngine: %s", e)
        sys.exit(1)
    load_time = time.time() - t0
    log.info("InferenceEngine loaded in %.2f seconds", load_time)
    log.info("Backend: %s", engine.get_backend_name())

    # 3. Initialize camera
    log.info("Initializing camera (320x240)...")
    try:
        from zumi.util.camera import Camera
        cam = Camera(320, 240)
        cam.start_camera()
        time.sleep(2)  # sensor warmup
    except Exception as e:
        log.error("Camera init failed: %s", e)
        sys.exit(1)
    log.info("Camera ready")

    # 4. Capture frame
    log.info("Capturing frame...")
    try:
        frame = cam.capture()
    except Exception as e:
        log.error("Capture failed: %s", e)
        cam.close()
        sys.exit(1)

    if frame is None:
        log.error("Captured frame is None")
        cam.close()
        sys.exit(1)

    log.info("Frame shape: %s, dtype: %s", str(frame.shape), str(frame.dtype))

    # 5. Run inference with timing
    log.info("Running inference...")
    t0 = time.time()
    try:
        detections = engine.detect(frame)
    except Exception as e:
        log.error("Inference failed: %s", e)
        cam.close()
        sys.exit(1)
    inference_time = time.time() - t0
    log.info("Inference completed in %.3f seconds", inference_time)

    # 6. Print results
    log.info("Detections: %d", len(detections))
    for i, det in enumerate(detections):
        log.info(
            "  [%d] label=%s confidence=%.3f bbox=%s",
            i, det.class_label, det.confidence, str(det.bounding_box)
        )

    # 7. Check timing requirement (< 2 seconds)
    if inference_time < 2.0:
        log.info("PASS: Inference time %.3fs < 2.0s requirement", inference_time)
    else:
        log.warning(
            "WARN: Inference time %.3fs exceeds 2.0s requirement",
            inference_time
        )

    # 8. Cleanup
    try:
        cam.close()
    except Exception:
        pass

    log.info("=== Inference test complete ===")
    log.info("Summary:")
    log.info("  Backend: %s", engine.get_backend_name())
    log.info("  Model load time: %.2fs", load_time)
    log.info("  Inference time: %.3fs", inference_time)
    log.info("  Detections: %d", len(detections))


if __name__ == "__main__":
    main()
