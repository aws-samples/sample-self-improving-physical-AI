# LeRobot Python API Reference (SO-ARM101 subset)

This is a working reference for the API surface used by the example scripts. It is intentionally narrow — see the upstream LeRobot repository for the full API.

## Robot connection

```python
from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

config = SO101FollowerConfig(
    port="/dev/tty.usbmodemXXXXXXXXXXX",
    id="my_awesome_follower_arm",
    disable_torque_on_disconnect=False,  # see "Disconnect" below
)
follower = SO101Follower(config)
follower.connect(calibrate=False)  # calibrate=True only if no calibration JSON exists
```

`SO101FollowerConfig` arguments used in this skill:

| Argument | Type | Default | Notes |
|---|---|---|---|
| `port` | `str` | required | Serial port, e.g. `/dev/tty.usbmodem...` (macOS) or `/dev/ttyACM0` (Linux) |
| `id` | `str` | required | Calibration ID; must match the JSON filename in `~/.cache/huggingface/lerobot/calibration/robots/so101_follower/` |
| `disable_torque_on_disconnect` | `bool` | `True` | If True, `disconnect()` sends `Torque_Enable=0` to all servos. Set False for short scripts to avoid overload errors during teardown. |

`follower.connect(calibrate=False)`:

- Opens the serial port.
- Performs a Feetech bus handshake: pings each expected motor ID and verifies model number.
- Loads calibration from `~/.cache/huggingface/lerobot/calibration/robots/so101_follower/<id>.json`.

If the handshake fails, you get `RuntimeError: FeetechMotorsBus motor check failed`. See `troubleshooting.md`.

## Reading joint state

```python
obs = follower.get_observation()
# obs is a dict with the following keys (when no cameras are configured):
# 'shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos',
# 'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos'
```

Values are in **calibrated units**, roughly normalized so 0 is the middle of the joint's range and ±100 are the mechanical limits. The exact mapping is determined by the calibration JSON.

`get_observation()` blocks for one round-trip on the Feetech bus (1 Mbps, ~6 reads). Expect 5–10 ms latency per call.

## Sending actions

```python
action = {
    "shoulder_pan.pos": 0.0,
    "shoulder_lift.pos": 0.0,
    "elbow_flex.pos": 0.0,
    "wrist_flex.pos": 0.0,
    "wrist_roll.pos": 0.0,
    "gripper.pos": 50.0,
}
follower.send_action(action)
```

Notes:

- The dict **must** include all six joint keys. Omitting one raises a validation error.
- `send_action` issues a SYNC_WRITE on the Feetech bus — all six servos receive their target in a single packet. Latency is roughly constant regardless of how many joints you change.
- The servos will move toward the target as fast as their internal speed limit allows. To get smooth motion, call `send_action` repeatedly with intermediate targets — that is the entire point of the interpolation helper in `lib/safe_arm.py`.

## Disconnect

```python
follower.disconnect()
```

If `disable_torque_on_disconnect=True` (the default), this sends `Torque_Enable=0` to every servo. Risk: a servo currently fighting load can reply with `[RxPacketError] Overload error!`, and after six retries the driver raises `RuntimeError: Failed to write 'Torque_Enable' on id_=N`. In severe cases the bus itself collapses and the next connect attempt sees `Missing motor IDs: 1-6`.

Recommended pattern for short scripts:

```python
config = SO101FollowerConfig(
    port=...,
    id=...,
    disable_torque_on_disconnect=False,  # leave torque on
)
```

When you actually want the arm to go limp at the end of a long session, run the dedicated `06_relax.py` script (which uses the default `True`). By that point the arm is in a low-load rest pose and the disable command succeeds cleanly.

## Cameras

The example scripts use OpenCV directly rather than the LeRobot camera API, because the LeRobot abstraction adds complexity (it expects cameras to be registered with the robot config) without buying anything for single-shot capture.

```python
import cv2

cap = cv2.VideoCapture(0)               # 0 is typically the wrist camera
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Warm up — first few frames are often dark while auto-exposure ramps
for _ in range(5):
    cap.read()

ok, frame = cap.read()
cv2.imwrite("/tmp/wrist.jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
cap.release()
```

Frame is a `numpy.ndarray` of shape `(H, W, 3)` in **BGR** order (OpenCV convention). If you pass it to a model that expects RGB, convert:

```python
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
```

## When you do want LeRobot-managed cameras

For data collection or teleoperation you want cameras attached to the robot config so observations are time-aligned:

```python
from lerobot.cameras.opencv import OpenCVCameraConfig

config = SO101FollowerConfig(
    port="...",
    id="...",
    cameras={
        "wrist": OpenCVCameraConfig(index_or_path=0, width=640, height=480, fps=30),
        "front": OpenCVCameraConfig(index_or_path=1, width=640, height=480, fps=30),
    },
)
follower = SO101Follower(config)
follower.connect(calibrate=False)

obs = follower.get_observation()
# obs now also contains 'wrist' and 'front' keys with numpy frame arrays
```

This is the path used by `lerobot.record` and `lerobot.teleoperate`.
