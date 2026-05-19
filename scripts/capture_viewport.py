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
capture_viewport.py - Capture a rendered image from the Isaac Sim 6.0 simulation camera.

Loads a scene (optionally with a Franka robot and conveyor) and renders
an image from a configurable camera viewpoint.

Security: Output images are written to the local filesystem on an Amazon EBS
volume encrypted at rest with the project AWS KMS key. No PII is captured
(simulation renders only). Data classification: "Internal" per project policy.

Usage:
    python capture_viewport.py --output /output/scene.png
    python capture_viewport.py --output /output/scene.png --eye "3,3,2" --target "0,0,0.5"
    python capture_viewport.py --output /output/scene.png --resolution "1920,1080" --scene manufacturing
    python capture_viewport.py --output /output/scene.png --usd-path /path/to/scene.usd
"""

import os
import sys
import argparse

# Accept EULA - MUST be before any isaacsim imports
os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description="Capture viewport image from Isaac Sim")
parser.add_argument("--output", type=str, required=True, help="Output image path")
parser.add_argument("--eye", type=str, default="3.0,-3.0,2.5",
                    help="Camera eye position x,y,z")
parser.add_argument("--target", type=str, default="0.0,0.0,0.5",
                    help="Camera look-at target x,y,z")
parser.add_argument("--resolution", type=str, default="1920,1080",
                    help="Image resolution width,height")
parser.add_argument("--focal-length", type=float, default=24.0,
                    help="Camera focal length in mm")
parser.add_argument("--scene", type=str, default="manufacturing",
                    choices=["empty", "manufacturing", "custom"],
                    help="Scene to load")
parser.add_argument("--usd-path", type=str, default=None,
                    help="Path to custom USD scene file")
parser.add_argument("--warm-up-steps", type=int, default=30,
                    help="Number of render steps before capture (for lighting convergence)")
args, _ = parser.parse_known_args()

try:
    eye = [float(x) for x in args.eye.split(",")]
    if len(eye) != 3:
        raise ValueError(f"Expected 3 eye values, got {len(eye)}")
    target_pt = [float(x) for x in args.target.split(",")]
    if len(target_pt) != 3:
        raise ValueError(f"Expected 3 target values, got {len(target_pt)}")
    res = [int(x) for x in args.resolution.split(",")]
    if len(res) != 2:
        raise ValueError(f"Expected 2 resolution values, got {len(res)}")
except (ValueError, IndexError) as e:
    print(f"Error: Invalid input format: {e}")
    sys.exit(1)

print(f"[capture_viewport] Starting Isaac Sim (headless)...")
simulation_app = SimulationApp({"headless": True})

import numpy as np
from pxr import UsdLux
import omni.usd
from isaacsim.core.api import World
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.storage.native.nucleus import get_assets_root_path
from isaacsim.core.utils.viewports import set_camera_view
from isaacsim.sensors.camera import Camera

# Create world
world = World(stage_units_in_meters=1.0)
stage = omni.usd.get_context().get_stage()

# ── Build Scene ───────────────────────────────────────────────────────
if args.scene == "custom" and args.usd_path:
    print(f"[capture_viewport] Loading custom USD: {args.usd_path}")
    omni.usd.get_context().open_stage(args.usd_path)
elif args.scene == "manufacturing":
    print("[capture_viewport] Building manufacturing scene for capture...")
    world.scene.add_default_ground_plane()

    assets_root = get_assets_root_path()

    # Lighting
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(500)

    # Factory floor
    VisualCuboid(
        prim_path="/World/Floor",
        name="floor",
        position=np.array([0.0, 0.0, -0.005]),
        scale=np.array([10.0, 10.0, 0.01]),
        color=np.array([0.35, 0.35, 0.38]),
    )

    # Conveyor
    FixedCuboid(
        prim_path="/World/Conveyor/Base",
        name="conveyor_base",
        position=np.array([-1.0, 0.0, 0.35]),
        scale=np.array([3.0, 0.6, 0.7]),
        color=np.array([0.25, 0.25, 0.28]),
    )
    FixedCuboid(
        prim_path="/World/Conveyor/Belt",
        name="conveyor_belt",
        position=np.array([-1.0, 0.0, 0.71]),
        scale=np.array([3.0, 0.55, 0.02]),
        color=np.array([0.15, 0.15, 0.15]),
    )

    # Boxes on conveyor
    for i, (x, color) in enumerate([
        (-2.0, np.array([0.8, 0.2, 0.2])),
        (-1.6, np.array([0.2, 0.6, 0.2])),
        (-1.2, np.array([0.2, 0.3, 0.8])),
        (-0.8, np.array([0.8, 0.6, 0.1])),
    ]):
        DynamicCuboid(
            prim_path=f"/World/Box_{i}",
            name=f"box_{i}",
            position=np.array([x, 0.0, 0.82]),
            scale=np.array([0.1, 0.08, 0.06]),
            color=color,
            mass=0.5,
        )

    # Robot
    if assets_root:
        try:
            franka_usd = assets_root + "/Isaac/Robots/Franka/franka_alt_fingers.usd"
            add_reference_to_stage(usd_path=franka_usd, prim_path="/World/Franka")
            from pxr import Gf, UsdGeom as UsdGeom2
            robot_xform = UsdGeom2.Xformable(stage.GetPrimAtPath("/World/Franka"))
            robot_xform.ClearXformOpOrder()
            robot_xform.AddTranslateOp().Set(Gf.Vec3d(0.5, 0.0, 0.0))
            print("[capture_viewport] Franka robot loaded.")
        except Exception as e:
            print(f"[capture_viewport] Could not load Franka: {e}")

    # Shelves
    for shelf_y in [-1.0, 1.0]:
        for s in range(4):
            FixedCuboid(
                prim_path=f"/World/Shelf_y{shelf_y:.0f}/Platform_{s}",
                name=f"shelf_{shelf_y}_{s}",
                position=np.array([2.0, shelf_y, s * 0.5 + 0.01]),
                scale=np.array([1.5, 0.5, 0.02]),
                color=np.array([0.45, 0.45, 0.48]),
            )
else:
    # Empty scene
    world.scene.add_default_ground_plane()
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(500)

print("[capture_viewport] Scene ready. Setting up camera...")

# ── Camera Setup ──────────────────────────────────────────────────────
cam = Camera(
    prim_path="/World/CaptureCamera",
    position=np.array(eye),
    frequency=30,
    resolution=(res[0], res[1]),
)
cam.initialize()
cam.set_focal_length(args.focal_length)

set_camera_view(
    eye=np.array(eye),
    target=np.array(target_pt),
    camera_prim_path="/World/CaptureCamera"
)

# ── Warm up rendering ────────────────────────────────────────────────
print(f"[capture_viewport] Warming up render ({args.warm_up_steps} steps)...")
world.reset()
for i in range(args.warm_up_steps):
    world.step(render=True)

# ── Capture ───────────────────────────────────────────────────────────
print("[capture_viewport] Capturing frame...")
frame = cam.get_rgba()

if frame is not None:
    from PIL import Image

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    img = Image.fromarray(frame[:, :, :3])
    img.save(args.output)

    print(f"[capture_viewport] ✓ Image saved: {args.output}")
    print(f"[capture_viewport]   Resolution: {res[0]}x{res[1]}")
    print(f"[capture_viewport]   Camera eye: {eye}")
    print(f"[capture_viewport]   Camera target: {target_pt}")
    print(f"[capture_viewport]   File size: {os.path.getsize(args.output)} bytes")
else:
    print("[capture_viewport] ERROR: Could not capture frame (frame is None)")
    print("[capture_viewport] This can happen if the renderer needs more warm-up steps.")
    print("[capture_viewport] Try increasing --warm-up-steps.")

print("[capture_viewport] Shutting down...")
simulation_app.close()
print("[capture_viewport] Done.")
