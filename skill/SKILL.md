---
name: isaac-sim
description: Control NVIDIA Isaac Sim 6.0 robot simulations with SO-ARM101 in kitchen environments. Use when asked to simulate robots, run pick-and-place tasks, control the SO-101 arm, load LeIsaac kitchen scenes, render simulation frames, stream real-time simulation, record episodes to DynamoDB, or transfer trajectories to real robots via Sim2Real bridge. Supports the LeIsaac kitchen orange-picking demo with physics-based joint control.
---

# Isaac Sim 6.0 — SO-101 Kitchen Simulation

Run headless NVIDIA Isaac Sim simulations via Docker on this server.
Primary demo: SO-ARM101 pick-and-place in LeIsaac kitchen scene.

## Prerequisites

| Component | Required | Check |
|-----------|----------|-------|
| Docker | ≥ 24.x | `docker --version` |
| NVIDIA Container Toolkit | ≥ 1.14 | `nvidia-container-cli --version` |
| Isaac Sim container | `nvcr.io/nvidia/isaac-sim:6.0.0-dev2` | `docker images` |
| NVIDIA GPU | L40S / A100 / etc. | `nvidia-smi` |
| LeIsaac assets | Kitchen + Robot USD | `ls /tmp/leisaac_assets/` |

Cache volumes: `~/docker/isaac-sim/`

## Quick Reference — Scripts

### 1. Download Assets
```bash
bash scripts/leisaac/download_assets.sh
# Downloads kitchen_with_orange.zip + so101_follower.usd
```

### 2. Interactive Streaming (WebRTC)
```bash
bash scripts/leisaac/run_streaming.sh
# Connect: NVIDIA Streaming Client -> localhost (or via DCV -> localhost)
```

### 3. Headless Render
```bash
ASSET_DIR=/tmp/leisaac_assets OUTPUT_DIR=./output bash scripts/leisaac/run_render.sh
```

### 4. Pick-and-Place Animation
The `load_kitchen_scene.py` script loads the scene and runs pick-and-place.
Restart the container to replay:
```bash
docker restart isaac-sim-streaming
```

## Robot Configuration

| Parameter | Value |
|-----------|-------|
| Model | SO-ARM101 (Hiwonder LeRobot) |
| USD | `/tmp/so101_follower.usd` |
| Position | (2.30, -0.55, 0.92) — counter edge |
| Rotation | 180° on Z (face wall/objects) |
| Stiffness | 17.8 |
| Damping | 0.60 |
| Fix method | FixedJoint (world → base) |

### Joints
| Joint | Range (deg) | Description |
|-------|-------------|-------------|
| shoulder_pan | -110 to 110 | Base rotation |
| shoulder_lift | -100 to 100 | Shoulder up/down |
| elbow_flex | -100 to 90 | Elbow bend |
| wrist_flex | -95 to 95 | Wrist pitch |
| wrist_roll | -160 to 160 | Wrist roll |
| gripper | -10 to 100 | Open/close |

## Critical Rules

1. **Never rotate the robot USD** for Y-up→Z-up — internal transforms handle it
2. **Always create FixedJoint** before physics play, or robot falls
3. **FixedJoint localPos0/localRot0 MUST match robot transform** — mismatch = physics explosion
4. **Quaternion for Z rotation**: `Gf.Quatf(cos(angle/2), 0, 0, sin(angle/2))`
5. **Use `drive:angular:physics:targetPosition`** for joint control (needs physics running)
6. **Set `physics:rigidBodyEnabled=False`** for static-only scenes (joints won't move)
7. **Camera: use `.Set()` not `.Add()`** on existing perspective camera ops
8. **No `import omni.X` inside async functions** — causes scoping errors with top-level `omni`
9. **Fix file permissions** (`chmod -R a+r`) on LeIsaac assets before Docker mount

## Scene Coordinates

Kitchen counter (`counter_main_main_group/geometry_1`):
- X: [1.71, 2.75]
- Y: [-0.65, 0.00] (edge at -0.65, wall at 0.00)
- Z: [0.89, 0.92] (top surface = 0.92)

Objects:
- Orange001: (2.13, -0.30, 0.95)
- Orange002: (2.25, -0.33, 0.95)
- Orange003: (2.15, -0.41, 0.94)
- Plate: (2.42, -0.34, 0.96)

## Core API Patterns

### Load Scene + Robot
```python
from isaacsim.core.utils.stage import add_reference_to_stage

add_reference_to_stage("/scene_data/scenes/kitchen_with_orange/scene.usd", "/World/Kitchen")
add_reference_to_stage("/scene_data/robot.usd", "/World/Robot")
```

### Position Robot
```python
xf = UsdGeom.Xformable(robot_prim)
xf.ClearXformOpOrder()
xf.AddTranslateOp().Set(Gf.Vec3d(2.30, -0.55, 0.92))
xf.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, 180))
```

### Fix Root Link (REQUIRED for physics)
```python
import math
angle_rad = math.radians(180)
quat_z = Gf.Quatf(math.cos(angle_rad/2), 0, 0, math.sin(angle_rad/2))

fj = UsdPhysics.FixedJoint.Define(stage, "/World/Robot/FixedJoint")
fj.GetBody1Rel().SetTargets(["/World/Robot/base"])
fj.GetLocalPos0Attr().Set(Gf.Vec3f(2.30, -0.55, 0.92))
fj.GetLocalRot0Attr().Set(quat_z)
fj.GetLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
fj.GetLocalRot1Attr().Set(Gf.Quatf(1, 0, 0, 0))
```

### Set Joint Targets
```python
for prim in Usd.PrimRange(robot_prim):
    if prim.IsA(UsdPhysics.RevoluteJoint):
        name = prim.GetName()
        if name in targets:
            prim.GetAttribute("drive:angular:physics:stiffness").Set(17.8)
            prim.GetAttribute("drive:angular:physics:damping").Set(0.60)
            prim.GetAttribute("drive:angular:physics:targetPosition").Set(targets[name])
```

### Start Physics
```python
omni.timeline.get_timeline_interface().play()
```

## Sim2Real Memory Pipeline

### Record Episode to DynamoDB
```python
from scripts.sim2real.episode_logger import EpisodeLogger
logger = EpisodeLogger()
eid = logger.start_episode(task="pick_orange_to_plate", robot_config={...})
logger.add_waypoint(1, "reach", {"shoulder_pan": -15, ...})
logger.end_episode(success=True)
```

### Transfer to Real Robot
```bash
python scripts/sim2real/bridge.py --task pick_orange_to_plate --execute
```

### Query Knowledge (Bedrock KB)
```bash
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id LXJRX6IS8Z \
  --retrieval-query '{"text": "How to pick orange with SO-101?"}' \
  --region us-west-2
```

## What Does NOT Work in Isaac Sim 6.0

| Approach | Result |
|----------|--------|
| `physxArticulation:fixBase` attribute | Not recognized |
| `PhysxArticulationAPI.GetFixBaseAttr()` | API doesn't exist |
| `physics:kinematicEnabled=True` on base only | Arm collapses |
| `physics:rigidBodyEnabled=False` on all links | Joints don't move |
| Heavy mass (1000kg) on base | Physics explosion |
| FixedJoint with wrong localPos0/localRot0 | Physics explosion |
| `from omni.X import Y` inside async function | Shadows top-level `omni` |

## Docker Container

```bash
docker run -d --name isaac-sim-streaming \
  --gpus all \
  -e "ACCEPT_EULA=Y" -e "PRIVACY_CONSENT=Y" \
  --network=host \
  -v ~/docker/isaac-sim/cache/main:/isaac-sim/.cache:rw \
  -v ~/docker/isaac-sim/cache/computecache:/isaac-sim/.nv/ComputeCache:rw \
  -v /tmp/leisaac_assets:/scene_data/scenes:ro \
  -v /tmp/so101_follower.usd:/scene_data/robot.usd:ro \
  -v /path/to/script.py:/isaac-sim/load_kitchen.py:ro \
  nvcr.io/nvidia/isaac-sim:6.0.0-dev2 \
  ./runheadless.sh \
  --/app/renderer/resolution/width=1280 \
  --/app/renderer/resolution/height=720 \
  --/exts/omni.kit.livestream.webrtc/maxBitrate=5000000 \
  --exec "/isaac-sim/load_kitchen.py"
```

## Safety
- Never use `-u 1234:1234` (causes EULA segfault)
- Always set `ACCEPT_EULA=Y`, `PRIVACY_CONSENT=Y`
- Use `--restart unless-stopped` for streaming containers
- Container startup: ~35s, scene load: ~30-60s, physics warm-up: ~10s
