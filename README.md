<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Sim2Real Robot Platform with Iterative Learning

A **robotics platform** that bridges simulation and reality through iterative learning. An AI agent orchestrates NVIDIA Isaac Sim, controls a SO-ARM101 robot arm, and uses **agent memory** to learn from task execution — tracking success rates, grasp accuracy, and sim-to-real transfer fidelity across iterations.

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

![My Photo](./images/physical-ai-agent.drawio.png)

## Project Structure

```
├── scripts/
│   ├── leisaac/               # Kitchen orange picking (primary demo)
│   │   ├── README.md          # Demo documentation
│   │   ├── download_assets.sh
│   │   ├── run_streaming.sh   # Interactive WebRTC mode
│   │   ├── run_render.sh      # Headless batch render
│   │   ├── load_kitchen_scene.py
│   │   ├── render_kitchen.py
│   │   └── pick_and_place.py  # 10-waypoint pick animation
│   ├── sim2real/              # Sim2Real memory pipeline
│   │   ├── README.md          # Architecture & setup
│   │   ├── episode_logger.py  # DynamoDB episode recorder
│   │   ├── bridge.py          # Trajectory transfer to real robot
│   │   └── mcp_config.json    # AWS MCP server configuration
│   ├── so101/                 # SO-101 digital twin scripts
│   │   ├── sim_so101.py       # Basic simulation
│   │   ├── sim2real_bridge.py # Sim2Real translation layer
│   │   ├── render_scene.py
│   │   └── render_v3.py
│   ├── manufacturing_scene.py # Factory environment setup
│   ├── pick_and_place.py      # Pick-and-place controller
│   ├── robot_control.py       # General robot control
│   ├── spawn_objects.py       # Object spawning
│   ├── capture_viewport.py    # Camera capture
│   ├── load_scene_streaming.py
│   └── run_sim.sh             # Docker container wrapper
├── infra/
│   └── cloudformation.yaml    # AWS stack (DynamoDB, OpenSearch, Bedrock KB)
├── models/
│   └── so101/                 # SO-ARM101 URDF model
│       ├── so_arm101.urdf
│       └── README.md
├── skill/
│   ├── SKILL.md               # OpenClaw Isaac Sim skill definition
│   └── LEISAAC_API.md         # Isaac Sim 6.0 API reference
├── docs/
│   ├── architecture.md
│   └── THREAT_MODEL.md
├── configs/
│   └── docker_run.env         # Docker environment variables
├── SECURITY.md                # Security policy & vulnerability reporting
├── CONTRIBUTING.md            # Contribution guidelines
├── CODE_OF_CONDUCT.md         # Code of conduct
└── LICENSE                    # MIT-0 license
```

## Deployed AWS Infrastructure

The platform uses AWS services for persistent simulation memory and knowledge retrieval:

| Component | Service | Purpose |
|-----------|---------|---------|
| Episode Store | DynamoDB (`sim-episodes`) | Stores simulation trajectories, success/failure, robot configs |
| Knowledge Docs | S3 | Simulation strategies, API reference, Sim2Real design docs |
| Vector Search | OpenSearch Serverless | Embedding store for RAG retrieval |
| Knowledge Base | Amazon Bedrock KB | RAG over simulation knowledge (Titan Embed v2) |
| MCP Servers | [awslabs/mcp](https://github.com/awslabs/mcp) | Tool access for agents (DynamoDB, Bedrock KB, S3) |

### Deploy Infrastructure

```bash
aws cloudformation create-stack \
  --stack-name physical-ai-sim-memory \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

### Sim2Real Memory Pipeline

```
Isaac Sim (simulation) ──▶ DynamoDB (episodes) ──▶ Real Robot (LeRobot)
         │                        │                        │
         ▼                        ▼                        ▼
    S3 (knowledge) ──────▶ Bedrock KB (RAG) ──────▶ MCP Server (tools)
```

**Record simulation episodes:**
```python
from scripts.sim2real.episode_logger import EpisodeLogger
logger = EpisodeLogger()
eid = logger.start_episode(task="pick_orange_to_plate", robot_config={...})
logger.add_waypoint(1, "reach", {"shoulder_pan": -15, ...})
logger.end_episode(success=True, metrics={"time": 50.0})
```

**Transfer to real robot:**
```bash
python scripts/sim2real/bridge.py --task pick_orange_to_plate --dry-run
python scripts/sim2real/bridge.py --task pick_orange_to_plate --execute
```

See [scripts/sim2real/README.md](scripts/sim2real/README.md) for full details.

## Key Concepts

### Self-Improving Loop

1. **Simulate** — Run task in Isaac Sim (pick orange → place in bowl)
2. **Evaluate** — Agent reviews success/failure, logs to episodic memory
3. **Adapt** — Modify strategy (grasp angle, approach vector, timing)
4. **Transfer** — Deploy refined policy to real SO-101 via Sim2Real bridge
5. **Learn** — Real-world feedback updates agent's semantic memory

### Sim2Real Bridge

The bridge (`scripts/sim2real/bridge.py`) translates between:
- Isaac Sim joint positions ↔ LeRobot servo commands
- Simulated camera frames ↔ Real USB camera feeds
- Physics-based collision detection ↔ Force/torque sensing

### MCP Integration

The [AWS MCP servers](https://github.com/awslabs/mcp) provide tool access for coding agents:
- **DynamoDB MCP** — Query/write simulation episodes
- **Bedrock KB MCP** — RAG retrieval over simulation knowledge
- **S3 MCP** — Read knowledge documents

## Quick Start (Full Setup)

```bash
# Prerequisites: Docker, NVIDIA GPU driver 550+, nvidia-container-toolkit

# 1. Clone
git clone https://github.com/aws-samples/sample-self-improving-physical-AI.git
cd sample-self-improving-physical-AI

# 2. Download assets
bash scripts/leisaac/download_assets.sh

# 3. Run demo
bash scripts/leisaac/run_streaming.sh

# 4. (Optional) Headless render
ASSET_DIR=/tmp/leisaac_assets OUTPUT_DIR=./output bash scripts/leisaac/run_render.sh

# 5. (Optional) Deploy memory pipeline
aws cloudformation create-stack \
  --stack-name physical-ai-sim-memory \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

## References

- [LightwheelAI/leisaac](https://github.com/LightwheelAI/leisaac) — Isaac Lab + SO-101 teleoperation
- [AWS Physical AI Blog](https://aws.amazon.com/blogs/physical-ai/embodied-ai-blog-series-part-1/) — Embodied AI platform
- [AWS MCP Servers](https://github.com/awslabs/mcp) — Open source MCP servers for AWS
- [HuggingFace LeRobot](https://github.com/huggingface/lerobot) — Open-source robot learning
- [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim) — Robot simulation
- [OpenClaw](https://github.com/openclaw/openclaw) — AI agent framework

## License

This project is licensed under the [MIT-0 (MIT No Attribution)](LICENSE) license.

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
