"""
Lego Block Pick-and-Stack: SO-101 picks blocks and stacks them.
Run after lego_stacking.py has loaded the scene.

Task: Pick each colored block and stack them at the target position.
"""
import asyncio
import omni.usd
import omni.kit.app
import omni.timeline
from pxr import UsdPhysics, Usd, UsdGeom, Gf


# Stacking waypoints — pick block from table, place on stack
# Blocks are small (64x32x24mm), need precise gripper control
BLOCK_HEIGHT = 0.024

# Generic pick-and-stack for each block
def make_pick_stack_sequence(block_idx):
    """Generate waypoints for picking block_idx and stacking it."""
    # Stack height increases with each block
    stack_z_offset = block_idx * BLOCK_HEIGHT

    return [
        # 1. Home position
        {"shoulder_pan": 0, "shoulder_lift": -100, "elbow_flex": 90, "wrist_flex": 50, "wrist_roll": 0, "gripper": -10},
        # 2. Open gripper
        {"shoulder_pan": 0, "shoulder_lift": -80, "elbow_flex": 80, "wrist_flex": 40, "wrist_roll": 0, "gripper": 60},
        # 3. Move above block (approximate — real system uses vision)
        {"shoulder_pan": -15 + block_idx * 10, "shoulder_lift": -40, "elbow_flex": 50, "wrist_flex": 25, "wrist_roll": 0, "gripper": 60},
        # 4. Lower to block
        {"shoulder_pan": -15 + block_idx * 10, "shoulder_lift": -25, "elbow_flex": 40, "wrist_flex": 15, "wrist_roll": 0, "gripper": 60},
        # 5. Grasp
        {"shoulder_pan": -15 + block_idx * 10, "shoulder_lift": -25, "elbow_flex": 40, "wrist_flex": 15, "wrist_roll": 0, "gripper": -15},
        # 6. Lift
        {"shoulder_pan": -15 + block_idx * 10, "shoulder_lift": -70, "elbow_flex": 70, "wrist_flex": 35, "wrist_roll": 0, "gripper": -15},
        # 7. Move to stack position
        {"shoulder_pan": 0, "shoulder_lift": -70, "elbow_flex": 70, "wrist_flex": 35, "wrist_roll": 0, "gripper": -15},
        # 8. Lower to stack height
        {"shoulder_pan": 0, "shoulder_lift": -30 + block_idx * 3, "elbow_flex": 45, "wrist_flex": 20, "wrist_roll": 0, "gripper": -15},
        # 9. Release
        {"shoulder_pan": 0, "shoulder_lift": -30 + block_idx * 3, "elbow_flex": 45, "wrist_flex": 20, "wrist_roll": 0, "gripper": 60},
        # 10. Retreat up
        {"shoulder_pan": 0, "shoulder_lift": -80, "elbow_flex": 80, "wrist_flex": 40, "wrist_roll": 0, "gripper": 60},
    ]


STEPS_PER_WAYPOINT = 150  # ~2.5s at 60Hz


def set_joint_targets(robot_prim, targets):
    """Set joint drive targets for all specified joints."""
    for prim in Usd.PrimRange(robot_prim):
        if prim.IsA(UsdPhysics.RevoluteJoint):
            name = prim.GetName()
            if name in targets:
                attr = prim.GetAttribute("drive:angular:physics:targetPosition")
                if attr.IsValid():
                    attr.Set(targets[name])


async def run_stacking():
    """Execute the full stacking sequence — pick all 4 blocks."""
    stage = omni.usd.get_context().get_stage()
    robot_prim = stage.GetPrimAtPath("/World/Robot")

    if not robot_prim.IsValid():
        print("[stack] ERROR: Robot not found at /World/Robot")
        return

    # Ensure physics is playing
    timeline = omni.timeline.get_timeline_interface()
    if not timeline.is_playing():
        timeline.play()
        for _ in range(60):
            await omni.kit.app.get_app().next_update_async()

    block_names = ["red_block", "blue_block", "yellow_block", "green_block"]

    print("[stack] 🧱 Starting lego stacking sequence...")
    print(f"[stack] Goal: Stack {len(block_names)} blocks at target position")

    for block_idx, block_name in enumerate(block_names):
        print(f"\n[stack] === Picking {block_name} ({block_idx + 1}/{len(block_names)}) ===")
        sequence = make_pick_stack_sequence(block_idx)

        for wp_idx, waypoint in enumerate(sequence):
            action = ["home", "open", "approach", "lower", "grasp", "lift", "move", "place", "release", "retreat"][wp_idx]
            print(f"[stack]   {action}: gripper={waypoint['gripper']}")
            set_joint_targets(robot_prim, waypoint)
            for _ in range(STEPS_PER_WAYPOINT):
                await omni.kit.app.get_app().next_update_async()

    # Return to rest
    rest = {"shoulder_pan": 0, "shoulder_lift": -100, "elbow_flex": 90, "wrist_flex": 50, "wrist_roll": 0, "gripper": -10}
    set_joint_targets(robot_prim, rest)
    for _ in range(STEPS_PER_WAYPOINT):
        await omni.kit.app.get_app().next_update_async()

    print("\n[stack] ✅ Stacking complete! 4 blocks stacked.")


asyncio.ensure_future(run_stacking())
