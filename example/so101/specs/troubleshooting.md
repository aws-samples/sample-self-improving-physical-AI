# SO-ARM101 Troubleshooting Decision Tree

Read this when something goes wrong. Each section starts from a concrete symptom.

## Symptom: "Missing motor IDs"

```
RuntimeError: FeetechMotorsBus motor check failed on port '...'
Missing motor IDs:
  - 1, 2, 3, 4, 5, 6
Full found motor list (id: model_number): {}
```

### Step 1 — How many IDs are missing?

- **All six (1–6) missing, brand-new arm**: factory default; every servo ships with `id=1`, so they collide on the bus. Run `lerobot-setup-motors` once. See the upstream LeRobot docs for the prompt sequence (gripper → wrist_roll → wrist_flex → elbow_flex → shoulder_lift → shoulder_pan).
- **All six missing, previously working arm**: power problem. Go to Step 2.
- **One or two missing (typically `6`, the gripper)**: that servo entered overload protection and dropped off the bus. Go to Step 3.

### Step 2 — Verify 12 V power

The controller LED can light up from USB alone, which is misleading. Confirm servo-bus power:

1. Barrel jack of the 12 V adapter is physically seated.
2. Wall outlet is live and the power adapter LED (if any) is lit.
3. Some controller boards have an on-board switch or jumper that gates the 12 V rail to the servo bus — verify it is in the ON position.
4. Try to back-drive a joint by hand. If it moves freely with no resistance, **the servos are unpowered** even if the LED is on.

If the joints do have resistance, the bus is powered but the controller cannot enumerate them. Reseat the 3-pin signal cable from the controller board to the first servo, then reseat each servo-to-servo cable in the daisy chain.

### Step 3 — Recover from overload

A servo that triggered overload protection will refuse to respond until it has been depowered. The cleanest fix:

1. Unplug the **12 V** power adapter (USB alone is not enough — you must cut the servo-bus rail).
2. Wait 5 seconds.
3. Reconnect 12 V. Listen for a faint click as the servos engage.
4. Re-run `01_read_state.py` and confirm all six IDs are visible.

To prevent recurrence:

- Always send the arm to a low-load rest pose before disconnecting.
- Use `disable_torque_on_disconnect=False` in `SO101FollowerConfig` for short scripts (`lib/safe_arm.py` already does this).
- Avoid commanding the gripper to a fully-closed position (`< 5`) when there is nothing to grip — it will torque against the mechanical limit.

## Symptom: Disconnect hangs for 10–20 s

`SO101Follower.disconnect()` is sending `Torque_Enable=0` and one of the servos is replying with overload errors that the driver retries six times each. The script will eventually exit, but the next session may find the bus in a bad state.

**Fix:** create the config with `disable_torque_on_disconnect=False`. Servos stay torque-enabled and warm, holding their position. This is fine for short scripts; for longer idle, send the arm to a rest pose first and then run `06_relax.py` deliberately.

## Symptom: Camera fails on macOS

```
OpenCV: not authorized to capture video (status 0), requesting...
OpenCV: camera failed to properly initialize!
```

The OS denied camera access to the **terminal application** that launched Python. The Python binary itself is irrelevant — macOS attributes the request to the parent app (Terminal, iTerm, VS Code, Cursor, Warp, etc.).

### Fix

1. Open *System Settings → Privacy & Security → Camera*.
2. Find your terminal app in the list and toggle it on.
3. Quit and relaunch the terminal — the permission only applies to processes started after the toggle.
4. Re-run `02_capture_camera.py`.

If the terminal app is not listed, run the capture script once. macOS will pop a permission dialog on the first `cv2.VideoCapture` call. Do not dismiss it — accept, then proceed.

### Identifying the wrist camera

The kit's wrist-mounted icspring camera typically shows up as OpenCV index `0` on macOS, with the laptop's FaceTime camera at index `1`. To verify:

```bash
python -c "
import cv2
for i in range(4):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        ok, frame = cap.read()
        if ok:
            h, w = frame.shape[:2]
            print(f'index {i}: {w}x{h}')
    cap.release()
"
```

The icspring camera is 640×480; FaceTime is typically 1280×720 or 1920×1080. The mapping is determined by USB enumeration order and may differ on Linux.

## Symptom: USB device disappears

**macOS:** the device path is `/dev/tty.usbmodem<serial>`. List with `ls /dev/tty.usbmodem*`.

If the path disappears between sessions or after a replug:

1. Try a different USB-C cable. Some are charge-only and do not carry data.
2. Plug directly into the laptop, bypassing any USB hub or dock. Some docks filter low-speed USB-Serial devices.
3. Run `system_profiler SPUSBDataType` and look for a CH340 / CP210x / FTDI USB-Serial entry. Absence means the controller is not enumerated at all.

**Linux:** the device path is `/dev/ttyACM0` (or `ttyACM1` if you also have a leader arm connected). Permission usually requires `chmod 666`:

```bash
sudo chmod 666 /dev/ttyACM0
```

Or, more permanently, add your user to the `dialout` group:

```bash
sudo usermod -aG dialout $USER
# log out and back in for the group change to take effect
```

## Symptom: Movement is jerky or overshoots

The example scripts use **linear interpolation** with 50 ms step size over 5–6 seconds for any home / rest motion. If your custom motion looks rough:

- Increase `DURATION_SEC` in your script (try 8–10 s for large excursions).
- Decrease `STEP_SEC` to 0.025 (40 Hz update) for smoother motion.
- Avoid long delays between `send_action` calls — the servos extrapolate during the gap.
- For paths that change direction, split into multiple linear segments rather than relying on one big interpolation.

## Symptom: Final pose differs from target

Expected. Each joint has its own steady-state error budget:

| Joint | Typical settling error | Cause |
|---|---|---|
| `shoulder_pan` | ±10–12 | Bears full arm weight; gear backlash at base |
| `shoulder_lift` | ±5 | Gravity load against gear train |
| `elbow_flex` | ±5 | Mid-arm gravity load |
| `wrist_flex` / `wrist_roll` | ±2 | Light load |
| `gripper` | ±1 | No external load |

If you need tighter tolerances, send the target a second time after a 0.5 s pause. The servos will integrate out the residual error.
