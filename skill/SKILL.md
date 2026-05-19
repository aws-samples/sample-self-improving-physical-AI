<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

---
name: isaac-sim
description: Control NVIDIA Isaac Sim robot simulations for manufacturing scenarios. Use when asked to simulate robots, create manufacturing scenes, perform pick-and-place operations, control robot arms, spawn objects in simulation, capture simulation screenshots, or any robot simulation task. Supports Franka Panda and UR10 robot arms in factory/warehouse environments with conveyors, shelving, and industrial props.
---

# Isaac Sim – Manufacturing Robot Simulation

Run headless NVIDIA Isaac Sim simulations via Docker on this server.  
All scripts live in `/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/`.  
The `run_sim.sh` wrapper handles the Docker container lifecycle automatically.

## Prerequisites

| Component | Required | Check |
|-----------|----------|-------|
| Docker | ≥ 24.x | `docker --version` |
| NVIDIA Container Toolkit | ≥ 1.14 | `nvidia-container-cli --version` |
| Isaac Sim container | `nvcr.io/nvidia/isaac-sim:6.0.0-dev2` | `docker images nvcr.io/nvidia/isaac-sim:6.0.0-dev2` |
| NVIDIA GPU | L40S / A100 / etc. | `nvidia-smi` |

Cache volumes live at `~/docker/isaac-sim/` (owned by UID 1234).

## Quick Reference – Scripts

### 1. Manufacturing Scene (`manufacturing_scene.py`)

Creates a full factory environment: ground plane, conveyor belt, shelving racks, Franka Panda robot arm, boxes on the conveyor, work table, industrial lighting.

```bash
# Basic scene creation (200 sim steps)
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh manufacturing_scene.py --steps 200

# Save as USD + capture image
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh manufacturing_scene.py \
  --save-usd /output/factory.usd \
  --capture /output/factory_scene.png \
  --steps 200
```

### 2. Pick and Place (`pick_and_place.py`)

Commands the Franka Panda to pick a box from the conveyor and place it at a target location. Uses Isaac Sim's built-in `PickPlaceController`.

```bash
# Default pick-and-place
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh pick_and_place.py

# Pick box index 2, place at custom position
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh pick_and_place.py \
  --pick-index 2 \
  --place-pos "0.5,-0.8,0.5" \
  --steps 2000 \
  --capture /output/pick_place_result.png
```

**Arguments:**
- `--pick-index N` – Which conveyor box to pick (0-3)
- `--place-pos "x,y,z"` – Target placement position
- `--steps N` – Max simulation steps (default: 2000)
- `--capture PATH` – Save final state image

### 3. Robot Control (`robot_control.py`)

General-purpose Franka Panda control with four actions:

```bash
# Return to home position
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh robot_control.py --action home

# Move to specific joint positions (7 DOF)
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh robot_control.py \
  --action move_joint \
  --joints "0.0,0.5,0.0,-1.0,0.0,1.5,0.8"

# Move end effector to Cartesian target (uses RMPFlow)
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh robot_control.py \
  --action move_to \
  --target "0.4,0.0,0.4"

# Gripper control
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh robot_control.py --action gripper --state open
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh robot_control.py --action gripper --state close
```

**Output:** Prints a `STATE_JSON:{...}` line with joint positions, velocities, and gripper state. Use `--output /output/state.json` to save to file.

### 4. Spawn Objects (`spawn_objects.py`)

Spawn primitive objects (box, cylinder, sphere) with physics.

```bash
# Single box at a position
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh spawn_objects.py \
  --type box --position "0.3,0.0,1.0" --scale "0.1,0.1,0.1"

# 10 random spheres in an area
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh spawn_objects.py \
  --type sphere --count 10 --area "-1,1,-1,1" --height 1.5

# Static colored cylinder
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh spawn_objects.py \
  --type cylinder --position "0.5,0.5,0.5" --color "1.0,0.0,0.0" --static
```

**Arguments:**
- `--type box|cylinder|sphere`
- `--position "x,y,z"` – Exact position (for single objects)
- `--scale "x,y,z"` – Object dimensions (default: 0.05 each)
- `--color "r,g,b"` – RGB color (0-1 range)
- `--count N` – Number of objects
- `--area "xmin,xmax,ymin,ymax"` – Random spawn bounds
- `--height H` – Spawn height for random objects
- `--mass M` – Object mass in kg (default: 0.2)
- `--static` – No physics (visual only)
- `--seed N` – Reproducible random placement

### 5. Capture Viewport (`capture_viewport.py`)

Render a camera image from the simulation. Can load the manufacturing scene or a custom USD file.

```bash
# Capture manufacturing scene
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh capture_viewport.py \
  --output /output/scene.png \
  --scene manufacturing

# Custom camera angle
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh capture_viewport.py \
  --output /output/closeup.png \
  --scene manufacturing \
  --eye "1.0,-1.0,1.0" \
  --target "0.0,0.0,0.5" \
  --resolution "2560,1440"

# Empty scene
/home/ubuntu/.openclaw/workspace/isaac-sim-demo/scripts/run_sim.sh capture_viewport.py \
  --output /output/empty.png --scene empty
```

**Arguments:**
- `--output PATH` – Image output path (required; use `/output/` inside container)
- `--eye "x,y,z"` – Camera position
- `--target "x,y,z"` – Camera look-at point
- `--resolution "W,H"` – Image resolution (default: 1920×1080)
- `--focal-length F` – Lens focal length in mm (default: 24)
- `--scene empty|manufacturing|custom`
- `--usd-path PATH` – Path to custom USD file (with `--scene custom`)
- `--warm-up-steps N` – Render warm-up frames (default: 30)

## Typical Workflows

### Create and Capture a Manufacturing Scene

```bash
# 1. Create the scene and capture an image
run_sim.sh manufacturing_scene.py --steps 200 --capture /output/factory.png

# 2. The image is at isaac-sim-demo/output/factory.png
# Return it to the user with the read tool
```

### Robot Pick and Place Demo

```bash
# 1. Run the pick-and-place
run_sim.sh pick_and_place.py --pick-index 0 --capture /output/result.png

# 2. Show the result image
```

### Interactive Robot Control

```bash
# 1. Home the robot
run_sim.sh robot_control.py --action home

# 2. Move to a position
run_sim.sh robot_control.py --action move_to --target "0.4,0.0,0.4"

# 3. Close gripper
run_sim.sh robot_control.py --action gripper --state close
```

## Output Files

All outputs (images, USD files, JSON state) go to:
`/home/ubuntu/.openclaw/workspace/isaac-sim-demo/output/`

This directory is mounted as `/output/` inside the container. To return images to the user, use the `read` tool on the output file path.

## Intent Mapping

| User Says | Script | Key Args |
|-----------|--------|----------|
| "create a factory scene" | `manufacturing_scene.py` | `--steps 200` |
| "show me the simulation" / "capture" / "screenshot" | `capture_viewport.py` | `--output /output/scene.png` |
| "pick up a box" / "pick and place" | `pick_and_place.py` | `--pick-index`, `--place-pos` |
| "move the robot arm" / "move to position" | `robot_control.py` | `--action move_to --target` |
| "set joint angles" | `robot_control.py` | `--action move_joint --joints` |
| "open/close gripper" | `robot_control.py` | `--action gripper --state` |
| "home the robot" / "reset robot" | `robot_control.py` | `--action home` |
| "add boxes" / "spawn objects" | `spawn_objects.py` | `--type`, `--count`, `--position` |
| "drop random objects" | `spawn_objects.py` | `--type sphere --count N` |


## Notes

- All simulation is **headless** (no display required).
- First run of each script is slower due to shader compilation and asset loading. Subsequent runs use cached data in `~/docker/isaac-sim/cache/`.
- The `run_sim.sh` wrapper auto-creates and removes containers. Set `KEEP_CONTAINER=1` to preserve them for debugging.
- Isaac Sim uses Nucleus for asset paths. Cloud-based assets require internet access on first load.
- Each script is self-contained: it creates its own scene, runs, and exits. For persistent scenes, save as USD with `--save-usd` and reload with `capture_viewport.py --usd-path`.
