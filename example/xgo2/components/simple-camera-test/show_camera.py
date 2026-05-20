"""
Display the XGO2 camera feed on the robot's built-in LCD screen.

Uses the LCD_2inch SPI display driver and OpenCV, matching how the
xgoedu library works internally.

Run on the XGO2 via SSH:
    ssh pi@10.131.141.49 'sudo python ~/show_camera.py'

Press Ctrl+C to stop, or press button 'c' on the robot.
"""

import sys
sys.path.append("/home/pi/cm4-main")

import cv2
import time
import subprocess
import os
import LCD_2inch
import RPi.GPIO as GPIO
from PIL import Image

# --- LCD init ---
display = LCD_2inch.LCD_2inch()
display.Init()
display.clear()

# --- GPIO button init (button c = GPIO 23) ---
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
BUTTON_C = 23
GPIO.setup(BUTTON_C, GPIO.IN, GPIO.PUD_UP)

LCD_WIDTH = 320
LCD_HEIGHT = 240
CAMERA_DEV = "/dev/video0"


def release_camera():
    """Kill any process holding the camera so we can open it."""
    try:
        result = subprocess.run(
            ["fuser", CAMERA_DEV],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        my_pid = str(os.getpid())
        for pid in pids:
            pid = pid.strip().rstrip("m")
            if pid and pid != my_pid:
                print(f"Killing PID {pid} holding {CAMERA_DEV}")
                subprocess.run(["kill", "-9", pid])
        time.sleep(0.5)
    except Exception as e:
        print(f"Warning: could not check camera lock: {e}")


def main():
    release_camera()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LCD_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LCD_HEIGHT)

    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    print("Camera feed running on LCD. Press Ctrl+C or button 'c' to stop.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Ignoring empty camera frame.")
                continue

            # BGR -> RGB, then horizontal flip (matches xgoedu cameraOn)
            b, g, r = cv2.split(frame)
            frame = cv2.merge((r, g, b))
            frame = cv2.flip(frame, 1)

            # Convert to PIL Image and push to LCD
            img = Image.fromarray(frame)
            display.ShowImage(img)

            # Check button 'c' to exit
            if not GPIO.input(BUTTON_C):
                print("Button 'c' pressed, exiting.")
                break
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cap.release()
        display.clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
