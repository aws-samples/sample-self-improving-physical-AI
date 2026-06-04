"""Capture a single frame from the wrist-mounted USB camera.

By default reads from OpenCV index 0 (the icspring camera shipped with the
SO-ARM101 kit on macOS). Override with the SO101_CAMERA_INDEX env var.

Saves the result to /tmp/so101_wrist.jpg.

macOS note: the *terminal application* that launched this script needs
Camera permission in System Settings. The Python binary is irrelevant.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make `lib.safe_arm` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402

from lib.safe_arm import camera_index  # noqa: E402

OUTPUT = Path("/tmp/so101_wrist.jpg")


def main() -> int:
    idx = camera_index()
    print(f"[1/3] Opening OpenCV camera index {idx} ...")
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        print(f"      ! could not open camera index {idx}")
        print("      try: SO101_CAMERA_INDEX=1 python 02_capture_camera.py")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Warm up — first few frames are often dark while auto-exposure ramps.
    print("[2/3] Warming up auto-exposure ...")
    for _ in range(5):
        cap.read()
        time.sleep(0.05)

    ok, frame = cap.read()
    if not ok or frame is None:
        print("      ! frame capture failed")
        cap.release()
        return 1

    h, w = frame.shape[:2]
    brightness = float(frame.mean())
    cv2.imwrite(str(OUTPUT), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    cap.release()

    print(f"[3/3] Saved {w}x{h} frame, mean brightness {brightness:.1f}")
    print(f"      file: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
