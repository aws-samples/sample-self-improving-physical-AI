# LeIsaac Kitchen Orange Picking Demo

SO-ARM101 (LeRobot) picks oranges from a kitchen counter — powered by [LightwheelAI/leisaac](https://github.com/LightwheelAI/leisaac) assets on NVIDIA Isaac Sim 6.0.

## Overview

This demo recreates the kitchen orange-picking task from the [AWS Physical AI Blog Series](https://aws.amazon.com/blogs/physical-ai/embodied-ai-blog-series-part-1/) using:

- **Scene**: LeIsaac kitchen with oranges, plate, and full kitchen fixtures (cabinets, stove, fridge, microwave)
- **Robot**: SO-101 Follower (6-DOF arm with gripper) from [HuggingFace LeRobot](https://github.com/huggingface/lerobot)
- **Simulator**: NVIDIA Isaac Sim 6.0 (Docker, headless or WebRTC streaming)
- **Infrastructure**: AWS EC2 G7e (NVIDIA L40S 48GB)

## Quick Start

### 1. Download Assets

```bash
bash scripts/leisaac/download_assets.sh /tmp/leisaac_assets
```

This downloads from [LightwheelAI/leisaac v0.1.0](https://github.com/LightwheelAI/leisaac/releases/tag/v0.1.0):
- `kitchen_with_orange.zip` (70MB) — Full kitchen USD scene with textures
- `so101_follower.usd` (23MB) — SO-101 robot model

### 2a. Interactive Streaming (recommended)

```bash
bash scripts/leisaac/run_streaming.sh
```

Then connect with **NVIDIA Streaming Client** → `localhost` (or via NICE DCV for remote access).

### 2b. Headless Render

```bash
ASSET_DIR=/tmp/leisaac_assets OUTPUT_DIR=./output bash scripts/leisaac/run_render.sh
```

Outputs 4 viewpoint images + USD file to `./output/`.

## Scene Layout

```
Kitchen Counter (Z=0.87m)
├── SO-101 Robot (2.7, -0.35, 0.87) — facing left toward oranges
├── Orange 1    (2.13, -0.30, 0.95)
├── Orange 2    (2.25, -0.33, 0.95)  
├── Orange 3    (2.15, -0.41, 0.94)
└── Plate/Bowl  (2.42, -0.34, 0.96) — target placement
```

The robot reaches ~280mm, placing it within grasp range of all three oranges.

## Architecture

```
┌─────────────────────────────────────────┐
│  NVIDIA Isaac Sim 6.0 (Docker)          │
│  ┌──────────┐  ┌───────────────────┐    │
│  │ Kitchen  │  │ SO-101 Robot      │    │
│  │ USD Scene│  │ (so101_follower)  │    │
│  └──────────┘  └───────────────────┘    │
│  ┌──────────┐  ┌───────────────────┐    │
│  │ PhysX    │  │ RTX Ray Tracing   │    │
│  │ Physics  │  │ Renderer          │    │
│  └──────────┘  └───────────────────┘    │
└────────────────┬────────────────────────┘
                 │ WebRTC / Headless
┌────────────────┴────────────────────────┐
│  AI Agent (OpenClaw)                     │
│  • Natural language control (Telegram)   │
│  • Sim2Real bridge (LeRobot)             │
│  • Agent memory (episodic/semantic)      │
└──────────────────────────────────────────┘
```

## Key Technical Notes

- **Up-axis conversion**: `so101_follower.usd` uses Y-up; scene is Z-up. Apply `RotateXYZ(-90, 0, -90)` to stand robot upright and face oranges.
- **Counter height**: 0.87m (standard kitchen counter in the LeIsaac scene)
- **Warm-up**: RTX renderer needs 200-300 physics steps before capturing clean frames (shader compilation + ray convergence)
- **Permissions**: USD asset files may have restrictive permissions (660); run `chmod -R a+r` on asset directory for Docker access.
- **PhysX warnings**: Joint/collision errors in logs are harmless (static body joints, mesh → convexHull fallback).

## Connection Methods

| Method | Use Case | Latency |
|--------|----------|---------|
| Streaming Client → localhost | Same machine | <1ms |
| DCV → Streaming Client | Remote (SSH tunnel for DCV) | ~30ms |
| Headless render | CI/CD, batch capture | N/A |

## References

- [LightwheelAI/leisaac](https://github.com/LightwheelAI/leisaac) — IsaacLab teleoperation with SO-101
- [AWS Physical AI Blog Part 1](https://aws.amazon.com/blogs/physical-ai/embodied-ai-blog-series-part-1/) — Embodied AI platform architecture
- [HuggingFace LeRobot](https://github.com/huggingface/lerobot) — Open-source robot learning framework
- [SO-ARM100/101](https://github.com/TheRobotStudio/SO-ARM100) — Robot hardware specs
