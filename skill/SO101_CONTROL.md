---
name: so101-control
description: Operate the physical SO-ARM101 6-axis robot arm via the LeRobot Python API — connect/disconnect, read joint state, capture wrist camera, move to safe poses, test gripper, relax for hand-positioning, and recover from common errors. Use when controlling the real robot directly (no leader teleop), executing scripted motions, or debugging hardware connection issues.
---

# SO-ARM101 Robot Control

End-to-end runbook for direct programmatic control of the SO-ARM101 follower arm using the LeRobot Python API. Designed for **follower-only** workflows (leader arm not connected) where motions are sent as Python dicts of joint targets.

See full code examples and step-by-step scripts in [`example/so101/`](../example/so101/).

## When to use this

- You have a follower SO-ARM101 connected over USB and calibrated.
- You want to send goal joint positions directly (Home, Rest, custom poses) — not teleoperate.
- You need to capture the wrist camera (`icspring`) for VLA model input or debugging.
- You hit a hardware error (port permission, motor disconnect, wrong baud) and need a triage path.

## Prerequisites

- macOS or Linux with the `lerobot` conda environment installed.
- Follower arm calibrated. Calibration JSON typically lives at `~/.cache/huggingface/lerobot/calibration/robots/so101_follower/<robot_id>.json`.
- USB serial port discoverable: macOS exposes it as `/dev/tty.usbmodem*`, Linux as `/dev/ttyACM*` or `/dev/ttyUSB*`.

```bash
# Activate environment (adjust path to your install)
conda activate lerobot

# Confirm port + camera indexes
ls /dev/tty.usbmodem*
python -c "import cv2; \
  [print(i, cv2.VideoCapture(i).isOpened()) for i in range(3)]"
```

## Standard control loop

Every script follows the same lifecycle. **Always disconnect** at the end — the motors stay torqued otherwise and the next connect attempt fails with `Port is busy`.

```python
from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

cfg = SO101FollowerConfig(
    port="/dev/tty.usbmodem5C4C1255691",   # YOUR port
    id="my_awesome_follower_arm",            # YOUR calibrated robot id
)
robot = SO101Follower(cfg)
robot.connect(calibrate=False)   # calibrate=False reuses on-disk calibration

try:
    state = robot.get_observation()
    # joint reading: state["shoulder_pan.pos"], etc.
    # camera image: state["icspring"]  (numpy HxWx3 BGR)
    # ... do work ...
finally:
    robot.disconnect()
```

## Joint name reference

| Joint | Range (deg, normalized) | Notes |
|-------|-------------------------|-------|
| `shoulder_pan.pos`   | -100 to +100 | base rotation |
| `shoulder_lift.pos`  | -100 to +100 | shoulder up/down |
| `elbow_flex.pos`     | -100 to +100 | elbow bend |
| `wrist_flex.pos`     | -100 to +100 | wrist pitch |
| `wrist_roll.pos`     | -100 to +100 | wrist twist |
| `gripper.pos`        | 0 (closed) to ~50 (open) | gripper |

LeRobot normalizes joint values to roughly `[-100, 100]` — these are **not raw degrees**. Use the calibration file as the source of truth.

## Safe poses

Two known-safe poses verified on this hardware:

```python
HOME = {  # arm vertical, wrist neutral, gripper open
    "shoulder_pan.pos": 0.0,
    "shoulder_lift.pos": 0.0,
    "elbow_flex.pos": 0.0,
    "wrist_flex.pos": 0.0,
    "wrist_roll.pos": 0.0,
    "gripper.pos": 30.0,
}

REST = {  # arm folded forward, low profile for storage
    "shoulder_pan.pos": 0.0,
    "shoulder_lift.pos": -90.0,
    "elbow_flex.pos": 90.0,
    "wrist_flex.pos": 0.0,
    "wrist_roll.pos": 0.0,
    "gripper.pos": 0.0,
}
```

## Smooth motion (avoid jerky jumps)

`send_action()` commands the goal instantly — the motors slew at full speed. To get smooth motion, **interpolate in software**:

```python
import time

def smooth_move(robot, target, duration=2.0, steps=40):
    start = robot.get_observation()
    start = {k: start[k] for k in target}
    for i in range(1, steps + 1):
        a = i / steps
        action = {k: start[k] + (target[k] - start[k]) * a for k in target}
        robot.send_action(action)
        time.sleep(duration / steps)
```

40 steps over 2 seconds is a good default. Faster motions risk overshoot and motor stalls.

## Critical pitfalls

- **Port busy after crash**: a previous Python process may still hold the serial port. `pkill -f lerobot` or unplug-replug the USB cable.
- **`calibrate=True` on every connect**: this overwrites your calibration. Always use `calibrate=False` once you have a good calibration on disk.
- **Forgetting `disconnect()`**: motors stay torqued, port stays locked. Wrap every script in `try/finally`.
- **Wrong robot id**: must exactly match the calibration filename (without `.json`). Mismatch causes silent miscalibration — the arm moves to wrong angles.
- **Gripper out of range**: `gripper.pos > 50` jams the mechanism. Stay in `[0, 50]`.
- **Wrist camera index**: USB camera index is **not stable** across reboots on macOS. Always probe with `cv2.VideoCapture(i)` before relying on a hard-coded index.

## Example workflow scripts

Numbered scripts in [`example/so101/device/`](../example/so101/device/) are intended to be run in order, end to end:

1. **`01_read_state.py`** — connect, read joints, disconnect. Smoke test for hardware.
2. **`02_capture_camera.py`** — capture wrist camera frame, save PNG.
3. **`03_move_home.py`** — smooth move to HOME pose.
4. **`04_move_rest.py`** — smooth move to REST pose.
5. **`05_gripper_test.py`** — open/close gripper cycle.
6. **`06_relax.py`** — torque-off all joints so you can hand-position the arm.

The shared helper `device/lib/safe_arm.py` provides `connect_arm()`, `smooth_move()`, and a `safe_session()` context manager that guarantees disconnect on exit.

## Triage cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `[Errno 13] Permission denied: '/dev/ttyACM0'` | Linux user not in `dialout` group | `sudo usermod -aG dialout $USER` then re-login |
| `Port is busy` | Stale Python process or motor torque held | `pkill -f lerobot`, unplug + replug USB |
| Arm jerks / overshoots | Direct `send_action()` jump | Use `smooth_move()` interpolation |
| Joint reads `None` | Calibration file missing or `id` mismatch | Recalibrate or fix `id=` to match JSON filename |
| Camera frame is black | Wrong `cv2.VideoCapture` index | Probe indexes 0–3, pick the wrist camera |
| Motors silent on `send_action` | Robot not connected or torque off | Re-run `robot.connect(calibrate=False)` |

See [`example/so101/specs/troubleshooting.md`](../example/so101/specs/troubleshooting.md) for extended debugging recipes and [`example/so101/specs/python-api.md`](../example/so101/specs/python-api.md) for the full LeRobot API surface used here.
