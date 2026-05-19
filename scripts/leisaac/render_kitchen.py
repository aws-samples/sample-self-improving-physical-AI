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
Render static images from LeIsaac Kitchen Orange Picking scene.
Uses Isaac Sim 6.0 headless mode to capture multiple viewpoints.

Usage:
    ./python.sh render_kitchen.py [--warmup 300] [--output /output]
"""
import os
import sys
import argparse

os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp

parser = argparse.ArgumentParser()
parser.add_argument("--warmup", type=int, default=300)
parser.add_argument("--output", type=str, default="/output")
args = parser.parse_args()

simulation_app = SimulationApp({"headless": True, "width": 1920, "height": 1080})

import numpy as np
from PIL import Image
from pxr import UsdGeom, Gf, UsdLux, Usd

from isaacsim.core.api import World
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.sensors.camera import Camera

print("[render] Setting up world...")
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()

stage = world.stage
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

# Load kitchen scene
print("[render] Loading kitchen scene...")
add_reference_to_stage("/scene_data/scenes/kitchen_with_orange/scene.usd", "/World/Kitchen")

# Load SO-101 robot
print("[render] Loading SO-101 robot...")
add_reference_to_stage("/scene_data/robot.usd", "/World/Robot")

# Position robot upright on counter (Y-up USD -> Z-up stage)
robot_prim = stage.GetPrimAtPath("/World/Robot")
if robot_prim.IsValid():
    xf = UsdGeom.Xformable(robot_prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(2.7, -0.35, 0.87))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(-90, 0, -90))  # Stand upright, face oranges
    print("[render] Robot placed at (2.7, -0.35, 0.87), facing oranges")

# Lighting
dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
dome.GetIntensityAttr().Set(700)
dome.GetColorAttr().Set(Gf.Vec3f(1.0, 0.97, 0.93))

# Key light
rect = UsdLux.RectLight.Define(stage, "/World/KeyLight")
rect.GetIntensityAttr().Set(3000)
rect.GetWidthAttr().Set(1.0)
rect.GetHeightAttr().Set(1.0)
UsdGeom.Xformable(rect.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(2.5, -2.0, 2.5))

world.reset()

# Camera viewpoints (eye, target) pairs
viewpoints = {
    "kitchen_overview": {
        "eye": (4.0, -3.5, 2.5),
        "target": (2.0, -0.3, 0.9),
        "desc": "Full kitchen overview"
    },
    "kitchen_robot_closeup": {
        "eye": (2.8, -1.2, 1.3),
        "target": (2.5, -0.35, 0.95),
        "desc": "Robot + oranges closeup"
    },
    "kitchen_topdown": {
        "eye": (2.3, -0.35, 2.5),
        "target": (2.3, -0.35, 0.87),
        "desc": "Top-down view of counter"
    },
    "kitchen_side": {
        "eye": (1.0, -1.5, 1.2),
        "target": (2.5, -0.3, 0.95),
        "desc": "Side view showing reach"
    },
}

# Create camera
cam = Camera(
    prim_path="/World/RenderCamera",
    resolution=(1920, 1080),
    frequency=30,
)
cam.initialize()
cam.set_focal_length(18.0)

# Warm-up
print(f"[render] Warming up ({args.warmup} steps)...")
for i in range(args.warmup):
    world.step(render=True)
    if (i + 1) % 50 == 0:
        print(f"[render]   Step {i+1}/{args.warmup}")

# Capture each viewpoint
os.makedirs(args.output, exist_ok=True)
for name, vp in viewpoints.items():
    print(f"[render] Capturing: {name} ({vp['desc']})")
    cam.set_world_pose(
        position=np.array(vp["eye"]),
        orientation=None
    )
    # Use set_camera_view for proper look-at
    from isaacsim.core.utils.stage import set_camera_view
    set_camera_view(
        eye=list(vp["eye"]),
        target=list(vp["target"]),
        camera_prim_path="/World/RenderCamera"
    )
    
    # Render frames for convergence
    for _ in range(50):
        world.step(render=True)
    
    # Capture
    frame = cam.get_rgba()
    if frame is not None and frame.any():
        img = Image.fromarray(frame[:, :, :3])
        path = os.path.join(args.output, f"{name}.png")
        img.save(path)
        print(f"[render]   Saved: {path} ({img.size}, mean={np.array(img).mean():.0f})")
    else:
        print(f"[render]   WARNING: Empty frame for {name}")

# Save USD
usd_path = os.path.join(args.output, "kitchen_orange_pick.usd")
stage.Export(usd_path)
print(f"[render] USD exported: {usd_path}")

world.stop()
simulation_app.close()
print("[render] Done!")
