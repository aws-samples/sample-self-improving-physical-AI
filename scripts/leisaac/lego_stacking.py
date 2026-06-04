"""
Lego Block Stacking Scenario: SO-101 picks and stacks lego blocks on a table.
Replaces the kitchen orange/plate scene with a tabletop block manipulation task.

Usage: Run inside Isaac Sim Kit via --exec
"""
import asyncio
import math
import omni.usd
import omni.kit.app
import omni.timeline
from pxr import UsdGeom, Gf, UsdLux, UsdPhysics, Usd, Sdf, UsdShade


# Configuration
ROBOT_POS = (0.0, -0.25, 0.75)    # On table edge, centered
ROBOT_YAW = 0.0                    # Facing +Y (toward blocks)
JOINT_TARGETS = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -100.0,
    "elbow_flex": 90.0,
    "wrist_flex": 50.0,
    "wrist_roll": 0.0,
    "gripper": -10.0,
}
JOINT_STIFFNESS = 17.8
JOINT_DAMPING = 0.60

# Lego blocks: (x, y, z_offset, color_rgb, name)
# Block dimensions: 0.032m x 0.016m x 0.012m (scaled 2x for visibility)
BLOCK_SIZE = (0.064, 0.032, 0.024)  # 2x scale for robot grasping
TABLE_HEIGHT = 0.75

BLOCKS = [
    {"name": "red_block",    "pos": (0.15, 0.12, 0.0),  "color": (0.9, 0.1, 0.1)},
    {"name": "blue_block",   "pos": (-0.10, 0.15, 0.0), "color": (0.1, 0.2, 0.9)},
    {"name": "yellow_block", "pos": (0.05, 0.20, 0.0),  "color": (0.95, 0.85, 0.1)},
    {"name": "green_block",  "pos": (-0.15, 0.08, 0.0), "color": (0.1, 0.8, 0.2)},
]

# Target stacking position
STACK_POS = (0.0, 0.15)  # x, y where blocks should be stacked


def create_table(stage):
    """Create a simple table."""
    table_path = "/World/Table"
    table_prim = UsdGeom.Cube.Define(stage, table_path)
    table_prim.GetSizeAttr().Set(1.0)

    xf = UsdGeom.Xformable(table_prim)
    xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.1, TABLE_HEIGHT / 2))
    xf.AddScaleOp().Set(Gf.Vec3f(0.8, 0.6, TABLE_HEIGHT))

    # Physics collider
    UsdPhysics.CollisionAPI.Apply(table_prim.GetPrim())

    # Material (wood-like)
    mat_path = "/World/Materials/TableMat"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.55, 0.35, 0.17))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.7)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(table_prim.GetPrim()).Bind(mat)

    print(f"[scene] Table created at height {TABLE_HEIGHT}m")


def create_lego_block(stage, name, pos, color):
    """Create a single lego-style block with physics."""
    block_path = f"/World/Blocks/{name}"
    block = UsdGeom.Cube.Define(stage, block_path)
    block.GetSizeAttr().Set(1.0)

    # Position on table surface
    world_pos = Gf.Vec3d(pos[0], pos[1], TABLE_HEIGHT + BLOCK_SIZE[2] / 2 + 0.001)
    xf = UsdGeom.Xformable(block)
    xf.AddTranslateOp().Set(world_pos)
    xf.AddScaleOp().Set(Gf.Vec3f(*BLOCK_SIZE))

    # Add studs on top (visual only — 2x3 pattern)
    stud_radius = 0.004
    stud_height = 0.003
    for sx in range(2):
        for sy in range(4):
            stud_path = f"{block_path}/stud_{sx}_{sy}"
            stud = UsdGeom.Cylinder.Define(stage, stud_path)
            stud.GetRadiusAttr().Set(stud_radius)
            stud.GetHeightAttr().Set(stud_height)
            stud_xf = UsdGeom.Xformable(stud)
            local_x = (sx - 0.5) * 0.024
            local_y = (sy - 1.5) * 0.012
            stud_xf.AddTranslateOp().Set(Gf.Vec3d(local_x, local_y, BLOCK_SIZE[2] / 2 + stud_height / 2))

    # Physics: rigid body + collider
    UsdPhysics.RigidBodyAPI.Apply(block.GetPrim())
    UsdPhysics.CollisionAPI.Apply(block.GetPrim())
    mass_api = UsdPhysics.MassAPI.Apply(block.GetPrim())
    mass_api.GetMassAttr().Set(0.025)  # 25g per block

    # Material (colored plastic)
    mat_path = f"/World/Materials/{name}_mat"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.3)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(block.GetPrim()).Bind(mat)

    print(f"[scene] Block '{name}' at {world_pos} color={color}")


def create_target_marker(stage):
    """Visual marker showing where to stack blocks."""
    marker_path = "/World/StackTarget"
    marker = UsdGeom.Cylinder.Define(stage, marker_path)
    marker.GetRadiusAttr().Set(0.05)
    marker.GetHeightAttr().Set(0.002)

    xf = UsdGeom.Xformable(marker)
    xf.AddTranslateOp().Set(Gf.Vec3d(STACK_POS[0], STACK_POS[1], TABLE_HEIGHT + 0.001))

    # Semi-transparent green
    mat_path = "/World/Materials/TargetMat"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.2, 0.9, 0.3))
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.4)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(marker.GetPrim()).Bind(mat)


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

    # Enable physics scene
    physics_scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    physics_scene.GetGravityDirectionAttr().Set(Gf.Vec3f(0, 0, -1))
    physics_scene.GetGravityMagnitudeAttr().Set(9.81)

    # Ground plane
    ground = UsdGeom.Xform.Define(stage, "/World/Ground")
    ground_plane = UsdPhysics.CollisionAPI.Apply(
        UsdGeom.Cube.Define(stage, "/World/Ground/Plane").GetPrim()
    )
    ground_geom = UsdGeom.Cube.Get(stage, "/World/Ground/Plane")
    ground_geom.GetSizeAttr().Set(1.0)
    gxf = UsdGeom.Xformable(ground_geom)
    gxf.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.5))
    gxf.AddScaleOp().Set(Gf.Vec3f(5.0, 5.0, 1.0))

    # Create table
    create_table(stage)

    # Create lego blocks
    UsdGeom.Xform.Define(stage, "/World/Blocks")
    for block in BLOCKS:
        create_lego_block(stage, block["name"], block["pos"], block["color"])

    # Stack target marker
    create_target_marker(stage)

    # Load robot
    from isaacsim.core.utils.stage import add_reference_to_stage
    add_reference_to_stage("/scene_data/robot.usd", "/World/Robot")
    for _ in range(10):
        await omni.kit.app.get_app().next_update_async()

    # Position robot
    robot_prim = stage.GetPrimAtPath("/World/Robot")
    xf = UsdGeom.Xformable(robot_prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(*ROBOT_POS))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, ROBOT_YAW))

    # Fix root link
    angle_rad = math.radians(ROBOT_YAW)
    quat_z = Gf.Quatf(math.cos(angle_rad / 2), 0, 0, math.sin(angle_rad / 2))
    fixed_joint = UsdPhysics.FixedJoint.Define(stage, "/World/Robot/FixedJoint")
    fixed_joint.GetBody1Rel().SetTargets(["/World/Robot/base"])
    fixed_joint.GetLocalPos0Attr().Set(Gf.Vec3f(*ROBOT_POS))
    fixed_joint.GetLocalRot0Attr().Set(quat_z)
    fixed_joint.GetLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
    fixed_joint.GetLocalRot1Attr().Set(Gf.Quatf(1, 0, 0, 0))
    print(f"[scene] Robot fixed at {ROBOT_POS}, yaw={ROBOT_YAW}°")

    # Configure joint drives
    for prim in Usd.PrimRange(robot_prim):
        if prim.IsA(UsdPhysics.RevoluteJoint):
            name = prim.GetName()
            if name in JOINT_TARGETS:
                stiff = prim.GetAttribute("drive:angular:physics:stiffness")
                if stiff.IsValid():
                    stiff.Set(JOINT_STIFFNESS)
                damp = prim.GetAttribute("drive:angular:physics:damping")
                if damp.IsValid():
                    damp.Set(JOINT_DAMPING)
                target = prim.GetAttribute("drive:angular:physics:targetPosition")
                if target.IsValid():
                    target.Set(JOINT_TARGETS[name])

    # Lighting
    dome = UsdLux.DomeLight.Define(stage, "/World/Dome")
    dome.GetIntensityAttr().Set(2000)
    dome.GetColorAttr().Set(Gf.Vec3f(0.9, 0.9, 1.0))

    # Key light (directional)
    key = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
    key.GetIntensityAttr().Set(5000)
    key_xf = UsdGeom.Xformable(key)
    key_xf.AddRotateXYZOp().Set(Gf.Vec3f(-45, 30, 0))

    # Camera — overhead angle viewing the table
    cam = stage.GetPrimAtPath("/OmniverseKit_Persp")
    if cam.IsValid():
        xf_cam = UsdGeom.Xformable(cam)
        for op in xf_cam.GetOrderedXformOps():
            if "translate" in op.GetOpName():
                op.Set(Gf.Vec3d(0.5, -0.6, 1.3))
            elif "rotate" in op.GetOpName():
                op.Set(Gf.Vec3f(55, 0, 160))

    # Wait for scene to load
    for _ in range(60):
        await omni.kit.app.get_app().next_update_async()

    # Start physics
    omni.timeline.get_timeline_interface().play()
    for _ in range(300):
        await omni.kit.app.get_app().next_update_async()

    print("[scene] ✅ Lego block stacking scene ready!")
    print(f"[scene] 4 blocks on table, stack target at {STACK_POS}")
    print("[scene] Robot: SO-101 at table edge, ready to pick and stack")


asyncio.ensure_future(load())
