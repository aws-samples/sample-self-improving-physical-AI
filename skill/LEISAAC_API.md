# LeIsaac SO-101 Kitchen Scene — API Reference & Skill

This document summarizes the key APIs, functions, and lessons learned for loading and controlling the SO-101 robot in NVIDIA Isaac Sim 6.0 with the LeIsaac kitchen scene.

## Core Setup Pattern

```python
import asyncio
import omni.usd, omni.kit.app, omni.timeline
from pxr import UsdGeom, Gf, UsdLux, UsdPhysics, Usd, Sdf
from isaacsim.core.utils.stage import add_reference_to_stage

# 1. Create stage
stage = omni.usd.get_context().get_stage()
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

# 2. Load scene
add_reference_to_stage("/path/to/kitchen_with_orange/scene.usd", "/World/Kitchen")

# 3. Load robot
add_reference_to_stage("/path/to/so101_follower.usd", "/World/Robot")
```

## Robot Placement

The `so101_follower.usd` is a Y-up model. In a Z-up stage, do **NOT** rotate it — the internal link transforms already handle orientation correctly.

```python
robot_prim = stage.GetPrimAtPath("/World/Robot")
xf = UsdGeom.Xformable(robot_prim)
xf.ClearXformOpOrder()

# Position on counter (Z=0.92 is counter_main_main_group/geometry_1 top)
xf.AddTranslateOp().Set(Gf.Vec3d(x, y, 0.92))

# Rotate on Z to set facing direction
# 0° = arm extends toward -Y (forward/camera)
# 180° = arm extends toward +Y (toward wall)
# 90° = arm extends toward -X (left)
xf.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, 180))  # face wall
```

## Fix Root Link (Critical!)

The `so101_follower.usd` does NOT have `fixBase` baked in. Without anchoring, physics will topple the robot. IsaacLab sets this at runtime via `fix_root_link=True` which creates a FixedJoint.

```python
import math

# Create FixedJoint: world frame -> robot base
fixed_joint = UsdPhysics.FixedJoint.Define(stage, "/World/Robot/FixedJoint")
fixed_joint.GetBody1Rel().SetTargets(["/World/Robot/base"])

# localPos0 = robot position in world frame
fixed_joint.GetLocalPos0Attr().Set(Gf.Vec3f(x, y, z))

# localRot0 = robot rotation as quaternion
# For Z-rotation of `angle` degrees:
angle_rad = math.radians(angle)
quat = Gf.Quatf(math.cos(angle_rad/2), 0, 0, math.sin(angle_rad/2))
fixed_joint.GetLocalRot0Attr().Set(quat)

# Body1 local frame = origin
fixed_joint.GetLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
fixed_joint.GetLocalRot1Attr().Set(Gf.Quatf(1, 0, 0, 0))
```

**Warning:** If `localPos0`/`localRot0` don't match the actual robot transform, physics will EXPLODE (robot flies to infinity).

## Joint Control

SO-101 joints: `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper`

### Set Joint Targets (with physics running)

```python
joint_targets = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -100.0,  # arm up
    "elbow_flex": 90.0,       # elbow bent forward
    "wrist_flex": 50.0,       # wrist tilted
    "wrist_roll": 0.0,
    "gripper": -10.0,         # closed
}

for prim in Usd.PrimRange(robot_prim):
    if prim.IsA(UsdPhysics.RevoluteJoint):
        name = prim.GetName()
        if name in joint_targets:
            prim.GetAttribute("drive:angular:physics:stiffness").Set(17.8)
            prim.GetAttribute("drive:angular:physics:damping").Set(0.60)
            prim.GetAttribute("drive:angular:physics:targetPosition").Set(joint_targets[name])
```

### LeIsaac Default Poses

| Pose | shoulder_pan | shoulder_lift | elbow_flex | wrist_flex | wrist_roll | gripper |
|------|-------------|---------------|------------|------------|------------|---------|
| Rest | 0 | -100 | 90 | 50 | 0 | -10 |
| Extended | 0 | 0 | 0 | 0 | 0 | 0 |
| Open gripper | — | — | — | — | — | 50 |

### Joint Limits (degrees)

| Joint | Min | Max |
|-------|-----|-----|
| shoulder_pan | -110 | 110 |
| shoulder_lift | -100 | 100 |
| elbow_flex | -100 | 90 |
| wrist_flex | -95 | 95 |
| wrist_roll | -160 | 160 |
| gripper | -10 | 100 |

## Scene Coordinates

Kitchen counter (`counter_main_main_group/geometry_1`):
- X: [1.71, 2.75]
- Y: [-0.65, 0.00]  (edge at -0.65, wall at 0.00)
- Z: [0.89, 0.92]   (top surface = 0.92)

Objects:
- Orange001: (2.13, -0.30, 0.95)
- Orange002: (2.25, -0.33, 0.95)
- Orange003: (2.15, -0.41, 0.94)
- Plate: (2.42, -0.34, 0.96)

## What Does NOT Work

| Approach | Result |
|----------|--------|
| `physxArticulation:fixBase` attribute | Not recognized in Isaac Sim 6.0 |
| `physics:kinematicEnabled = True` on base | Partial — arm still collapses |
| Removing all RigidBodyAPI | Robot stays upright but joints won't move |
| Setting `physics:mass = 1000` on base | Physics explosion |
| External FixedJoint without matching rotation | Physics explosion |
| `PhysxSchema.PhysxArticulationAPI.GetFixBaseAttr()` | API doesn't exist in 6.0 |

## Disable Physics (Visual Only Mode)

For static renders where you don't need joint movement:

```python
for prim in Usd.PrimRange(robot_prim):
    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
        rb = prim.GetAttribute("physics:rigidBodyEnabled")
        if rb.IsValid():
            rb.Set(False)
        else:
            prim.CreateAttribute("physics:rigidBodyEnabled", Sdf.ValueTypeNames.Bool).Set(False)
```

## Camera Control

The perspective camera (`/OmniverseKit_Persp`) already has xformOps — use `.Set()` not `.Add()`:

```python
cam = stage.GetPrimAtPath("/OmniverseKit_Persp")
xf_cam = UsdGeom.Xformable(cam)
for op in xf_cam.GetOrderedXformOps():
    if "translate" in op.GetOpName():
        op.Set(Gf.Vec3d(eye_x, eye_y, eye_z))
    elif "rotate" in op.GetOpName():
        op.Set(Gf.Vec3f(rot_x, rot_y, rot_z))
```

## Streaming Container Setup

```bash
docker run -d --name isaac-sim-streaming \
  --gpus all \
  -e "ACCEPT_EULA=Y" -e "PRIVACY_CONSENT=Y" \
  --network=host \
  -v /path/to/assets:/scene_data/scenes:ro \
  -v /path/to/robot.usd:/scene_data/robot.usd:ro \
  -v /path/to/script.py:/isaac-sim/load_kitchen.py:ro \
  nvcr.io/nvidia/isaac-sim:6.0.0-dev2 \
  ./runheadless.sh \
  --/app/renderer/resolution/width=1280 \
  --/app/renderer/resolution/height=720 \
  --/exts/omni.kit.livestream.webrtc/maxBitrate=5000000 \
  --exec "/isaac-sim/load_kitchen.py"
```

Connect via: **NVIDIA Streaming Client → localhost** (or DCV for remote).

## File Permissions

LeIsaac USD assets have `660` permissions by default. Fix before mounting:

```bash
chmod -R a+r /path/to/leisaac_assets/
```

## Timing

- Container startup: ~35s
- Scene load + shader compile: ~30-60s  
- Physics warm-up (300 steps): ~10s
- Total from `docker run` to interactive: ~70-90s
