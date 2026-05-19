---
name: sim2real-mcp
description: Query simulation memory and transfer robot trajectories to real hardware using AWS services (DynamoDB, Bedrock KB, MCP). Use when asked to recall past simulation episodes, find successful trajectories, query robot knowledge, or execute Sim2Real transfer to the physical SO-ARM101.
---

# Sim2Real MCP — Simulation Memory & Transfer

Access simulation history and knowledge through AWS MCP servers.

## Prerequisites

| Component | Required |
|-----------|----------|
| AWS credentials | IAM role with DynamoDB + Bedrock access |
| DynamoDB table | `sim-episodes` |
| Bedrock KB | ID: `LXJRX6IS8Z` |
| S3 bucket | `physical-ai-sim-knowledge-{account}` |
| MCP servers | `awslabs.dynamodb-mcp-server`, `awslabs.bedrock-kb-retrieval-mcp-server` |

## MCP Server Configuration

Add to your MCP client config (`mcp_config.json`):
```json
{
  "mcpServers": {
    "awslabs.dynamodb-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.dynamodb-mcp-server@latest"],
      "env": {"AWS_REGION": "us-west-2"}
    },
    "awslabs.bedrock-kb-retrieval-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.bedrock-kb-retrieval-mcp-server@latest"],
      "env": {"AWS_REGION": "us-west-2"}
    }
  }
}
```

## Query Simulation Episodes

### Python SDK
```python
from scripts.sim2real.episode_logger import EpisodeLogger
logger = EpisodeLogger()

# Find successful pick-and-place episodes
episodes = logger.query_episodes(task="pick_orange_to_plate", success_only=True)

# Get best trajectory
trajectory = logger.get_best_trajectory("pick_orange_to_plate")
```

### AWS CLI
```bash
aws dynamodb scan --table-name sim-episodes \
  --filter-expression "task = :t AND success = :s" \
  --expression-attribute-values '{":t":{"S":"pick_orange_to_plate"},":s":{"BOOL":true}}' \
  --region us-west-2
```

## Query Knowledge Base (RAG)

```bash
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id LXJRX6IS8Z \
  --retrieval-query '{"text": "What joint angles work for picking oranges?"}' \
  --region us-west-2
```

## Transfer to Real Robot

```bash
# Dry run — print adapted trajectory
python scripts/sim2real/bridge.py --task pick_orange_to_plate --dry-run

# Execute on real SO-ARM101
python scripts/sim2real/bridge.py --task pick_orange_to_plate --execute
```

### Safety Scaling
- All joint angles scaled by 0.9 (safety margin)
- Gripper range scaled by 0.8 (smaller real range)
- Execution speed: 0.5s per waypoint (slower than sim)

## Record New Episodes

```python
logger = EpisodeLogger()
eid = logger.start_episode(
    task="pick_orange_to_plate",
    robot_config={"position": [2.30, -0.55, 0.92], "yaw": 180.0, "stiffness": 17.8}
)
logger.add_waypoint(1, "rest", {"shoulder_pan": 0, "shoulder_lift": -100, ...})
logger.add_waypoint(2, "reach", {"shoulder_pan": -15, "shoulder_lift": -30, ...})
# ... more waypoints
logger.end_episode(success=True, metrics={"completion_time_s": 50.0})
```

## Upload New Knowledge

```bash
# Add a new document
aws s3 cp my_new_strategy.md s3://physical-ai-sim-knowledge-{account}/docs/

# Trigger re-ingestion
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id LXJRX6IS8Z \
  --data-source-id VCD3VJTFHI \
  --region us-west-2
```
