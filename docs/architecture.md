# System Architecture — Self-improving Physical AI

## Overview

This system bridges simulation and reality through an AI agent that continuously learns from both domains.

### Key Innovation

Unlike traditional sim2real transfer (one-way), this architecture creates a **bidirectional feedback loop**:

1. **Sim → Real**: Transfer validated trajectories, policies, and strategies
2. **Real → Sim**: Feed real-world observations back to improve simulation fidelity
3. **Memory**: Persistent agent memory connects both domains across sessions

## Architecture Layers

### 1. User Layer
- **Telegram** — Natural language interface for commanding robots
- **WebRTC Viewer** — Real-time 3D visualization of simulation
- **Dashboard** — Monitoring metrics, memory state, sim2real gap tracking

### 2. AI Agent Layer (OpenClaw)
- **Orchestrator** — LLM-powered decision engine
- **Isaac Sim Skill** — Controls simulation environment
- **Real Robot Skill** — Controls physical hardware via ROS 2
- **Sim2Real Skill** — Manages transfer, validation, and domain adaptation

### 3. Agent Memory
- **Episodic** — Every task execution logged with full context
- **Semantic** — Learned knowledge (object properties, environment models)
- **Procedural** — Optimized trajectories and calibration data
- **Sim2Real Delta** — Discrepancy tracking between simulation and reality

### 4. Simulation (Digital Twin)
- **NVIDIA Isaac Sim 6.0** — Physics simulation with RTX rendering
- **USD scenes** — Persistent scene format (OpenUSD)
- **Domain Randomization** — Robustness training across variations

### 5. Real Robot System
- **ROS 2** — Robot middleware
- **Robot Drivers** — Franka, UR, custom arms
- **Sensors** — RGB-D cameras, force/torque sensors
- **Grippers** — Parallel, suction, custom end-effectors

### 6. Infrastructure
- **NVIDIA GPU** — RTX rendering + physics simulation
- **WebRTC** — Low-latency streaming
- **OpenUSD** — Scene interchange format

## Self-Improving Cycle

```
PLAN → SIMULATE → VALIDATE → EXECUTE → OBSERVE → LEARN → (repeat)
  ↑                                                    │
  └────────────── Memory Update ───────────────────────┘
```

Each cycle improves:
- **Simulation fidelity** (physics parameters get closer to reality)
- **Task success rate** (strategies refined from experience)
- **Transfer accuracy** (calibration offsets tuned over time)
- **Failure prediction** (agent learns to anticipate real-world issues)
