# Sim2Real Memory Pipeline

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Isaac Sim 6.0  │────▶│   DynamoDB   │◀────│  Real SO-ARM101 │
│  (AWS L40S GPU) │     │ sim-episodes │     │   (LeRobot)     │
└────────┬────────┘     └──────┬───────┘     └────────┬────────┘
         │                     │                      │
         ▼                     ▼                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│    S3 Bucket    │────▶│ Bedrock KB   │────▶│   MCP Server    │
│  (knowledge)   │     │  (RAG)       │     │ (tool access)   │
└─────────────────┘     └──────────────┘     └─────────────────┘
```

## Components

### 1. DynamoDB Table: `sim-episodes`
Stores every simulation episode with full trajectory data.

**Schema:**
| Field | Type | Description |
|-------|------|-------------|
| episode_id | String (PK) | UUID |
| created_at | String (SK) | ISO timestamp |
| task | String | Task identifier |
| trajectory | List | Joint angle waypoints |
| success | Boolean | Episode outcome |
| robot_config | Map | Robot placement/params |
| metrics | Map | Timing, accuracy |

### 2. S3 Bucket: `physical-ai-sim-knowledge-{account}`
Knowledge documents for RAG retrieval:
- `docs/pick_and_place_strategy.md` — Successful strategies
- `docs/isaac_sim_6_api.md` — API reference and gotchas
- `docs/sim2real_bridge.md` — Transfer design

### 3. Bedrock Knowledge Base
RAG over simulation knowledge. Agents can query:
- "How do I pick up an orange with SO-101?"
- "What joint angles work for reaching the counter?"
- "What failed approaches should I avoid?"

### 4. MCP Servers (awslabs/mcp)
Two MCP servers provide tool access:
- **DynamoDB MCP** (`awslabs.dynamodb-mcp-server`) — Query/write episodes
- **Bedrock KB MCP** (`awslabs.bedrock-kb-retrieval-mcp-server`) — RAG retrieval over the
  knowledge documents in the S3 bucket (the KB's data source)

Only launch MCP servers whose package names are published on PyPI by AWS Labs
(see https://github.com/awslabs/mcp). `uvx` resolves bare names from public PyPI,
so an unpublished name can be claimed by a third party.

## Setup

### Prerequisites
- AWS account with DynamoDB, S3, Bedrock access
- IAM role with appropriate permissions

### Deploy Infrastructure
```bash
aws cloudformation create-stack \
  --stack-name physical-ai-sim-memory \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

### Configure MCP Servers
Copy `scripts/sim2real/mcp_config.json` to your MCP client configuration.

### Usage

**Record episodes from simulation:**
```python
from episode_logger import EpisodeLogger
logger = EpisodeLogger()
eid = logger.start_episode(task="pick_orange_to_plate", robot_config={...})
logger.add_waypoint(1, "reach", {"shoulder_pan": -15, ...})
logger.end_episode(success=True, metrics={"time": 50.0})
```

**Transfer to real robot:**
```bash
python bridge.py --task pick_orange_to_plate --dry-run
python bridge.py --task pick_orange_to_plate --execute
```

**Query past episodes:**
```python
logger = EpisodeLogger()
episodes = logger.query_episodes(task="pick_orange_to_plate", success_only=True)
best_trajectory = logger.get_best_trajectory("pick_orange_to_plate")
```

## Remaining Setup (requires IAM permissions)

The EC2 instance role needs these additional permissions to create the KB:
- `iam:CreateRole` + `iam:PassRole`
- `cloudformation:CreateStack`
- `aoss:*` (OpenSearch Serverless)

Deploy the CloudFormation stack from Console or a privileged user:
```bash
aws cloudformation create-stack \
  --stack-name physical-ai-sim-memory \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```
