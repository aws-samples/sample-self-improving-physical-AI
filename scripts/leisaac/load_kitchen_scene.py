# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: Bandit v1.8.3 + Amazon CodeGuru Reviewer
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

import asyncio
import omni.usd
import omni.kit.app
import omni.timeline
from pxr import UsdGeom, Gf, UsdLux

async def load():
    for _ in range(10):
        await omni.kit.app.get_app().next_update_async()
    
    ctx = omni.usd.get_context()
    ctx.new_stage()
    for _ in range(5):
        await omni.kit.app.get_app().next_update_async()
    
    stage = ctx.get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    
    from isaacsim.core.utils.stage import add_reference_to_stage
    
    # Load kitchen
    add_reference_to_stage("/scene_data/scenes/kitchen_with_orange/scene.usd", "/World/Kitchen")
    for _ in range(30):
        await omni.kit.app.get_app().next_update_async()
    
    # Load robot
    add_reference_to_stage("/scene_data/robot.usd", "/World/Robot")
    for _ in range(10):
        await omni.kit.app.get_app().next_update_async()
    
    # Position robot - fix orientation!
    # The USD has Y-up but our stage is Z-up
    # Rotate -90 on X to convert Y-up to Z-up (stand upright)
    # Then rotate on Z to face the oranges (to the left)
    robot_prim = stage.GetPrimAtPath("/World/Robot")
    if robot_prim.IsValid():
        xf = UsdGeom.Xformable(robot_prim)
        xf.ClearXformOpOrder()
        # Place to the right of the plate, on counter
        translate = xf.AddTranslateOp()
        translate.Set(Gf.Vec3d(2.7, -0.35, 0.87))
        # Rotate: first X=-90 to stand up (Y-up -> Z-up), then Z=-90 to face oranges
        rotate = xf.AddRotateXYZOp()
        rotate.Set(Gf.Vec3f(-90, 0, -90))
        
        for _ in range(5):
            await omni.kit.app.get_app().next_update_async()
        cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_])
        bounds = cache.ComputeWorldBound(robot_prim)
        rng = bounds.GetRange()
        z_span = rng.GetMax()[2] - rng.GetMin()[2]
        print(f"[startup] Robot bounds: min={rng.GetMin()}, max={rng.GetMax()}")
        print(f"[startup] Robot Z-span: {z_span:.3f}m (should be ~0.3+ if upright)")
        
        # If still flat, try different rotation
        if z_span < 0.15:
            print("[startup] Still flat, trying rotation (90, 0, -90)...")
            xf.ClearXformOpOrder()
            translate = xf.AddTranslateOp()
            translate.Set(Gf.Vec3d(2.7, -0.35, 0.87))
            rotate = xf.AddRotateXYZOp()
            rotate.Set(Gf.Vec3f(90, 0, -90))
            for _ in range(3):
                await omni.kit.app.get_app().next_update_async()
            bounds = cache.ComputeWorldBound(robot_prim)
            rng = bounds.GetRange()
            z_span2 = rng.GetMax()[2] - rng.GetMin()[2]
            print(f"[startup] After fix: Z-span={z_span2:.3f}m")
    
    # Lighting
    dome = UsdLux.DomeLight.Define(stage, "/World/Dome")
    dome.GetIntensityAttr().Set(700)
    dome.GetColorAttr().Set(Gf.Vec3f(1.0, 0.97, 0.93))
    
    # Camera aimed at counter area
    cam = stage.GetPrimAtPath("/OmniverseKit_Persp")
    if cam.IsValid():
        xf = UsdGeom.Xformable(cam)
        ops = xf.GetOrderedXformOps()
        for op in ops:
            if "translate" in op.GetOpName():
                op.Set(Gf.Vec3d(2.3, -1.8, 1.4))
            elif "rotate" in op.GetOpName():
                op.Set(Gf.Vec3f(60, 0, 155))
    
    for _ in range(60):
        await omni.kit.app.get_app().next_update_async()
    
    omni.timeline.get_timeline_interface().play()
    print("[startup] Done!")

asyncio.ensure_future(load())
