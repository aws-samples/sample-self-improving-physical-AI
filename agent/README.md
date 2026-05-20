# Agent Layer

This directory contains the AI agent infrastructure that orchestrates the Physical AI platform.

## Components

### [OpenClaw](./openclaw/)
Personal AI agent framework. Provides:
- Natural language → robot control (via Telegram)
- Skills system for Isaac Sim knowledge
- MCP server integration (DynamoDB, Bedrock KB)
- Agent memory for continuous improvement

### [Hermes 3](./hermes/)
Self-improving AI agent (Nous Research). Provides:
- Auto skill creation from task outcomes
- Cross-session memory with learning loop
- Subagent delegation for parallel simulation
- 20+ model providers (Bedrock, OpenRouter, Ollama, etc.)

### [Bedrock Converse](./bedrock-converse/)
AWS-native agent using Bedrock Converse API for physical robot control. Provides:
- Natural language → robot control (via browser chat UI)
- Multi-agent architecture (Act, Perception, Governance)
- AWS IoT Core integration for real-time device commands
- Hardware registry supporting multiple robot platforms (Zumi, XGO2)
- FastAPI server with single-file chat UI

### [AWS Deployment](./aws-deployment/)
Complete deployment guide for running the full stack on AWS:
- EC2 GPU instance setup
- IAM roles and permissions
- Memory pipeline (DynamoDB + OpenSearch + Bedrock KB)
- Networking and security

## How They Work Together

```
User (natural language)
  │
  ├──► OpenClaw (Telegram) ──► Isaac Sim / Real Robot (ROS 2)
  │
  ├──► Bedrock Converse (Browser) ──► IoT Core ──► Zumi / XGO2
  │
  └──► Hermes (any frontend) ──► Self-improving loop
        │
        ▼
  AWS Infrastructure
  (GPU compute, memory pipeline, knowledge base, IoT Core)
```

## Quick Start

### Simulation Path (OpenClaw + Isaac Sim)
1. Deploy AWS infrastructure → `aws-deployment/README.md`
2. Install OpenClaw → `openclaw/README.md`
3. (Optional) Self-host Hermes 3 → `hermes/README.md`
4. Configure skills and MCP servers
5. Send commands via Telegram

### Physical Robot Path (Bedrock Converse + IoT)
1. Provision IoT device → `iot/provisioning/`
2. Deploy device code → `example/zumi/` or `example/xgo2/`
3. Start the agent → `bedrock-converse/README.md`
4. Open browser chat UI and send commands
