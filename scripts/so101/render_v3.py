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
SO-ARM101 — Build scene then capture with proven camera approach
Reuses the exact camera method from capture_viewport.py that produced panorama.png
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

print("Building SO-ARM101 scene...")

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
stage = omni.usd.get_context().get_stage()

# ========== LIGHTING (same as manufacturing_scene) ==========
dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
dome.CreateIntensityAttr(500)

for i, (pos, name) in enumerate([
    ((0.0, 0.0, 2.0), "overhead"),
    ((1.0, -1.0, 1.5), "key"),
]):
    light = UsdLux.RectLight.Define(stage, f"/World/Light_{name}")
    light.CreateIntensityAttr(1200)
    light.CreateWidthAttr(0.8)
    light.CreateHeightAttr(0.8)
    xf = UsdGeom.Xformable(light.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(*pos))

# ========== TABLE ==========
FixedCuboid(prim_path="/World/Table", name="table",
    position=np.array([0.0, 0.0, -0.015]),
    scale=np.array([0.8, 0.6, 0.03]),
    color=np.array([0.6, 0.45, 0.3]))

# ========== SO-ARM101 ROBOT ==========
# Base
FixedCuboid(prim_path="/World/R/Base", name="base",
    position=np.array([0.0, 0.0, 0.004]),
    scale=np.array([0.08, 0.08, 0.008]),
    color=np.array([0.12, 0.12, 0.12]))

# Base motor
FixedCuboid(prim_path="/World/R/Motor", name="motor",
    position=np.array([0.0, 0.0, 0.03]),
    scale=np.array([0.05, 0.05, 0.04]),
    color=np.array([0.22, 0.22, 0.22]))

# Shoulder
FixedCuboid(prim_path="/World/R/Shoulder", name="shoulder",
    position=np.array([0.0, 0.0, 0.077]),
    scale=np.array([0.044, 0.044, 0.055]),
    color=np.array([0.93, 0.93, 0.93]))

# Upper arm
FixedCuboid(prim_path="/World/R/UpperArm", name="upper",
    position=np.array([0.0, 0.0, 0.155]),
    scale=np.array([0.036, 0.042, 0.10]),
    color=np.array([0.93, 0.93, 0.93]))

# Elbow servo
FixedCuboid(prim_path="/World/R/Elbow", name="elbow",
    position=np.array([0.0, 0.0, 0.21]),
    scale=np.array([0.042, 0.026, 0.026]),
    color=np.array([0.18, 0.18, 0.18]))

# Forearm
FixedCuboid(prim_path="/World/R/Forearm", name="forearm",
    position=np.array([0.0, 0.0, 0.27]),
    scale=np.array([0.032, 0.038, 0.095]),
    color=np.array([0.93, 0.93, 0.93]))

# Wrist servo
FixedCuboid(prim_path="/World/R/WristServo", name="wrist_servo",
    position=np.array([0.0, 0.0, 0.322]),
    scale=np.array([0.035, 0.024, 0.024]),
    color=np.array([0.18, 0.18, 0.18]))

# Wrist
FixedCuboid(prim_path="/World/R/Wrist", name="wrist",
    position=np.array([0.0, 0.0, 0.35]),
    scale=np.array([0.03, 0.032, 0.03]),
    color=np.array([0.93, 0.93, 0.93]))

# Gripper base
FixedCuboid(prim_path="/World/R/GripBase", name="gbase",
    position=np.array([0.0, 0.0, 0.372]),
    scale=np.array([0.032, 0.045, 0.014]),
    color=np.array([0.18, 0.18, 0.18]))

# Gripper fingers (orange - signature SO-101 color)
FixedCuboid(prim_path="/World/R/FingerL", name="fl",
    position=np.array([0.0, -0.018, 0.4]),
    scale=np.array([0.007, 0.008, 0.045]),
    color=np.array([1.0, 0.5, 0.0]))
FixedCuboid(prim_path="/World/R/FingerR", name="fr",
    position=np.array([0.0, 0.018, 0.4]),
    scale=np.array([0.007, 0.008, 0.045]),
    color=np.array([1.0, 0.5, 0.0]))

# Camera module
FixedCuboid(prim_path="/World/R/Cam", name="cam",
    position=np.array([0.022, 0.0, 0.375]),
    scale=np.array([0.02, 0.02, 0.014]),
    color=np.array([0.03, 0.03, 0.03]))

# ========== COLORED OBJECTS ==========
objs = [
    ("Red",    [0.18, -0.12, 0.02], [0.04, 0.04, 0.04], [0.95, 0.1, 0.1]),
    ("Green",  [0.22,  0.10, 0.02], [0.04, 0.04, 0.04], [0.1, 0.85, 0.1]),
    ("Blue",   [0.12,  0.15, 0.02], [0.04, 0.04, 0.04], [0.1, 0.2, 0.95]),
    ("Yellow", [0.25, -0.05, 0.02], [0.035, 0.035, 0.035], [0.95, 0.9, 0.1]),
    ("Purple", [0.10, -0.18, 0.02], [0.035, 0.035, 0.035], [0.7, 0.1, 0.9]),
    ("Orange", [0.28,  0.12, 0.02], [0.03, 0.03, 0.06], [1.0, 0.4, 0.0]),
]
for name, pos, scale, color in objs:
    DynamicCuboid(prim_path=f"/World/O/{name}", name=name.lower(),
        position=np.array(pos), scale=np.array(scale),
        color=np.array(color), mass=0.03)

# ========== CAMERA — pull VERY far back ==========
# The key insight from manufacturing_scene: camera must be FAR from scene
# SO-101 scene is ~0.5m across. Use distance proportional to scene size.
eye = np.array([3.0, -3.0, 2.5])
target = np.array([0.05, 0.0, 0.15])

cam = Camera(
    prim_path="/World/SceneCam",
    position=eye,
    frequency=30,
    resolution=(1920, 1080),
)
cam.initialize()
cam.set_focal_length(12.0)

set_camera_view(
    eye=eye,
    target=target,
    camera_prim_path="/World/SceneCam",
)

# ========== RENDER ==========
print("Rendering...")
world.reset()
for i in range(50):
    world.step(render=True)

print("Capturing...")
frame = cam.get_rgba()

output = "/output"
os.makedirs(output, exist_ok=True)

if frame is not None and frame.max() > 0:
    from PIL import Image
    img = Image.fromarray(frame[:, :, :3])
    path = f"{output}/so101_render.png"
    img.save(path)
    sz = os.path.getsize(path)
    print(f"OK: {path} ({img.size[0]}x{img.size[1]}, {sz} bytes)")
else:
    print(f"FAIL: frame={'None' if frame is None else f'max={frame.max()}'}")

# Save USD
omni.usd.get_context().save_as_stage(f"{output}/so101_digital_twin.usd")
print("USD saved")

simulation_app.close()
print("Done")
