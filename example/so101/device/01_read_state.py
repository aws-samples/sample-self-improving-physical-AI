"""Read the current joint state of the SO-ARM101 follower arm.

Read-only — no motion commands are sent. Use this to verify the bus is
healthy before running any of the motion examples.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `lib.safe_arm` importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.safe_arm import JOINT_KEYS, follower_arm, read_joint_pos


def main() -> int:
    print("[1/3] Connecting to follower arm ...")
    with follower_arm() as arm:
        print("      connected")
        print("[2/3] Reading current joint positions ...")
        pose = read_joint_pos(arm)
        for k in JOINT_KEYS:
            print(f"        {k:20s} {pose[k]:+7.2f}")
        print("[3/3] Disconnecting (torque preserved) ...")
    print("      done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
