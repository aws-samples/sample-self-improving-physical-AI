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
  ├── LLM Backend: Hermes Agent or OpenClaw (any model provider)
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
