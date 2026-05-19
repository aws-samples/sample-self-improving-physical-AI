"""
Pick-and-place animation: SO-101 picks an orange and places it on the plate.
Drives joint targets through a sequence of waypoints.

Usage: Run inside Isaac Sim Kit via --exec, after load_kitchen_scene.py has loaded.
Or integrate into a live session via Script Editor.
"""
import asyncio
import omni.usd
import omni.kit.app
import omni.timeline
from pxr import UsdPhysics, Usd


# Waypoint sequences (joint angles in degrees)
# Each waypoint: {joint_name: angle, ...}
PICK_SEQUENCE = [
    # 1. Rest pose (starting position)
    {"shoulder_pan": 0, "shoulder_lift": -100, "elbow_flex": 90, "wrist_flex": 50, "wrist_roll": 0, "gripper": -10},
    # 2. Open gripper
    {"shoulder_pan": 0, "shoulder_lift": -100, "elbow_flex": 90, "wrist_flex": 50, "wrist_roll": 0, "gripper": 60},
    # 3. Reach toward orange (extend arm)
    {"shoulder_pan": -20, "shoulder_lift": -50, "elbow_flex": 50, "wrist_flex": 30, "wrist_roll": 0, "gripper": 60},
    # 4. Lower to orange
    {"shoulder_pan": -20, "shoulder_lift": -30, "elbow_flex": 40, "wrist_flex": 20, "wrist_roll": 0, "gripper": 60},
    # 5. Close gripper (grasp)
    {"shoulder_pan": -20, "shoulder_lift": -30, "elbow_flex": 40, "wrist_flex": 20, "wrist_roll": 0, "gripper": -10},
    # 6. Lift orange
    {"shoulder_pan": -20, "shoulder_lift": -80, "elbow_flex": 70, "wrist_flex": 40, "wrist_roll": 0, "gripper": -10},
    # 7. Rotate to plate
    {"shoulder_pan": 30, "shoulder_lift": -80, "elbow_flex": 70, "wrist_flex": 40, "wrist_roll": 0, "gripper": -10},
    # 8. Lower to plate
    {"shoulder_pan": 30, "shoulder_lift": -40, "elbow_flex": 50, "wrist_flex": 30, "wrist_roll": 0, "gripper": -10},
    # 9. Release
    {"shoulder_pan": 30, "shoulder_lift": -40, "elbow_flex": 50, "wrist_flex": 30, "wrist_roll": 0, "gripper": 60},
    # 10. Return to rest
    {"shoulder_pan": 0, "shoulder_lift": -100, "elbow_flex": 90, "wrist_flex": 50, "wrist_roll": 0, "gripper": -10},
]

STEPS_PER_WAYPOINT = 200  # Physics steps between waypoints (~3.3s at 60Hz)


def set_joint_targets(robot_prim, targets):
    """Set joint drive targets for all specified joints."""
    for prim in Usd.PrimRange(robot_prim):
        if prim.IsA(UsdPhysics.RevoluteJoint):
            name = prim.GetName()
            if name in targets:
                attr = prim.GetAttribute("drive:angular:physics:targetPosition")
                if attr.IsValid():
                    attr.Set(targets[name])


async def run_pick_and_place():
    """Execute the pick-and-place sequence."""
    stage = omni.usd.get_context().get_stage()
    robot_prim = stage.GetPrimAtPath("/World/Robot")

    if not robot_prim.IsValid():
        print("[pick] ERROR: Robot not found at /World/Robot")
        return

    # Ensure physics is playing
    timeline = omni.timeline.get_timeline_interface()
    if not timeline.is_playing():
        timeline.play()
        for _ in range(60):
            await omni.kit.app.get_app().next_update_async()

    print("[pick] Starting pick-and-place sequence...")
    for i, waypoint in enumerate(PICK_SEQUENCE):
        print(f"[pick] Waypoint {i+1}/{len(PICK_SEQUENCE)}: gripper={waypoint['gripper']}")
        set_joint_targets(robot_prim, waypoint)
        for _ in range(STEPS_PER_WAYPOINT):
            await omni.kit.app.get_app().next_update_async()

    print("[pick] Pick-and-place complete!")


# Auto-run when executed via --exec
asyncio.ensure_future(run_pick_and_place())
