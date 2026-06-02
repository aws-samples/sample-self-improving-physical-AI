"""Smoothly drive the follower arm to its calibrated home (zero) position.

All six joints interpolate linearly to 0 over 5 seconds, except the gripper
which moves to 60 (slightly more than half-open) to avoid sitting at a hard
mechanical limit.

Make sure ~40 cm of clear space exists around and above the arm — it will
straighten up from whatever pose it is currently in.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.safe_arm import HOME_POSE, follower_arm, interpolate_to


def main() -> int:
    print("[1/3] Connecting ...")
    with follower_arm() as arm:
        print("      connected")
        print("[2/3] Moving to HOME pose (5 s linear interpolation) ...")
        interpolate_to(arm, HOME_POSE, duration_sec=5.0)
        print("[3/3] Disconnecting (torque preserved) ...")
    print("      done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
