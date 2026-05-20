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
Open-weight agentic LLM (Nous Research). Provides:
- Function calling for robot tool use
- Structured output (joint configs, waypoints)
- Task decomposition and planning
- Self-hostable (no API dependency)

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
  ▼
OpenClaw Agent (orchestration)
  │
  ├── LLM Backend: Hermes 3 (self-hosted) or Claude/GPT (API)
  │
  ├── Skills: Isaac Sim control, Sim2Real commands
  │
  ├── MCP Tools: DynamoDB queries, Bedrock KB retrieval
  │
  └── Output: Simulation scripts / Real robot commands
        │
        ▼
  AWS Infrastructure
  (GPU compute, memory pipeline, knowledge base)
```

## Quick Start

1. Deploy AWS infrastructure → `aws-deployment/README.md`
2. Install OpenClaw → `openclaw/README.md`
3. (Optional) Self-host Hermes 3 → `hermes/README.md`
4. Configure skills and MCP servers
5. Send commands via Telegram
