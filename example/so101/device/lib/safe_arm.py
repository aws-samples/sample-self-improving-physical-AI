"""Shared helpers for SO-ARM101 example scripts.

Pulls connection settings from environment variables, with sensible
defaults and macOS auto-detection of the controller serial port.
"""
from __future__ import annotations

import glob
import os
import time
from contextlib import contextmanager
from typing import Dict, Iterator

# All scripts share this set of joint keys. Order matters only for printing.
JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)


def auto_detect_port() -> str:
    """Find the SO-ARM101 controller serial port.

    Honours the ``SO101_PORT`` environment variable. Otherwise scans macOS
    ``/dev/tty.usbmodem*`` and Linux ``/dev/ttyACM*`` paths and returns the
    first match.
    """
    env = os.environ.get("SO101_PORT")
    if env:
        return env

    candidates = sorted(
        glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/ttyACM*")
    )
    if not candidates:
        raise RuntimeError(
            "Could not auto-detect SO-ARM101 serial port. "
            "Set SO101_PORT explicitly, e.g. "
            "SO101_PORT=/dev/tty.usbmodemXXXXXXXXXXX"
        )
    return candidates[0]


def robot_id() -> str:
    """Calibration ID for the follower arm.

    Honours ``SO101_ROBOT_ID``. The corresponding calibration JSON must
    exist at ``~/.cache/huggingface/lerobot/calibration/robots/so101_follower/<id>.json``.
    """
    return os.environ.get("SO101_ROBOT_ID", "my_awesome_follower_arm")


def camera_index() -> int:
    """OpenCV index of the wrist camera. Defaults to 0."""
    return int(os.environ.get("SO101_CAMERA_INDEX", "0"))


@contextmanager
def follower_arm(disable_torque_on_disconnect: bool = False) -> Iterator:
    """Context manager that connects to the follower arm and disconnects cleanly.

    By default, torque is **left enabled** on disconnect to avoid the gripper
    overload trap that bricks the bus until the 12V supply is power-cycled.
    Run ``06_relax.py`` deliberately when you want the arm to go limp.
    """
    from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

    config = SO101FollowerConfig(
        port=auto_detect_port(),
        id=robot_id(),
        disable_torque_on_disconnect=disable_torque_on_disconnect,
    )
    arm = SO101Follower(config)
    arm.connect(calibrate=False)
    try:
        yield arm
    finally:
        arm.disconnect()


def read_joint_pos(arm) -> Dict[str, float]:
    """Return the current six joint positions as a dict."""
    obs = arm.get_observation()
    return {k: float(obs[k]) for k in JOINT_KEYS}


def interpolate_to(
    arm,
    target: Dict[str, float],
    duration_sec: float = 5.0,
    step_sec: float = 0.05,
    verbose: bool = True,
) -> Dict[str, float]:
    """Smoothly drive the arm from its current pose to ``target``.

    Linear interpolation; ``duration_sec / step_sec`` ``send_action`` calls
    are issued. The default 5 s / 50 ms gives a 100-step trajectory at 20 Hz,
    which the STS3215 servos track without overshoot.

    Returns the final observed pose for verification.
    """
    if set(target) != set(JOINT_KEYS):
        raise ValueError(
            f"target must include exactly these keys: {JOINT_KEYS}\n"
            f"got: {sorted(target)}"
        )

    n_steps = max(1, int(round(duration_sec / step_sec)))
    start = read_joint_pos(arm)

    if verbose:
        print(f"  interpolating over {duration_sec:.1f}s ({n_steps} steps)")
        for k in JOINT_KEYS:
            print(f"    {k:20s} {start[k]:+7.2f}  ->  {target[k]:+7.2f}")

    for i in range(1, n_steps + 1):
        alpha = i / n_steps
        action = {
            k: start[k] + alpha * (target[k] - start[k]) for k in JOINT_KEYS
        }
        arm.send_action(action)
        time.sleep(step_sec)

    # Let the servos settle, then read the final pose
    time.sleep(0.5)
    final = read_joint_pos(arm)

    if verbose:
        print("  final pose (target | actual | error):")
        for k in JOINT_KEYS:
            err = final[k] - target[k]
            print(f"    {k:20s} {target[k]:+7.2f} | {final[k]:+7.2f} | {err:+5.2f}")

    return final


# Pre-defined poses
HOME_POSE: Dict[str, float] = {
    "shoulder_pan.pos": 0.0,
    "shoulder_lift.pos": 0.0,
    "elbow_flex.pos": 0.0,
    "wrist_flex.pos": 0.0,
    "wrist_roll.pos": 0.0,
    "gripper.pos": 60.0,  # slightly more than half-open to avoid overload
}

REST_POSE: Dict[str, float] = {
    "shoulder_pan.pos": 0.0,
    "shoulder_lift.pos": -98.0,
    "elbow_flex.pos": 100.0,
    "wrist_flex.pos": 71.0,
    "wrist_roll.pos": 0.0,
    "gripper.pos": 60.0,
}
