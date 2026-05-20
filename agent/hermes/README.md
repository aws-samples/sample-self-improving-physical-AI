# Hermes Agent — The Self-Improving AI Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research is a self-improving AI agent with a built-in learning loop. It creates skills from experience, improves them during use, persists knowledge across sessions, and runs anywhere — from a $5 VPS to a GPU cluster.

**Repo:** https://github.com/NousResearch/hermes-agent
**Docs:** https://hermes-agent.nousresearch.com/docs/

## Why Hermes Agent for Physical AI

| Capability | Application |
|-----------|-------------|
| Closed learning loop | Agent creates/improves skills from robot task outcomes |
| Skill auto-creation | Complex pick-and-place sequences become reusable skills |
| Cross-session memory | Remembers successful strategies across restarts |
| Multi-platform messaging | Telegram, Discord, Slack, WhatsApp, Signal |
| Subagent delegation | Parallel simulation runs, concurrent perception tasks |
| Scheduled automations | Periodic simulation health checks, nightly training runs |
| Any model backend | Nous Portal, OpenRouter, AWS Bedrock, Ollama, vLLM, custom |
| AgentSkills standard | Compatible with [agentskills.io](https://agentskills.io) open standard |

## Installation

```bash
# One-liner (Linux / macOS / WSL2)
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# Or via pip
pip install hermes-agent
hermes postinstall  # installs Node.js, browser, ripgrep, ffmpeg

# Reload shell
source ~/.bashrc
```

### Windows (PowerShell)
```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

## Quick Setup

```bash
hermes          # Start interactive CLI
hermes model    # Choose LLM provider
hermes setup    # Full setup wizard
hermes gateway  # Start messaging gateway (Telegram, etc.)
```

## Key Commands

| Command | Description |
|---------|-------------|
| `hermes` | Interactive terminal UI |
| `hermes model` | Select/switch LLM provider |
| `hermes tools` | Configure available tools |
| `hermes gateway` | Start messaging gateway |
| `hermes claw migrate` | Migrate from OpenClaw |
| `hermes update` | Update to latest |
| `hermes doctor` | Diagnose issues |

### In-Session Commands
| Command | Description |
|---------|-------------|
| `/new` | Start fresh conversation |
| `/model [provider:model]` | Change model mid-session |
| `/skills` | Browse available skills |
| `/compress` | Compress context window |
| `/usage` | Check token usage |
| `/retry` | Retry last response |

## Model Providers

Hermes supports 20+ providers with no code changes:

| Provider | Setup |
|----------|-------|
| Nous Portal | OAuth via `hermes model` |
| AWS Bedrock | IAM role or `aws configure` |
| OpenRouter | API key (200+ models) |
| Anthropic | OAuth (Max plan) or API key |
| OpenAI / Codex | Device code auth |
| NVIDIA NIM | `NVIDIA_API_KEY` |
| Ollama / vLLM | Custom endpoint URL |
| Hugging Face | `HF_TOKEN` |
| DeepSeek | `DEEPSEEK_API_KEY` |

**Minimum requirement:** 64K context window.

## Core Features

### 1. Closed Learning Loop
Hermes automatically creates skills from complex tasks:
```
Execute complex robot task → Agent solves it → Skill auto-created
                                                      ↓
Next similar request → Agent uses existing skill → Skill self-improves
```

### 2. Subagent Delegation
Spawn isolated subagents for parallel work:
```bash
# Agent can delegate simulation runs in parallel
# "Run 5 variations of the grasp approach simultaneously"
# → Spawns 5 subagents, each testing a different strategy
```

### 3. Scheduled Automations
Built-in cron for unattended work:
```bash
# "Every night at 2am, run 100 simulation episodes and log results"
# "Every Monday, generate a training report from last week's episodes"
```

### 4. Cross-Session Memory
- FTS5 session search with LLM summarization
- Periodic memory nudges (agent reminds itself to persist knowledge)
- [Honcho](https://github.com/plastic-labs/honcho) dialectic user modeling

### 5. Terminal Backends
Run anywhere:
| Backend | Use Case |
|---------|----------|
| Local | Development on your machine |
| Docker | Isolated container execution |
| SSH | Remote GPU server |
| Modal | Serverless (hibernates when idle) |
| Daytona | Serverless with persistence |
| Singularity | HPC clusters |

## Integration with This Platform

### As Robot Controller
```bash
# Configure Hermes with AWS Bedrock for Claude
hermes model  # → AWS Bedrock → Claude Sonnet

# Add Isaac Sim skill
# Hermes will auto-discover and use skills from ~/.hermes/skills/
cp -r skill/ ~/.hermes/skills/isaac-sim/
```

### With MCP Servers
Hermes supports MCP tool servers for DynamoDB/Bedrock KB access:
```json
{
  "mcp": {
    "servers": {
      "dynamodb": {
        "command": "uvx",
        "args": ["awslabs.dynamodb-mcp-server@latest"],
        "env": {"AWS_REGION": "us-west-2"}
      }
    }
  }
}
```

### Gateway for Telegram Control
```bash
hermes gateway setup   # Configure Telegram bot token
hermes gateway start   # Start listening

# Now message the bot: "Pick the closest orange"
# → Agent generates Isaac Sim script
# → Records episode to DynamoDB
# → Reports success/failure back to Telegram
```

### Migration from OpenClaw
```bash
hermes claw migrate  # Migrates config, skills, and memory
```

## Hermes vs OpenClaw

Both are personal AI agents. Key differences:

| | Hermes Agent | OpenClaw |
|---|---|---|
| Runtime | Python (uv) | Node.js |
| Learning | Auto skill creation + improvement | Manual skill files |
| Memory | FTS5 + Honcho user modeling | File-based (MEMORY.md) |
| Subagents | Built-in parallel delegation | ACP runtime spawning |
| Scheduling | Built-in cron | Built-in cron |
| Messaging | Telegram, Discord, Slack, etc. | Same platforms |
| Model support | 20+ providers | Multiple providers |
| Unique | Self-improving skills, trajectory generation | Canvas, node pairing |

Both work for this project. Use whichever fits your workflow.

## References

- [GitHub](https://github.com/NousResearch/hermes-agent)
- [Documentation](https://hermes-agent.nousresearch.com/docs/)
- [Quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart)
- [Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging)
- [AWS Bedrock Guide](https://hermes-agent.nousresearch.com/docs/guides/aws-bedrock)
- [AgentSkills Standard](https://agentskills.io)
- [Discord Community](https://discord.gg/NousResearch)
