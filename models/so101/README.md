<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# SO-ARM101 Digital Twin

This directory contains the simulation model and scripts for the **Hiwonder LeRobot SO-ARM101** (also known as SO-101) 6-DOF robotic arm.

## Licensing

The SO-ARM101 URDF model (`so_arm101.urdf`) is derived from the [SO-ARM100 project](https://github.com/TheRobotStudio/SO-ARM100) and is licensed under **CC BY-SA 4.0**. Attribution: © The Robot Studio. Derivative works based on this URDF model must be distributed under the same CC BY-SA 4.0 license. The remainder of this project's code is licensed under MIT-0 (see root LICENSE file).

## Hardware Specs

| Property | Value |
|----------|-------|
| DOF | 6 (5 arm joints + 1 gripper) |
| Servos | Feetech STS3215 (30KG, magnetic feedback) |
| Reach | ~280mm |
| Weight | ~1.2kg |
| Interface | USB (TTL bus servo protocol) |
| Cameras | Dual — gripper-mounted + external overhead |
| Framework | HuggingFace LeRobot |

## Joint Mapping

| Joint | Name | Axis | Range | Function |
|-------|------|------|-------|----------|
| 1 | Base | Z | ±180° | Base rotation (yaw) |
| 2 | Shoulder | Y | ±90° | Shoulder pitch |
| 3 | Elbow | Y | ±90° | Elbow pitch |
| 4 | Wrist Pitch | Y | ±90° | Wrist up/down |
| 5 | Wrist Roll | Z | ±180° | Wrist rotation |
| 6 | Gripper | Y | 0-45° | Open/close |

## Files

```
models/so101/
├── so_arm101.urdf          # Robot description (URDF)
└── README.md               # This file

scripts/so101/
├── sim_so101.py            # Isaac Sim digital twin
└── sim2real_bridge.py      # Real robot ↔ sim bridge
```

## Usage

### Create Scene & Capture Photo
```bash
./scripts/run_sim.sh scripts/so101/sim_so101.py --action scene --output /output
```

### Capture from Specific Camera
```bash
# Gripper camera (what the robot sees)
./scripts/run_sim.sh scripts/so101/sim_so101.py --action photo --camera gripper

# External overhead camera
./scripts/run_sim.sh scripts/so101/sim_so101.py --action photo --camera external

# Side view (for visualization)
./scripts/run_sim.sh scripts/so101/sim_so101.py --action photo --camera side
```

### Record Video
```bash
./scripts/run_sim.sh scripts/so101/sim_so101.py --action video --camera side --duration 5
```

### Move Joints
```bash
# Move to specific joint positions (6 values in radians)
./scripts/run_sim.sh scripts/so101/sim_so101.py --action move --joints "0,0.5,-0.3,-0.2,0,0.6"
```

### Run Pick-and-Place Demo
```bash
./scripts/run_sim.sh scripts/so101/sim_so101.py --action demo
```

### Save as USD
```bash
./scripts/run_sim.sh scripts/so101/sim_so101.py --action scene --save-usd /output/so101_scene.usd
```

## Sim2Real Bridge

### Check Connection
```bash
python scripts/so101/sim2real_bridge.py --mode info
```

### Calibrate (First Time)
```bash
python scripts/so101/sim2real_bridge.py --mode calibrate
```

### Sync Real → Sim
```bash
python scripts/so101/sim2real_bridge.py --mode sync
```

### Record Episode from Real Robot
```bash
python scripts/so101/sim2real_bridge.py --mode record --duration 10
```

## Camera System

The SO-ARM101 uses a **dual-camera system** matching the real hardware:

1. **Gripper Camera** — Mounted on the end effector, provides close-up view for manipulation tasks. Used for precise grasping and visual servoing.

2. **External Camera** — Overhead/side view of the workspace. Provides context for the AI agent about the overall scene layout.

Both cameras in simulation match the real hardware resolution (640×480) and framerate (30fps) for direct sim2real transfer of vision policies.

## LeRobot Integration

This digital twin is designed to work with the [HuggingFace LeRobot](https://github.com/huggingface/lerobot) ecosystem:

1. **Data Collection**: Record teleoperation episodes from the real robot
2. **Training**: Train ACT/Diffusion/VLA policies on collected data
3. **Sim Validation**: Test policies in Isaac Sim before deploying to real hardware
4. **Deployment**: Deploy trained policies to real SO-ARM101

```python
from lerobot.robots.so100 import SO100Robot

robot = SO100Robot(config=...)
robot.connect()

# Collect data via teleoperation
# Train policy (ACT, Diffusion, Pi0, etc.)
# Validate in sim
# Deploy to real robot
```



