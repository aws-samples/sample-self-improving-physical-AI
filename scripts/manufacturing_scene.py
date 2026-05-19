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
manufacturing_scene.py - Create a manufacturing environment in Isaac Sim 6.0.

Creates a factory floor with:
- Ground plane with industrial appearance
- Conveyor belt
- Shelving/storage racks
- Franka Panda robot arm
- Boxes/parts on the conveyor
- Proper lighting

Usage:
    python manufacturing_scene.py [--save-usd PATH] [--steps N]
"""

import os
import sys
import argparse

# Accept EULA via environment - MUST be before any isaacsim imports
os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

from isaacsim import SimulationApp

# Parse args before SimulationApp init (it consumes some args)
parser = argparse.ArgumentParser(description="Create a manufacturing scene in Isaac Sim")
parser.add_argument("--save-usd", type=str, default=None, help="Save scene as USD file")
parser.add_argument("--steps", type=int, default=200, help="Number of simulation steps to run (0 = just create scene)")
parser.add_argument("--capture", type=str, default=None, help="Capture viewport image to this path")
args, _ = parser.parse_known_args()

print("[manufacturing_scene] Starting Isaac Sim (headless)...")
simulation_app = SimulationApp({"headless": True})

# Now import Isaac Sim modules (using 6.0.0 API)
import numpy as np
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics, PhysxSchema

import omni.usd
from isaacsim.core.api import World
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.storage.native.nucleus import get_assets_root_path

print("[manufacturing_scene] Isaac Sim started. Building scene...")

# Get assets root (Nucleus or local)
assets_root = get_assets_root_path()
if assets_root is None:
    # Fallback for offline environments
    assets_root = "omniverse://localhost/NVIDIA/Assets/Isaac/4.2"
    print(f"[manufacturing_scene] WARNING: Could not get assets root, using fallback: {assets_root}")
else:
    print(f"[manufacturing_scene] Assets root: {assets_root}")

# Create the world
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
print("[manufacturing_scene] Ground plane added.")

stage = omni.usd.get_context().get_stage()

# ── Lighting ──────────────────────────────────────────────────────────
print("[manufacturing_scene] Setting up factory lighting...")

# Main overhead light (like factory ceiling lights)
dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
dome_light.CreateIntensityAttr(500)
dome_light.CreateColorAttr(Gf.Vec3f(1.0, 0.98, 0.95))

# Directional fill light
distant_light = UsdLux.DistantLight.Define(stage, "/World/DistantLight")
distant_light.CreateIntensityAttr(300)
distant_light.CreateAngleAttr(2.0)
xform = UsdGeom.Xformable(distant_light.GetPrim())
xform.AddRotateXYZOp().Set(Gf.Vec3f(-45, 30, 0))

# Spot lights for work areas
for i, (pos, target_name) in enumerate([
    ((0.5, 0.0, 2.5), "robot_area"),
    ((-1.0, 0.0, 2.5), "conveyor_area"),
]):
    spot = UsdLux.RectLight.Define(stage, f"/World/AreaLight_{target_name}")
    spot.CreateIntensityAttr(800)
    spot.CreateWidthAttr(0.5)
    spot.CreateHeightAttr(0.5)
    xformable = UsdGeom.Xformable(spot.GetPrim())
    xformable.AddTranslateOp().Set(Gf.Vec3d(*pos))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(-90, 0, 0))

# ── Factory Floor (visual overlay on ground plane) ────────────────────
print("[manufacturing_scene] Creating factory floor...")
factory_floor = VisualCuboid(
    prim_path="/World/FactoryFloor",
    name="factory_floor",
    position=np.array([0.0, 0.0, -0.005]),
    scale=np.array([10.0, 10.0, 0.01]),
    color=np.array([0.35, 0.35, 0.38]),  # Industrial gray
)

# Floor markings (safety lines)
for i, y_pos in enumerate([-1.5, 1.5]):
    VisualCuboid(
        prim_path=f"/World/FloorMarking_{i}",
        name=f"floor_marking_{i}",
        position=np.array([0.0, y_pos, 0.001]),
        scale=np.array([8.0, 0.05, 0.002]),
        color=np.array([0.9, 0.8, 0.0]),  # Yellow safety lines
    )

# ── Conveyor Belt ─────────────────────────────────────────────────────
print("[manufacturing_scene] Building conveyor belt...")

# Conveyor base structure
conveyor_base = FixedCuboid(
    prim_path="/World/Conveyor/Base",
    name="conveyor_base",
    position=np.array([-1.0, 0.0, 0.35]),
    scale=np.array([3.0, 0.6, 0.7]),
    color=np.array([0.25, 0.25, 0.28]),  # Dark metal
)

# Conveyor belt surface
conveyor_belt = FixedCuboid(
    prim_path="/World/Conveyor/Belt",
    name="conveyor_belt",
    position=np.array([-1.0, 0.0, 0.71]),
    scale=np.array([3.0, 0.55, 0.02]),
    color=np.array([0.15, 0.15, 0.15]),  # Black rubber belt
)

# Conveyor legs
for i, (x, y) in enumerate([(-2.3, -0.25), (-2.3, 0.25), (0.3, -0.25), (0.3, 0.25)]):
    FixedCuboid(
        prim_path=f"/World/Conveyor/Leg_{i}",
        name=f"conveyor_leg_{i}",
        position=np.array([x, y, 0.175]),
        scale=np.array([0.05, 0.05, 0.35]),
        color=np.array([0.3, 0.3, 0.32]),
    )

# Conveyor side rails
for i, y_off in enumerate([-0.3, 0.3]):
    FixedCuboid(
        prim_path=f"/World/Conveyor/Rail_{i}",
        name=f"conveyor_rail_{i}",
        position=np.array([-1.0, y_off, 0.78]),
        scale=np.array([3.0, 0.03, 0.1]),
        color=np.array([0.6, 0.6, 0.1]),  # Yellow safety rails
    )

# ── Shelving/Storage Racks ────────────────────────────────────────────
print("[manufacturing_scene] Building storage racks...")

def create_shelf(base_path, position, num_shelves=3, width=1.5, depth=0.5, height=2.0):
    """Create a shelving unit."""
    shelf_height = height / num_shelves
    # Uprights
    for i, (dx, dy) in enumerate([
        (-width/2, -depth/2), (-width/2, depth/2),
        (width/2, -depth/2), (width/2, depth/2)
    ]):
        FixedCuboid(
            prim_path=f"{base_path}/Upright_{i}",
            name=f"upright_{i}",
            position=np.array([position[0] + dx, position[1] + dy, height/2]),
            scale=np.array([0.04, 0.04, height]),
            color=np.array([0.3, 0.35, 0.6]),  # Blue-gray industrial
        )
    # Shelf platforms
    for s in range(num_shelves + 1):
        z = s * shelf_height
        FixedCuboid(
            prim_path=f"{base_path}/Shelf_{s}",
            name=f"shelf_platform_{s}",
            position=np.array([position[0], position[1], z + 0.01]),
            scale=np.array([width, depth, 0.02]),
            color=np.array([0.45, 0.45, 0.48]),
        )

# Two shelf units
create_shelf("/World/Shelf_A", position=(2.0, -1.0, 0.0), num_shelves=3, width=1.5, depth=0.5, height=1.8)
create_shelf("/World/Shelf_B", position=(2.0, 1.0, 0.0), num_shelves=3, width=1.5, depth=0.5, height=1.8)

# Add some boxes on shelves
shelf_box_positions = [
    (2.0, -1.0, 0.65), (1.7, -1.0, 0.65), (2.3, -1.0, 0.65),
    (2.0, -1.0, 1.25), (1.8, -1.0, 1.25),
    (2.0, 1.0, 0.65), (2.2, 1.0, 0.65),
]
for i, pos in enumerate(shelf_box_positions):
    color = np.array([0.6, 0.3, 0.1]) if i % 2 == 0 else np.array([0.2, 0.4, 0.6])
    VisualCuboid(
        prim_path=f"/World/ShelfBox_{i}",
        name=f"shelf_box_{i}",
        position=np.array(pos),
        scale=np.array([0.15, 0.12, 0.1]),
        color=color,
    )

# ── Robot Arm (Franka Panda) ──────────────────────────────────────────
print("[manufacturing_scene] Loading Franka Panda robot arm...")

franka_usd = assets_root + "/Isaac/Robots/Franka/franka_alt_fingers.usd"
try:
    robot_prim = add_reference_to_stage(usd_path=franka_usd, prim_path="/World/Franka")
    # Position the robot next to the conveyor using direct USD API
    from pxr import UsdGeom
    robot_xform = UsdGeom.Xformable(stage.GetPrimAtPath("/World/Franka"))
    robot_xform.ClearXformOpOrder()
    robot_xform.AddTranslateOp().Set(Gf.Vec3d(0.5, 0.0, 0.0))
    print("[manufacturing_scene] Franka Panda loaded successfully.")
except Exception as e:
    print(f"[manufacturing_scene] WARNING: Could not load Franka from {franka_usd}: {e}")
    print("[manufacturing_scene] Creating placeholder robot...")
    # Placeholder robot base
    FixedCuboid(
        prim_path="/World/Franka/Base",
        name="robot_base_placeholder",
        position=np.array([0.5, 0.0, 0.15]),
        scale=np.array([0.2, 0.2, 0.3]),
        color=np.array([0.9, 0.9, 0.9]),
    )

# ── Boxes on Conveyor ─────────────────────────────────────────────────
print("[manufacturing_scene] Placing boxes on conveyor...")

box_colors = [
    np.array([0.8, 0.2, 0.2]),  # Red
    np.array([0.2, 0.6, 0.2]),  # Green
    np.array([0.2, 0.3, 0.8]),  # Blue
    np.array([0.8, 0.6, 0.1]),  # Orange
]

for i in range(4):
    DynamicCuboid(
        prim_path=f"/World/ConveyorBox_{i}",
        name=f"conveyor_box_{i}",
        position=np.array([-2.0 + i * 0.4, 0.0, 0.82]),
        scale=np.array([0.1, 0.08, 0.06]),
        color=box_colors[i % len(box_colors)],
        mass=0.5,
    )

# ── Work Table ────────────────────────────────────────────────────────
print("[manufacturing_scene] Adding work table...")
FixedCuboid(
    prim_path="/World/WorkTable/Top",
    name="work_table_top",
    position=np.array([0.5, -0.8, 0.4]),
    scale=np.array([0.8, 0.6, 0.03]),
    color=np.array([0.5, 0.45, 0.35]),
)
for i, (dx, dy) in enumerate([(-0.35, -0.25), (-0.35, 0.25), (0.35, -0.25), (0.35, 0.25)]):
    FixedCuboid(
        prim_path=f"/World/WorkTable/Leg_{i}",
        name=f"table_leg_{i}",
        position=np.array([0.5 + dx, -0.8 + dy, 0.2]),
        scale=np.array([0.04, 0.04, 0.4]),
        color=np.array([0.4, 0.4, 0.42]),
    )

# ── Target placement area ────────────────────────────────────────────
VisualCuboid(
    prim_path="/World/TargetZone",
    name="target_zone",
    position=np.array([0.5, -0.8, 0.42]),
    scale=np.array([0.2, 0.2, 0.005]),
    color=np.array([0.0, 0.8, 0.0]),  # Green target zone
)

print("[manufacturing_scene] Scene build complete!")

# ── Save USD if requested ─────────────────────────────────────────────
if args.save_usd:
    print(f"[manufacturing_scene] Saving scene to: {args.save_usd}")
    omni.usd.get_context().save_as_stage(args.save_usd)
    print("[manufacturing_scene] Scene saved.")

# ── Run simulation ────────────────────────────────────────────────────
if args.steps > 0:
    print(f"[manufacturing_scene] Running {args.steps} simulation steps...")
    world.reset()
    for i in range(args.steps):
        world.step(render=True)
        if (i + 1) % 50 == 0:
            print(f"[manufacturing_scene] Step {i + 1}/{args.steps}")
    print("[manufacturing_scene] Simulation complete.")

# ── Capture viewport if requested ─────────────────────────────────────
if args.capture:
    print(f"[manufacturing_scene] Capturing viewport to: {args.capture}")
    from isaacsim.core.utils.viewports import set_camera_view
    from isaacsim.sensors.camera import Camera

    # Set up camera far enough to see entire factory layout
    # Scene objects use scale as full-size, so scene is large
    # Pull camera way back for panoramic view
    eye_pos = np.array([12.0, -12.0, 10.0])
    look_at = np.array([0.0, 0.0, 0.3])

    cam = Camera(
        prim_path="/World/SceneCamera",
        position=eye_pos,
        frequency=30,
        resolution=(1920, 1080),
    )
    cam.initialize()
    cam.set_focal_length(12.0)  # Ultra-wide for full factory view

    set_camera_view(
        eye=eye_pos,
        target=look_at,
        camera_prim_path="/World/SceneCamera"
    )

    # Render frames to stabilize
    for _ in range(30):
        world.step(render=True)

    # Get the image
    frame = cam.get_rgba()
    if frame is not None:
        from PIL import Image
        img = Image.fromarray(frame[:, :, :3])
        img.save(args.capture)
        print(f"[manufacturing_scene] Image saved: {args.capture}")
    else:
        print("[manufacturing_scene] WARNING: Could not capture frame.")

print("[manufacturing_scene] Done. Shutting down...")
simulation_app.close()
print("[manufacturing_scene] Shutdown complete.")
