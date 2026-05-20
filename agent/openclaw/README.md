# OpenClaw — Personal AI Agent for Robot Control

[OpenClaw](https://github.com/openclaw/openclaw) is the AI agent framework that orchestrates this platform. It provides natural language robot control via Telegram, manages simulation workflows, and maintains agent memory for continuous improvement.

## Role in This Project

```
User (Telegram) → OpenClaw Agent → Isaac Sim (simulation)
                                  → DynamoDB (memory)
                                  → Bedrock KB (knowledge)
                                  → Real Robot (execution)
```

OpenClaw acts as the **central intelligence layer**:
- Receives natural language commands via Telegram
- Translates intent into Isaac Sim simulation scripts
- Records episodes and learns from outcomes
- Queries past experience via MCP servers
- Transfers successful strategies to real hardware

## Installation

### Quick Install (macOS / Linux)
```bash
curl -fsSL https://openclaw.ai/install.sh | bash
openclaw onboard --install-daemon
```

### Docker (for server/VPS deployment)
```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw
./scripts/docker/setup.sh
```

### Verify
```bash
openclaw gateway status
openclaw dashboard  # opens Control UI at http://localhost:18789
```

## Configuration for Physical AI

### Model Setup
```bash
# During onboarding, select a model provider (Anthropic, OpenAI, Google, etc.)
# Recommended: Claude Sonnet/Opus for complex robotics reasoning
openclaw onboard
```

### Telegram Channel
```bash
# 1. Create bot via @BotFather on Telegram
# 2. Add channel
openclaw channels add --channel telegram --token "<BOT_TOKEN>"
```

### Skills
Copy the `skill/` directory from this repo into your OpenClaw workspace:
```bash
cp -r skill/ ~/.openclaw/workspace/skills/isaac-sim/
```

This gives the agent knowledge of:
- Isaac Sim 6.0 API and Docker setup
- SO-101 robot configuration and joint control
- LeIsaac kitchen scene coordinates
- Sim2Real memory pipeline commands

### MCP Server Integration
Add to OpenClaw config for agent tool access:
```json
{
  "mcp": {
    "servers": {
      "dynamodb": {
        "command": "uvx",
        "args": ["awslabs.dynamodb-mcp-server@latest"],
        "env": {"AWS_REGION": "us-west-2"}
      },
      "bedrock-kb": {
        "command": "uvx",
        "args": ["awslabs.bedrock-kb-retrieval-mcp-server@latest"],
        "env": {"AWS_REGION": "us-west-2"}
      }
    }
  }
}
```

## Agent Workflow

### 1. Natural Language → Simulation
User says: "Pick the orange and put it on the plate"
→ Agent generates Isaac Sim script with correct joint waypoints

### 2. Simulation → Memory
Agent records episode:
- Joint trajectories at each waypoint
- Success/failure outcome
- Timing and metrics

### 3. Memory → Improvement
Agent queries past episodes:
- "What grasp angle worked best for oranges?"
- Adjusts strategy based on historical success rates

### 4. Simulation → Real Robot
Agent uses `bridge.py` to transfer validated trajectories:
- Safety scaling applied (0.9x joint angles, 0.8x gripper)
- Slower execution speed on real hardware

## Key Features Used

| Feature | Usage |
|---------|-------|
| Telegram channel | Natural language robot commands |
| Skills system | Isaac Sim API knowledge |
| MCP servers | DynamoDB + Bedrock KB tool access |
| Cron jobs | Periodic simulation health checks |
| Agent memory | Long-term learning from experiments |
| Exec tool | Docker container management |

## References

- [OpenClaw Docs](https://docs.openclaw.ai)
- [Getting Started](https://docs.openclaw.ai/start/getting-started)
- [Docker Install](https://docs.openclaw.ai/install/docker)
- [Telegram Channel](https://docs.openclaw.ai/channels/telegram)
- [Skills System](https://docs.openclaw.ai/tools/skills)
- [MCP Integration](https://docs.openclaw.ai/tools/mcp)
- [Source Code](https://github.com/openclaw/openclaw)
