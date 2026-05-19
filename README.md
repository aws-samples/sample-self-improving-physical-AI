# Self-improving Physical AI — Sim2Real Robot Platform

A **self-improving robotics platform** that bridges simulation and reality. An AI agent orchestrates NVIDIA Isaac Sim, controls a SO-ARM101 robot arm, and uses **agent memory** to continuously learn from task execution.

Built on [OpenClaw](https://github.com/openclaw/openclaw) + Telegram for natural language robot control.

## Demo: Kitchen Orange Picking

SO-ARM101 picks oranges from a kitchen counter in Isaac Sim, using [LeIsaac](https://github.com/LightwheelAI/leisaac) assets.

```bash
# 1. Download scene assets (kitchen USD + SO-101 robot)
bash scripts/leisaac/download_assets.sh

# 2. Run interactive streaming
bash scripts/leisaac/run_streaming.sh

# 3. Connect: NVIDIA Streaming Client -> localhost
```

See [scripts/leisaac/README.md](scripts/leisaac/README.md) for full details.

## Architecture

```
┌───────────────────────────────────────────────────────┐
│  User Layer                                           │
│  📱 Telegram (NL commands) │ 💻 Streaming Client      │
└──────────────────┬────────────────────────────────────┘
                   │
┌──────────────────┴────────────────────────────────────┐
│  AI Agent (OpenClaw)                                  │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ Isaac Sim  │ │ Sim2Real   │ │ Agent Memory     │  │
│  │ Skill      │ │ Bridge     │ │ (Episodic/Proc)  │  │
│  └────────────┘ └────────────┘ └──────────────────┘  │
└──────────────────┬────────────────────────────────────┘
                   │
┌──────────────────┴────────────────────────────────────┐
│  Simulation (Isaac Sim 6.0, Docker)                   │
│  • LeIsaac Kitchen Scene (USD) + SO-101 Robot         │
│  • PhysX rigid body physics                           │
│  • RTX ray-traced rendering                           │
│  • WebRTC streaming (60fps)                           │
└──────────────────┬────────────────────────────────────┘
                   │ Sim2Real Transfer
┌──────────────────┴────────────────────────────────────┐
│  Real Robot (SO-ARM101 / LeRobot)                     │
│  • HuggingFace LeRobot control                        │
│  • Dual camera (front + wrist)                        │
│  • Joint-level position control                       │
└───────────────────────────────────────────────────────┘
```

## Project Structure

```
├── scripts/
│   ├── leisaac/              # Kitchen orange picking (primary demo)
│   │   ├── README.md         # Demo documentation
│   │   ├── download_assets.sh
│   │   ├── run_streaming.sh  # Interactive WebRTC mode
│   │   ├── run_render.sh     # Headless batch render
│   │   ├── load_kitchen_scene.py
│   │   └── render_kitchen.py
│   ├── so101/                # SO-101 digital twin scripts
│   │   ├── sim_so101.py      # Basic simulation
│   │   ├── sim2real_bridge.py
│   │   ├── render_scene.py
│   │   └── render_v3.py
│   ├── manufacturing_scene.py
│   ├── pick_and_place.py
│   ├── robot_control.py
│   ├── spawn_objects.py
│   ├── capture_viewport.py
│   └── run_sim.sh
├── models/
│   └── so101/                # SO-ARM101 URDF model
│       ├── so_arm101.urdf
│       └── README.md
├── skill/
│   └── SKILL.md              # OpenClaw Isaac Sim skill
├── docs/
│   ├── architecture.md
│   └── THREAT_MODEL.md
└── configs/
    └── docker_run.env        # Docker environment template
```

## Infrastructure

| Component | Spec |
|-----------|------|
| GPU | NVIDIA L40S 48GB |
| Instance | AWS EC2 G7e |
| Simulator | Isaac Sim 6.0.0 (Docker) |
| Robot | SO-ARM101 (Hiwonder LeRobot) |
| Agent | OpenClaw + Claude |
| Messaging | Telegram bot |

## Key Concepts

### Self-Improving Loop

1. **Simulate** — Run task in Isaac Sim (pick orange → place in bowl)
2. **Evaluate** — Agent reviews success/failure, logs to episodic memory
3. **Adapt** — Modify strategy (grasp angle, approach vector, timing)
4. **Transfer** — Deploy refined policy to real SO-101 via Sim2Real bridge
5. **Learn** — Real-world feedback updates agent's semantic memory

### Sim2Real Bridge

The bridge (`scripts/so101/sim2real_bridge.py`) translates between:
- Isaac Sim joint positions ↔ LeRobot servo commands
- Simulated camera frames ↔ Real USB camera feeds
- Physics-based collision detection ↔ Force/torque sensing

## Quick Start (Full Setup)

```bash
# Prerequisites: Docker, NVIDIA GPU driver 550+, nvidia-container-toolkit

# 1. Clone
git clone https://github.com/aws-samples/sample-self-improving-physical-AI.git
cd Self-improving-Physical-AI

# 2. Download assets
bash scripts/leisaac/download_assets.sh

# 3. Run demo
bash scripts/leisaac/run_streaming.sh

# 4. (Optional) Headless render
ASSET_DIR=/tmp/leisaac_assets OUTPUT_DIR=./output bash scripts/leisaac/run_render.sh
```

## References

- [LightwheelAI/leisaac](https://github.com/LightwheelAI/leisaac) — Isaac Lab + SO-101 teleoperation
- [AWS Physical AI Blog](https://aws.amazon.com/blogs/physical-ai/embodied-ai-blog-series-part-1/) — Embodied AI platform
- [HuggingFace LeRobot](https://github.com/huggingface/lerobot) — Open-source robot learning
- [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim) — Robot simulation
- [OpenClaw](https://github.com/openclaw/openclaw) — AI agent framework

## License

MIT
