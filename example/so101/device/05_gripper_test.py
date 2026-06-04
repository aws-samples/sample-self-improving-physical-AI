"""Open and close the gripper three times with all other joints locked.

The five non-gripper joints are read once at the start and held at those
exact values for the duration of the test. Only servo ID 6 (the gripper)
moves.

Useful as a mechanical sanity check after a power cycle or recalibration.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.safe_arm import JOINT_KEYS, follower_arm, read_joint_pos

GRIPPER_OPEN = 90.0
GRIPPER_CLOSE = 15.0
SETTLE_SEC = 1.2
N_CYCLES = 3


def main() -> int:
    print("[1/4] Connecting ...")
    with follower_arm() as arm:
        print("      connected")

        print("[2/4] Reading current pose (will be locked for non-gripper joints) ...")
        start = read_joint_pos(arm)
        locked = {k: start[k] for k in JOINT_KEYS if k != "gripper.pos"}
        for k, v in locked.items():
            print(f"        lock  {k:20s} {v:+7.2f}")

        print(f"[3/4] Running gripper open/close x {N_CYCLES} ...")
        for cycle in range(1, N_CYCLES + 1):
            for label, target in (
                ("OPEN ", GRIPPER_OPEN),
                ("CLOSE", GRIPPER_CLOSE),
            ):
                action = dict(locked)
                action["gripper.pos"] = target
                arm.send_action(action)
                print(f"        cycle {cycle}  gripper -> {label} ({target:.0f})")
                time.sleep(SETTLE_SEC)

        # Park gripper at a safe mid-position
        final = dict(locked)
        final["gripper.pos"] = 60.0
        arm.send_action(final)
        time.sleep(SETTLE_SEC)
        print("        parked gripper at 60")

        print("[4/4] Disconnecting (torque preserved) ...")
    print("      done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
