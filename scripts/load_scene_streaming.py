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
Load manufacturing scene into a running Isaac Sim streaming instance.
Run via: docker exec isaac-sim-streaming ./python.sh /scripts/load_scene_streaming.py
This uses Kit's execute_on_startup to build the scene in the running app.
"""
import omni.kit.app
import omni.usd
import asyncio
import numpy as np
from pxr import Gf, UsdGeom, UsdLux, UsdPhysics

async def build_scene():
    print("[scene_loader] Building manufacturing scene...")
    
    stage = omni.usd.get_context().get_stage()
    
    # Clear existing scene
    default_prim = stage.GetDefaultPrim()
    
    # === Ground Plane ===
    from isaacsim.core.api import World
    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    print("[scene_loader] Ground plane added")
    
    from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
    
    # === Lighting ===
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(500)
    dome_light.CreateColorAttr(Gf.Vec3f(1.0, 0.98, 0.95))
    
    distant_light = UsdLux.DistantLight.Define(stage, "/World/DistantLight")
    distant_light.CreateIntensityAttr(300)
    distant_light.CreateAngleAttr(2.0)
    xform = UsdGeom.Xformable(distant_light.GetPrim())
    xform.AddRotateXYZOp().Set(Gf.Vec3f(-45, 30, 0))
    print("[scene_loader] Lighting set up")
    
    # === Factory Floor ===
    factory_floor = VisualCuboid(
        prim_path="/World/FactoryFloor",
        name="factory_floor",
        position=np.array([0.0, 0.0, -0.005]),
        scale=np.array([10.0, 10.0, 0.01]),
        color=np.array([0.35, 0.35, 0.38]),
    )
    
    # Safety lines
    for i, y_pos in enumerate([-1.5, 1.5]):
        VisualCuboid(
            prim_path=f"/World/FloorMarking_{i}",
            name=f"floor_marking_{i}",
            position=np.array([0.0, y_pos, 0.001]),
            scale=np.array([8.0, 0.05, 0.002]),
            color=np.array([0.9, 0.8, 0.0]),
        )
    print("[scene_loader] Factory floor done")
    
    # === Conveyor Belt ===
    FixedCuboid(prim_path="/World/Conveyor/Base", name="conveyor_base",
        position=np.array([-1.0, 0.0, 0.35]), scale=np.array([3.0, 0.6, 0.7]),
        color=np.array([0.25, 0.25, 0.28]))
    FixedCuboid(prim_path="/World/Conveyor/Belt", name="conveyor_belt",
        position=np.array([-1.0, 0.0, 0.71]), scale=np.array([3.0, 0.55, 0.02]),
        color=np.array([0.15, 0.15, 0.15]))
    for i, y_off in enumerate([-0.3, 0.3]):
        FixedCuboid(prim_path=f"/World/Conveyor/Rail_{i}", name=f"conveyor_rail_{i}",
            position=np.array([-1.0, y_off, 0.78]), scale=np.array([3.0, 0.03, 0.1]),
            color=np.array([0.6, 0.6, 0.1]))
    print("[scene_loader] Conveyor belt done")
    
    # === Shelving ===
    def create_shelf(base_path, position, num_shelves=3, width=1.5, depth=0.5, height=2.0):
        shelf_height = height / num_shelves
        for i, (dx, dy) in enumerate([(-width/2, -depth/2), (-width/2, depth/2), (width/2, -depth/2), (width/2, depth/2)]):
            FixedCuboid(prim_path=f"{base_path}/Upright_{i}", name=f"upright_{i}",
                position=np.array([position[0]+dx, position[1]+dy, height/2]),
                scale=np.array([0.04, 0.04, height]), color=np.array([0.3, 0.35, 0.6]))
        for s in range(num_shelves + 1):
            z = s * shelf_height
            FixedCuboid(prim_path=f"{base_path}/Shelf_{s}", name=f"shelf_platform_{s}",
                position=np.array([position[0], position[1], z+0.01]),
                scale=np.array([width, depth, 0.02]), color=np.array([0.45, 0.45, 0.48]))
    
    create_shelf("/World/Shelf_A", position=(2.0, -1.0, 0.0))
    create_shelf("/World/Shelf_B", position=(2.0, 1.0, 0.0))
    print("[scene_loader] Shelving done")
    
    # === Robot Arm (Franka Panda) ===
    from isaacsim.core.utils.stage import add_reference_to_stage
    from isaacsim.storage.native.nucleus import get_assets_root_path
    from isaacsim.core.prims import XFormPrim
    
    assets_root = get_assets_root_path()
    if assets_root:
        franka_usd = assets_root + "/Isaac/Robots/Franka/franka_alt_fingers.usd"
        try:
            add_reference_to_stage(usd_path=franka_usd, prim_path="/World/Franka")
            xform_prim = XFormPrim(prim_path="/World/Franka", name="franka_robot")
            xform_prim.set_world_pose(position=np.array([0.5, 0.0, 0.0]), orientation=np.array([1.0, 0.0, 0.0, 0.0]))
            print("[scene_loader] Franka Panda loaded!")
        except Exception as e:
            print(f"[scene_loader] Franka load error: {e}")
    
    # === Boxes on Conveyor ===
    box_colors = [np.array([0.8, 0.2, 0.2]), np.array([0.2, 0.6, 0.2]), np.array([0.2, 0.3, 0.8]), np.array([0.8, 0.6, 0.1])]
    for i in range(4):
        DynamicCuboid(prim_path=f"/World/ConveyorBox_{i}", name=f"conveyor_box_{i}",
            position=np.array([-2.0 + i*0.4, 0.0, 0.82]), scale=np.array([0.1, 0.08, 0.06]),
            color=box_colors[i % len(box_colors)], mass=0.5)
    print("[scene_loader] Boxes placed")
    
    # === Work Table ===
    FixedCuboid(prim_path="/World/WorkTable/Top", name="work_table_top",
        position=np.array([0.5, -0.8, 0.4]), scale=np.array([0.8, 0.6, 0.03]),
        color=np.array([0.5, 0.45, 0.35]))
    VisualCuboid(prim_path="/World/TargetZone", name="target_zone",
        position=np.array([0.5, -0.8, 0.42]), scale=np.array([0.2, 0.2, 0.005]),
        color=np.array([0.0, 0.8, 0.0]))
    print("[scene_loader] Work table done")
    
    # === Start simulation ===
    world.reset()
    print("[scene_loader] ✅ Manufacturing scene loaded! Simulation running.")

# Schedule the scene build
asyncio.ensure_future(build_scene())
