"""Fold the follower arm into a low-energy parked (rest) pose.

Recommended at the end of every session — sitting in the rest pose draws
much less servo current than holding the home pose against gravity, and
keeps the arm in a known starting state for the next run.

The arm folds *forward and down* during the motion. Make sure there is
~30 cm of clear space directly in front of and below the base, and ~20 cm
on either side.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.safe_arm import REST_POSE, follower_arm, interpolate_to


def main() -> int:
    print("[1/3] Connecting ...")
    with follower_arm() as arm:
        print("      connected")
        print("[2/3] Moving to REST pose (6 s linear interpolation) ...")
        interpolate_to(arm, REST_POSE, duration_sec=6.0)
        print("[3/3] Disconnecting (torque preserved) ...")
    print("      done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
