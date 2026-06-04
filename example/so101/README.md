# SO-ARM101 Examples

Six minimal scripts that exercise the [SO-ARM101](https://github.com/TheRobotStudio/SO-ARM100) follower arm via the [LeRobot](https://github.com/huggingface/lerobot) Python API. Together they form a safe, end-to-end session without requiring a leader arm or teleoperation rig.

The expected lifecycle for any session:

```
read_state  →  capture_camera  →  move_home  →  (your motion)  →  move_rest  →  relax
```

## Prerequisites

1. SO-ARM101 follower arm wired up (12 V power **and** USB-C data — both are required).
2. A `lerobot` conda environment with LeRobot installed and the Feetech extras:

   ```bash
   conda create -n lerobot python=3.10 ffmpeg=7.1.1 -c conda-forge
   conda activate lerobot
   pip install -e "lerobot[feetech]"   # from the LeRobot repo
   ```

3. Calibration JSON for the follower arm at
   `~/.cache/huggingface/lerobot/calibration/robots/so101_follower/<id>.json`.
   If missing, run `lerobot-calibrate --robot.type=so101_follower ...` first.

## Configuration

All scripts read three environment variables, with sensible defaults:

| Variable | Default | Description |
|---|---|---|
| `SO101_PORT` | auto-detected from `/dev/tty.usbmodem*` (macOS) or `/dev/ttyACM*` (Linux) | Serial port of the follower controller |
| `SO101_ROBOT_ID` | `my_awesome_follower_arm` | Calibration JSON ID |
| `SO101_CAMERA_INDEX` | `0` | OpenCV index for the wrist camera |

Override at runtime, for example:

```bash
SO101_PORT=/dev/ttyACM0 SO101_ROBOT_ID=my_arm \
    python example/so101/device/01_read_state.py
```

## Scripts

| # | Script | Description | Moves the arm? |
|---|---|---|---|
| 1 | `01_read_state.py` | Connect, print joint positions, disconnect. | No |
| 2 | `02_capture_camera.py` | Save one wrist-camera frame to `/tmp/so101_wrist.jpg`. | No |
| 3 | `03_move_home.py` | Slowly interpolate all joints to the calibrated middle (0). | Yes |
| 4 | `04_move_rest.py` | Fold into a low-energy parked pose. | Yes |
| 5 | `05_gripper_test.py` | Open/close gripper x 3 with all other joints locked. | Gripper only |
| 6 | `06_relax.py` | Disable torque so the arm goes limp. | No (servos go limp) |

## Quick start

```bash
conda activate lerobot

# Sanity check — must complete cleanly before doing anything else
python example/so101/device/01_read_state.py

# Take a photo through the wrist camera
python example/so101/device/02_capture_camera.py

# Drive the arm
python example/so101/device/03_move_home.py
python example/so101/device/04_move_rest.py

# Release torque at the end of the session
python example/so101/device/06_relax.py
```

## Library

`lib/safe_arm.py` is the only shared module. It provides:

- `auto_detect_port()` / `robot_id()` / `camera_index()` — read configuration.
- `follower_arm(disable_torque_on_disconnect=False)` — context manager that connects and disconnects cleanly.
- `read_joint_pos(arm)` — returns the six joint positions as a dict.
- `interpolate_to(arm, target, duration_sec=5.0, step_sec=0.05)` — smooth linear interpolation to a target pose.
- `HOME_POSE`, `REST_POSE` — the two reference poses used by scripts 3 and 4.

To define a new motion, copy `04_move_rest.py` and replace the `TARGET` import with your own dict.

## Safety

Read these once before running anything that moves the arm:

- **Workspace.** Make sure ~40 cm of clear space exists around and above the arm before running `03_move_home.py`. The rest pose (script 4) requires ~30 cm in front of and below the base.
- **Smooth motion only.** Never command a far-away joint target in one shot — use `interpolate_to` (or its equivalent in your own script). The example scripts default to 5–6 second motions, which the STS3215 servos track without overshoot.
- **Gripper overload.** If `disconnect()` ever raises `Overload error!`, the bus may collapse. Recovery requires unplugging the 12 V power for ~5 seconds. The library workaround — `disable_torque_on_disconnect=False` — is enabled by default in scripts 1–5.
- **macOS camera permission.** The terminal app that launched the script (Terminal, iTerm, VS Code, etc.) needs Camera permission in *System Settings → Privacy & Security → Camera*. The Python binary itself is irrelevant.

For deeper troubleshooting, see [`specs/troubleshooting.md`](specs/troubleshooting.md). For a higher-level workflow guide, see the top-level skill at [`skill/SO101_CONTROL.md`](../../skill/SO101_CONTROL.md).
