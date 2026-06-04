"""Disable torque on all six servos so the arm goes limp.

Run this last, after the arm is already in the REST pose. Sending
``Torque_Enable=0`` while the gripper or shoulder is fighting gravity
can trigger overload protection and bus collapse — see
``skill/so101-robot-control/references/troubleshooting.md``.

Recommended workflow:

    python 04_move_rest.py
    python 06_relax.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.safe_arm import follower_arm


def main() -> int:
    print("[1/2] Connecting ...")
    # Use the *default* torque-disable-on-disconnect behaviour for this script.
    with follower_arm(disable_torque_on_disconnect=True) as arm:
        print("      connected")
        print("[2/2] Disconnecting and disabling torque on all servos ...")
    print("      done — arm is limp; you can move it freely by hand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
