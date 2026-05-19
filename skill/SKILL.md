# Isaac Sim 6.0 + LeIsaac SO-101 Skill

## Description
Load, position, and control the SO-ARM101 robot in NVIDIA Isaac Sim 6.0 with the LeIsaac kitchen scene for orange-picking tasks.

## Prerequisites
- NVIDIA GPU with driver 550+
- Docker with nvidia-container-toolkit
- Isaac Sim 6.0 image: `nvcr.io/nvidia/isaac-sim:6.0.0-dev2`
- LeIsaac assets (download via `scripts/leisaac/download_assets.sh`)

## Quick Commands

### Start Interactive Scene
```bash
bash scripts/leisaac/run_streaming.sh
```

### Render Static Images
```bash
ASSET_DIR=/tmp/leisaac_assets OUTPUT_DIR=./output bash scripts/leisaac/run_render.sh
```

## Key APIs

See [LEISAAC_API.md](LEISAAC_API.md) for complete API reference including:
- Robot placement (position + rotation)
- Fix root link via FixedJoint
- Joint control (stiffness/damping/targets)
- Camera manipulation
- Physics enable/disable

## Critical Rules

1. **Never rotate the robot USD** for Y-up to Z-up conversion — it's already correct
2. **Always create FixedJoint** before playing physics, or robot will fall
3. **Match FixedJoint localPos0/localRot0** exactly to robot transform, or physics explodes
4. **Use `drive:angular:physics:targetPosition`** for joint control (requires physics running)
5. **Set `physics:rigidBodyEnabled=False`** on all links for static-only scenes
6. **Camera ops: use `.Set()` not `.Add()`** on existing perspective camera
7. **Fix file permissions** (`chmod -R a+r`) on LeIsaac assets before Docker mount

## Safety
- Always use `--restart unless-stopped` for streaming containers
- Never use `-u 1234:1234` (causes EULA segfault)
- Always set `ACCEPT_EULA=Y`, `PRIVACY_CONSENT=Y`, `OMNI_KIT_ACCEPT_EULA=YES`
