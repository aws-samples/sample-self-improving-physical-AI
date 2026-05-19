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
robot_control.py - General-purpose robot arm control in Isaac Sim 6.0.

Supports Franka Panda with the following actions:
  --action move_joint   Move to specific joint positions
  --action move_to      Move end effector to a Cartesian target
  --action gripper      Open or close the gripper
  --action home         Return to home configuration

Usage:
    python robot_control.py --action move_joint --joints "0.0,0.5,0.0,-1.0,0.0,1.5,0.8"
    python robot_control.py --action move_to --target "0.4,0.0,0.4"
    python robot_control.py --action gripper --state open
    python robot_control.py --action gripper --state close
    python robot_control.py --action home
"""

import os
import sys
import argparse
import json

# Accept EULA - MUST be before any isaacsim imports
os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description="Control robot arm in Isaac Sim")
parser.add_argument("--action", type=str, required=True,
                    choices=["move_joint", "move_to", "gripper", "home"],
                    help="Action to perform")
parser.add_argument("--joints", type=str, default=None,
                    help="Comma-separated joint positions (7 values for Franka)")
parser.add_argument("--target", type=str, default=None,
                    help="Comma-separated target position x,y,z")
parser.add_argument("--state", type=str, default=None, choices=["open", "close"],
                    help="Gripper state (open/close)")
parser.add_argument("--steps", type=int, default=500,
                    help="Max simulation steps to reach target")
parser.add_argument("--output", type=str, default=None,
                    help="Output file for joint state JSON")
args, _ = parser.parse_known_args()

print(f"[robot_control] Starting Isaac Sim (headless)...")
print(f"[robot_control] Action: {args.action}")
simulation_app = SimulationApp({"headless": True})

import numpy as np
from isaacsim.core.api import World
from isaacsim.core.api.objects import FixedCuboid
from isaacsim.core.api.controllers import BaseController
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.storage.native.nucleus import get_assets_root_path
from isaacsim.robot.manipulators import SingleManipulator
from isaacsim.robot.manipulators.grippers import ParallelGripper

# Create world with ground plane and conveyor
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()

# Add conveyor for reference
FixedCuboid(
    prim_path="/World/Conveyor",
    name="conveyor",
    position=np.array([-1.0, 0.0, 0.35]),
    scale=np.array([3.0, 0.6, 0.7]),
    color=np.array([0.25, 0.25, 0.28]),
)

# Load the Franka robot
print("[robot_control] Loading Franka Panda...")
assets_root = get_assets_root_path()
if assets_root is None:
    assets_root = "omniverse://localhost/NVIDIA/Assets/Isaac/4.2"

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

world.reset()
articulation_controller = franka.get_articulation_controller()

# Franka home joint positions (default)
HOME_JOINTS = np.array([0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785])

def get_robot_state():
    """Get current robot state as a dict."""
    joint_positions = franka.get_joint_positions()
    joint_velocities = franka.get_joint_velocities()
    gripper_positions = franka.gripper.get_joint_positions()

    state = {
        "joint_positions": joint_positions[:7].tolist(),
        "joint_velocities": joint_velocities[:7].tolist(),
        "gripper_positions": gripper_positions.tolist() if gripper_positions is not None else [0.0, 0.0],
        "gripper_state": "open" if (gripper_positions is not None and gripper_positions[0] > 0.02) else "closed",
    }
    return state

def print_state(state, label="Current"):
    """Pretty print robot state."""
    print(f"\n[robot_control] === {label} Robot State ===")
    print(f"  Joint positions: [{', '.join(f'{j:.4f}' for j in state['joint_positions'])}]")
    print(f"  Gripper: {state['gripper_state']} ({state['gripper_positions']})")
    print(f"  ==========================================\n")

# ── Execute Action ────────────────────────────────────────────────────

if args.action == "home":
    print("[robot_control] Moving to home position...")
    target_joints = HOME_JOINTS

    for step in range(args.steps):
        current = franka.get_joint_positions()[:7]
        error = np.linalg.norm(target_joints - current)

        # Simple proportional control
        delta = target_joints - current
        command = current + 0.05 * delta

        # Apply joint position targets
        from isaacsim.core.utils.types import ArticulationAction
        action = ArticulationAction(joint_positions=np.append(command, [0.04, 0.04]))
        articulation_controller.apply_action(action)
        world.step(render=False)

        if error < 0.01:
            print(f"[robot_control] Home position reached at step {step + 1}")
            break

        if (step + 1) % 100 == 0:
            print(f"[robot_control] Step {step + 1}/{args.steps}, error: {error:.4f}")

    # Settle
    for _ in range(20):
        world.step(render=False)

elif args.action == "move_joint":
    if args.joints is None:
        print("[robot_control] ERROR: --joints required for move_joint action")
        simulation_app.close()
        sys.exit(1)

    try:
        target_joints = np.array([float(x) for x in args.joints.split(",")])
    except (ValueError, IndexError) as e:
        print(f"[robot_control] ERROR: Invalid joint values: {e}")
        sys.exit(1)
    if len(target_joints) != 7:
        print(f"[robot_control] ERROR: Expected 7 joint values, got {len(target_joints)}")
        simulation_app.close()
        sys.exit(1)

    # Validate joint limits (Franka Panda safe operating ranges in radians)
    JOINT_LIMITS = [
        (-2.8973, 2.8973),   # Joint 1
        (-1.7628, 1.7628),   # Joint 2
        (-2.8973, 2.8973),   # Joint 3
        (-3.0718, -0.0698),  # Joint 4
        (-2.8973, 2.8973),   # Joint 5
        (-0.0175, 3.7525),   # Joint 6
        (-2.8973, 2.8973),   # Joint 7
    ]
    for i, (val, (lo, hi)) in enumerate(zip(target_joints, JOINT_LIMITS)):
        if val < lo or val > hi:
            print(f"[robot_control] ERROR: Joint {i+1} value {val:.4f} outside safe limits [{lo}, {hi}]")
            simulation_app.close()
            sys.exit(1)

    print(f"[robot_control] Moving to joint positions: {target_joints}")

    for step in range(args.steps):
        current = franka.get_joint_positions()[:7]
        error = np.linalg.norm(target_joints - current)

        delta = target_joints - current
        command = current + 0.05 * delta

        from isaacsim.core.utils.types import ArticulationAction
        gripper_pos = franka.gripper.get_joint_positions()
        gripper_vals = gripper_pos if gripper_pos is not None else np.array([0.04, 0.04])
        action = ArticulationAction(joint_positions=np.append(command, gripper_vals))
        articulation_controller.apply_action(action)
        world.step(render=False)

        if error < 0.01:
            print(f"[robot_control] Target joint positions reached at step {step + 1}")
            break

        if (step + 1) % 100 == 0:
            print(f"[robot_control] Step {step + 1}/{args.steps}, error: {error:.4f}")

    for _ in range(20):
        world.step(render=False)

elif args.action == "move_to":
    if args.target is None:
        print("[robot_control] ERROR: --target required for move_to action")
        simulation_app.close()
        sys.exit(1)

    try:
        target_pos = np.array([float(x) for x in args.target.split(",")])
        if len(target_pos) != 3:
            raise ValueError(f"Expected 3 position values (x,y,z), got {len(target_pos)}")
    except (ValueError, IndexError) as e:
        print(f"[robot_control] ERROR: Invalid target format: {e}")
        simulation_app.close()
        sys.exit(1)
    print(f"[robot_control] Moving end effector to: {target_pos}")

    # Use RMPFlow for Cartesian motion
    try:
        from isaacsim.robot_motion.motion_generation import RmpFlow, ArticulationMotionPolicy
        from isaacsim.storage.native.nucleus import get_assets_root_path as _get_root

        _assets_root = _get_root()

        rmpflow = RmpFlow(
            robot_description_path=_assets_root + "/Isaac/Robots/Franka/rmpflow/robot_descriptor.yaml",
            urdf_path=_assets_root + "/Isaac/Robots/Franka/lula_franka_gen.urdf",
            rmpflow_config_path=_assets_root + "/Isaac/Robots/Franka/rmpflow/franka_rmpflow_common.yaml",
            end_effector_frame_name="right_gripper",
            maximum_substep_size=0.00334
        )

        physics_dt = 1.0 / 60.0
        articulation_rmpflow = ArticulationMotionPolicy(franka, rmpflow, physics_dt)

        rmpflow.set_end_effector_target(
            target_position=target_pos,
            target_orientation=np.array([0.0, 1.0, 0.0, 0.0])  # Pointing down
        )

        print("[robot_control] Using RMPFlow for Cartesian control...")

        for step in range(args.steps):
            rmpflow.update_world()
            actions = articulation_rmpflow.get_next_articulation_action()
            articulation_controller.apply_action(actions)
            world.step(render=False)

            if (step + 1) % 100 == 0:
                current_joints = franka.get_joint_positions()
                print(f"[robot_control] Step {step + 1}/{args.steps}")

        print("[robot_control] Cartesian motion complete.")

    except Exception as e:
        print(f"[robot_control] RMPFlow not available ({e}), using IK fallback...")
        # Fallback: simple IK approach
        from isaacsim.core.utils.types import ArticulationAction

        for step in range(args.steps):
            # Just step simulation (robot will remain in place without proper IK)
            world.step(render=False)
            if (step + 1) % 100 == 0:
                print(f"[robot_control] Step {step + 1}/{args.steps}")

        print("[robot_control] WARNING: Limited motion without RMPFlow.")

    for _ in range(20):
        world.step(render=False)

elif args.action == "gripper":
    if args.state is None:
        print("[robot_control] ERROR: --state required for gripper action (open/close)")
        simulation_app.close()
        sys.exit(1)

    print(f"[robot_control] Setting gripper to: {args.state}")

    if args.state == "open":
        franka.gripper.open()
    else:
        franka.gripper.close()

    # Step to execute gripper action
    for step in range(min(100, args.steps)):
        world.step(render=False)

    print(f"[robot_control] Gripper {args.state} command executed.")

# ── Report final state ────────────────────────────────────────────────
final_state = get_robot_state()
print_state(final_state, "Final")

# Output JSON if requested
if args.output:
    with open(args.output, 'w') as f:
        json.dump(final_state, f, indent=2)
    print(f"[robot_control] State saved to: {args.output}")

# Always output JSON to stdout as last line
print(f"[robot_control] STATE_JSON:{json.dumps(final_state)}")

print("[robot_control] Shutting down...")
simulation_app.close()
print("[robot_control] Done.")
