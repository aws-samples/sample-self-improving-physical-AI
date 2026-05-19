# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: Bandit v1.8.3 + Amazon CodeGuru Reviewer
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

"""
SO-ARM101 Scene — Render with proven camera method
Uses set_camera_view (same as working capture_viewport.py)
"""
import os
import sys
import numpy as np

os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

from isaacsim.core.api import World
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid
from isaacsim.core.utils.viewports import set_camera_view
from isaacsim.sensors.camera import Camera
import omni.usd
from pxr import UsdGeom, Gf, UsdLux

print("="*60)
print("SO-ARM101 Digital Twin — Render")
print("="*60)

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
stage = omni.usd.get_context().get_stage()

# ========== LIGHTING ==========
print("[1/5] Lighting...")
dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
dome.CreateIntensityAttr(800)

key = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
key.CreateIntensityAttr(2500)
key.CreateAngleAttr(2.0)
UsdGeom.Xformable(key).AddTranslateOp().Set(Gf.Vec3d(1, -1, 3))
UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3d(-50, 20, 0))

# ========== TABLE ==========
print("[2/5] Table...")
FixedCuboid(
    prim_path="/World/Table",
    name="table",
    position=np.array([0.0, 0.0, -0.015]),
    scale=np.array([0.6, 0.45, 0.03]),
    color=np.array([0.65, 0.5, 0.35]),
)

# ========== SO-ARM101 ==========
print("[3/5] SO-ARM101 robot arm...")

# Base
FixedCuboid(prim_path="/World/Robot/Base", name="base",
    position=np.array([0.0, 0.0, 0.003]),
    scale=np.array([0.07, 0.07, 0.006]),
    color=np.array([0.15, 0.15, 0.15]))

# Base motor
FixedCuboid(prim_path="/World/Robot/BaseMotor", name="base_motor",
    position=np.array([0.0, 0.0, 0.03]),
    scale=np.array([0.048, 0.048, 0.04]),
    color=np.array([0.25, 0.25, 0.25]))

# Shoulder
FixedCuboid(prim_path="/World/Robot/Shoulder", name="shoulder",
    position=np.array([0.0, 0.0, 0.075]),
    scale=np.array([0.042, 0.042, 0.05]),
    color=np.array([0.92, 0.92, 0.92]))

# Upper arm
FixedCuboid(prim_path="/World/Robot/UpperArm", name="upper_arm",
    position=np.array([0.0, 0.0, 0.15]),
    scale=np.array([0.035, 0.04, 0.10]),
    color=np.array([0.92, 0.92, 0.92]))

# Elbow servo (dark)
FixedCuboid(prim_path="/World/Robot/Elbow", name="elbow",
    position=np.array([0.0, 0.0, 0.205]),
    scale=np.array([0.04, 0.025, 0.025]),
    color=np.array([0.2, 0.2, 0.2]))

# Forearm
FixedCuboid(prim_path="/World/Robot/Forearm", name="forearm",
    position=np.array([0.0, 0.0, 0.26]),
    scale=np.array([0.03, 0.035, 0.09]),
    color=np.array([0.92, 0.92, 0.92]))

# Wrist
FixedCuboid(prim_path="/World/Robot/Wrist", name="wrist",
    position=np.array([0.0, 0.0, 0.32]),
    scale=np.array([0.028, 0.03, 0.035]),
    color=np.array([0.92, 0.92, 0.92]))

# Gripper base
FixedCuboid(prim_path="/World/Robot/GripBase", name="grip_base",
    position=np.array([0.0, 0.0, 0.345]),
    scale=np.array([0.03, 0.04, 0.015]),
    color=np.array([0.2, 0.2, 0.2]))

# Gripper fingers (orange)
FixedCuboid(prim_path="/World/Robot/FingerL", name="finger_l",
    position=np.array([0.0, -0.015, 0.375]),
    scale=np.array([0.006, 0.008, 0.045]),
    color=np.array([1.0, 0.5, 0.0]))
FixedCuboid(prim_path="/World/Robot/FingerR", name="finger_r",
    position=np.array([0.0, 0.015, 0.375]),
    scale=np.array([0.006, 0.008, 0.045]),
    color=np.array([1.0, 0.5, 0.0]))

# Camera module (black box on gripper)
FixedCuboid(prim_path="/World/Robot/CamModule", name="cam_module",
    position=np.array([0.02, 0.0, 0.35]),
    scale=np.array([0.018, 0.018, 0.012]),
    color=np.array([0.05, 0.05, 0.05]))

# ========== OBJECTS ==========
print("[4/5] Manipulation objects...")
# Place colored cubes clearly visible around the arm's workspace
# Larger cubes, more spread out, on the table surface
DynamicCuboid(prim_path="/World/Obj/Red", name="red",
    position=np.array([0.15, -0.10, 0.02]),
    scale=np.array([0.035, 0.035, 0.035]),
    color=np.array([0.95, 0.1, 0.1]), mass=0.03)
DynamicCuboid(prim_path="/World/Obj/Green", name="green",
    position=np.array([0.20, 0.08, 0.02]),
    scale=np.array([0.035, 0.035, 0.035]),
    color=np.array([0.1, 0.85, 0.1]), mass=0.03)
DynamicCuboid(prim_path="/World/Obj/Blue", name="blue",
    position=np.array([0.10, 0.12, 0.02]),
    scale=np.array([0.035, 0.035, 0.035]),
    color=np.array([0.1, 0.2, 0.95]), mass=0.03)
DynamicCuboid(prim_path="/World/Obj/Yellow", name="yellow",
    position=np.array([0.22, -0.06, 0.02]),
    scale=np.array([0.03, 0.03, 0.03]),
    color=np.array([0.95, 0.9, 0.1]), mass=0.02)
DynamicCuboid(prim_path="/World/Obj/Purple", name="purple",
    position=np.array([0.08, -0.12, 0.02]),
    scale=np.array([0.03, 0.03, 0.03]),
    color=np.array([0.7, 0.1, 0.9]), mass=0.02)

# ========== CAMERA (using proven method) ==========
print("[5/5] Camera setup...")

# SO-101 is ~40cm tall. Objects on table at z~0.02
# Pull camera far back with wide-angle lens (same approach as manufacturing_scene)
eye_pos = np.array([1.0, -0.8, 0.7])
look_at = np.array([0.05, 0.0, 0.12])

cam = Camera(
    prim_path="/World/RenderCam",
    position=eye_pos,
    frequency=30,
    resolution=(1920, 1080),
)
cam.initialize()
cam.set_focal_length(12.0)  # Wide-angle like manufacturing_scene
cam.set_clipping_range(0.01, 20.0)

# Use set_camera_view — THE method that works
set_camera_view(
    eye=eye_pos,
    target=look_at,
    camera_prim_path="/World/RenderCam",
)

# ========== RENDER ==========
print("Rendering (50 warm-up steps)...")
world.reset()
for i in range(50):
    world.step(render=True)

# Capture
print("Capturing...")
frame = cam.get_rgba()

output_dir = "/output"
os.makedirs(output_dir, exist_ok=True)

if frame is not None and frame.max() > 0:
    from PIL import Image
    img = Image.fromarray(frame[:, :, :3])
    img.save(f"{output_dir}/so101_render.png")
    print(f"✅ Saved: {output_dir}/so101_render.png ({img.size[0]}x{img.size[1]}, {os.path.getsize(f'{output_dir}/so101_render.png')} bytes)")
else:
    print(f"⚠️  Frame issue. frame is None: {frame is None}")
    if frame is not None:
        print(f"    frame shape: {frame.shape}, max: {frame.max()}, min: {frame.min()}")

# Save USD
omni.usd.get_context().save_as_stage(f"{output_dir}/so101_digital_twin.usd")
print(f"✅ USD saved: {output_dir}/so101_digital_twin.usd")

print("\nDone!")
simulation_app.close()
