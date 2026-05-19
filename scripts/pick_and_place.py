# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: Bandit v1.8.3 + Amazon CodeGuru Reviewer
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

#!/usr/bin/env python3
"""
pick_and_place.py - Robot pick and place demo in a manufacturing scene (Isaac Sim 6.0).

Loads the manufacturing environment, then commands the Franka Panda robot
to pick up a box from the conveyor and place it at a target location.

Uses isaacsim.robot.manipulators for the Franka robot and PickPlaceController.

Usage:
    python pick_and_place.py [--pick-index N] [--place-pos "x,y,z"] [--steps N]
"""

import os
import sys
import argparse

# Accept EULA - MUST be before any isaacsim imports
os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description="Pick and place demo")
parser.add_argument("--pick-index", type=int, default=0, help="Index of conveyor box to pick (0-3)")
parser.add_argument("--place-pos", type=str, default="0.5,-0.8,0.5", help="Target placement position x,y,z")
parser.add_argument("--steps", type=int, default=2000, help="Max simulation steps")
parser.add_argument("--capture", type=str, default=None, help="Capture final state image")
args, _ = parser.parse_known_args()

try:
    place_position = [float(x) for x in args.place_pos.split(",")]
    if len(place_position) != 3:
        raise ValueError(f"Expected 3 values (x,y,z), got {len(place_position)}")
except (ValueError, IndexError) as e:
    print(f"Error: Invalid place position format: {e}")
    sys.exit(1)

print("[pick_and_place] Starting Isaac Sim (headless)...")
simulation_app = SimulationApp({"headless": True})

import numpy as np
from pxr import Gf, UsdGeom

import omni.usd
from isaacsim.core.api import World
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.storage.native.nucleus import get_assets_root_path
from isaacsim.robot.manipulators.controllers import PickPlaceController
from isaacsim.robot.manipulators.grippers import ParallelGripper
from isaacsim.robot.manipulators import SingleManipulator
from isaacsim.robot_motion.motion_generation import (
    RmpFlow, ArticulationMotionPolicy, interface_config_loader
)

print("[pick_and_place] Building manufacturing scene...")

assets_root = get_assets_root_path()
if assets_root is None:
    assets_root = "omniverse://localhost/NVIDIA/Assets/Isaac/4.2"

# Create world
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()

# ── Conveyor Belt ─────────────────────────────────────────────────────
conveyor_base = FixedCuboid(
    prim_path="/World/Conveyor/Base",
    name="conveyor_base",
    position=np.array([-1.0, 0.0, 0.35]),
    scale=np.array([3.0, 0.6, 0.7]),
    color=np.array([0.25, 0.25, 0.28]),
)
conveyor_belt = FixedCuboid(
    prim_path="/World/Conveyor/Belt",
    name="conveyor_belt",
    position=np.array([-1.0, 0.0, 0.71]),
    scale=np.array([3.0, 0.55, 0.02]),
    color=np.array([0.15, 0.15, 0.15]),
)

# ── Robot Arm ─────────────────────────────────────────────────────────
print("[pick_and_place] Loading Franka Panda robot...")

# Load Franka USD via stage reference
franka_usd = assets_root + "/Isaac/Robots/Franka/franka_alt_fingers.usd"
add_reference_to_stage(usd_path=franka_usd, prim_path="/World/Franka")

# Set up gripper
gripper = ParallelGripper(
    end_effector_prim_path="/World/Franka/panda_rightfinger",
    joint_prim_names=["panda_finger_joint1", "panda_finger_joint2"],
    joint_opened_positions=np.array([0.04, 0.04]),
    joint_closed_positions=np.array([0.0, 0.0]),
    action_deltas=np.array([0.04, 0.04]),
)

# Create the manipulator
franka = world.scene.add(
    SingleManipulator(
        prim_path="/World/Franka",
        name="franka",
        end_effector_prim_path="/World/Franka/panda_rightfinger",
        gripper=gripper,
    )
)

# ── Target box (the one we'll pick) ──────────────────────────────────
box_positions = [
    np.array([-0.3, 0.0, 0.82]),
    np.array([-0.5, 0.0, 0.82]),
    np.array([-0.7, 0.0, 0.82]),
    np.array([-0.9, 0.0, 0.82]),
]

pick_idx = min(args.pick_index, len(box_positions) - 1)
pick_box_pos = box_positions[pick_idx]

# Create the pick target as a dynamic cuboid
pick_box = world.scene.add(
    DynamicCuboid(
        prim_path="/World/PickBox",
        name="pick_box",
        position=pick_box_pos,
        scale=np.array([0.05, 0.05, 0.05]),
        color=np.array([0.8, 0.2, 0.2]),
        mass=0.1,
    )
)

# Other boxes (visual only)
for i, pos in enumerate(box_positions):
    if i == pick_idx:
        continue
    VisualCuboid(
        prim_path=f"/World/OtherBox_{i}",
        name=f"other_box_{i}",
        position=pos,
        scale=np.array([0.05, 0.05, 0.05]),
        color=np.array([0.3, 0.3, 0.6]),
    )

# ── Target placement zone ────────────────────────────────────────────
target_pos = np.array(place_position)
VisualCuboid(
    prim_path="/World/TargetZone",
    name="target_zone",
    position=np.array([target_pos[0], target_pos[1], 0.005]),
    scale=np.array([0.1, 0.1, 0.005]),
    color=np.array([0.0, 0.9, 0.0]),
)

# ── Work Table ────────────────────────────────────────────────────────
FixedCuboid(
    prim_path="/World/WorkTable",
    name="work_table",
    position=np.array([target_pos[0], target_pos[1], target_pos[2] / 2 - 0.02]),
    scale=np.array([0.4, 0.4, target_pos[2] - 0.04]),
    color=np.array([0.5, 0.45, 0.35]),
)

print("[pick_and_place] Scene ready. Initializing controller...")

# ── Pick and Place Controller ─────────────────────────────────────────
world.reset()

# Create RMPFlow controller for configuration-space motion
rmp_config = interface_config_loader.load_supported_motion_policy_config("Franka", "RMPflow")
rmpflow = RmpFlow(**rmp_config)

physics_dt = 1.0 / 60.0
articulation_rmpflow = ArticulationMotionPolicy(franka, rmpflow, physics_dt)

from isaacsim.robot_motion.motion_generation import MotionPolicyController
cspace_controller = MotionPolicyController(
    name="cspace_controller",
    articulation_motion_policy=articulation_rmpflow,
)

controller = PickPlaceController(
    name="pick_place_controller",
    cspace_controller=cspace_controller,
    gripper=franka.gripper,
    end_effector_initial_height=0.3,
)

# Articulation controller for the robot
articulation_controller = franka.get_articulation_controller()

# ── Run the pick and place sequence ───────────────────────────────────
print(f"[pick_and_place] Starting pick and place sequence...")
print(f"[pick_and_place] Pick box at: {pick_box_pos}")
print(f"[pick_and_place] Target position: {target_pos}")

step = 0
task_done = False

while step < args.steps and not task_done:
    # Get current box position
    box_pos, _ = pick_box.get_world_pose()

    # Compute the pick-place action
    actions = controller.forward(
        picking_position=pick_box_pos,
        placing_position=target_pos,
        current_joint_positions=franka.get_joint_positions(),
        end_effector_offset=np.array([0.0, 0.0, 0.0]),
    )

    # Apply actions
    articulation_controller.apply_action(actions)

    # Step simulation
    world.step(render=True)
    step += 1

    if step % 100 == 0:
        print(f"[pick_and_place] Step {step}/{args.steps} - Box pos: {box_pos}")

    # Check if controller is done
    if controller.is_done():
        print(f"[pick_and_place] Pick and place completed at step {step}!")
        task_done = True

if not task_done:
    print(f"[pick_and_place] Reached max steps ({args.steps}). Task may be incomplete.")

# Final box position
final_box_pos, _ = pick_box.get_world_pose()
print(f"[pick_and_place] Final box position: {final_box_pos}")
distance = np.linalg.norm(final_box_pos[:2] - target_pos[:2])
print(f"[pick_and_place] Distance to target (XY): {distance:.4f}m")

# Run a few more steps for settling
for _ in range(50):
    world.step(render=True)

# ── Capture if requested ──────────────────────────────────────────────
if args.capture:
    print(f"[pick_and_place] Capturing viewport to: {args.capture}")
    from isaacsim.core.utils.viewports import set_camera_view
    from isaacsim.sensors.camera import Camera

    cam = Camera(
        prim_path="/World/PickPlaceCamera",
        position=np.array([1.5, -1.5, 1.5]),
        frequency=30,
        resolution=(1920, 1080),
    )
    cam.initialize()
    set_camera_view(
        eye=np.array([1.5, -1.5, 1.5]),
        target=np.array([0.0, 0.0, 0.4]),
        camera_prim_path="/World/PickPlaceCamera"
    )
    for _ in range(10):
        world.step(render=True)

    frame = cam.get_rgba()
    if frame is not None:
        from PIL import Image
        img = Image.fromarray(frame[:, :, :3])
        img.save(args.capture)
        print(f"[pick_and_place] Image saved: {args.capture}")

print("[pick_and_place] Shutting down...")
simulation_app.close()
print("[pick_and_place] Done.")
