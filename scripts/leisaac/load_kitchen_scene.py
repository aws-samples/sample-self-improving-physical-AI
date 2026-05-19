"""
Load LeIsaac Kitchen + SO-101 robot into Isaac Sim streaming mode.
Robot is positioned on counter edge, facing wall, between oranges and plate.

Used with: ./runheadless.sh --exec "/isaac-sim/load_kitchen.py"
"""
import asyncio
import math
import omni.usd
import omni.kit.app
import omni.timeline
from pxr import UsdGeom, Gf, UsdLux, UsdPhysics, Usd, Sdf


# Configuration
ROBOT_POS = (2.30, -0.55, 0.92)   # Counter edge, between oranges and plate
ROBOT_YAW = 180.0                  # Face +Y (toward wall/objects)
JOINT_TARGETS = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -100.0,       # Arm up (LeIsaac rest pose)
    "elbow_flex": 90.0,            # Elbow bent forward
    "wrist_flex": 50.0,            # Wrist tilted down
    "wrist_roll": 0.0,
    "gripper": -10.0,              # Closed
}
JOINT_STIFFNESS = 17.8             # LeIsaac default
JOINT_DAMPING = 0.60               # LeIsaac default


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

    # Load kitchen scene
    add_reference_to_stage("/scene_data/scenes/kitchen_with_orange/scene.usd", "/World/Kitchen")
    for _ in range(30):
        await omni.kit.app.get_app().next_update_async()

    # Load robot
    add_reference_to_stage("/scene_data/robot.usd", "/World/Robot")
    for _ in range(10):
        await omni.kit.app.get_app().next_update_async()

    # Position robot (no X/Y rotation — USD internal transforms handle orientation)
    robot_prim = stage.GetPrimAtPath("/World/Robot")
    xf = UsdGeom.Xformable(robot_prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(*ROBOT_POS))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, ROBOT_YAW))

    # Fix root link — create FixedJoint (world -> base)
    angle_rad = math.radians(ROBOT_YAW)
    quat_z = Gf.Quatf(math.cos(angle_rad / 2), 0, 0, math.sin(angle_rad / 2))

    fixed_joint = UsdPhysics.FixedJoint.Define(stage, "/World/Robot/FixedJoint")
    fixed_joint.GetBody1Rel().SetTargets(["/World/Robot/base"])
    fixed_joint.GetLocalPos0Attr().Set(Gf.Vec3f(*ROBOT_POS))
    fixed_joint.GetLocalRot0Attr().Set(quat_z)
    fixed_joint.GetLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
    fixed_joint.GetLocalRot1Attr().Set(Gf.Quatf(1, 0, 0, 0))
    print(f"[startup] Robot fixed at {ROBOT_POS}, yaw={ROBOT_YAW}°")

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
    print("[startup] Joint drives configured")

    # Lighting
    dome = UsdLux.DomeLight.Define(stage, "/World/Dome")
    dome.GetIntensityAttr().Set(3000)
    dome.GetColorAttr().Set(Gf.Vec3f(0.75, 0.75, 0.75))

    # Camera
    cam = stage.GetPrimAtPath("/OmniverseKit_Persp")
    if cam.IsValid():
        xf_cam = UsdGeom.Xformable(cam)
        for op in xf_cam.GetOrderedXformOps():
            if "translate" in op.GetOpName():
                op.Set(Gf.Vec3d(1.5, -1.5, 1.5))
            elif "rotate" in op.GetOpName():
                op.Set(Gf.Vec3f(50, 0, 145))

    # Wait for scene to fully load
    for _ in range(60):
        await omni.kit.app.get_app().next_update_async()

    # Start physics
    omni.timeline.get_timeline_interface().play()
    for _ in range(300):
        await omni.kit.app.get_app().next_update_async()

    print("[startup] Done! Kitchen scene ready with SO-101 in pick position.")


asyncio.ensure_future(load())
