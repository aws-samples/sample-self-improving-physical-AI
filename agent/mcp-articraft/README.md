# Articraft MCP Servers — 3D Asset Generation & Retrieval

Two MCP servers that expose [Articraft](https://github.com/mattzh72/articraft) capabilities to any MCP-compatible agent (AgentCore, OpenClaw, Hermes, Claude, etc.).

## Architecture

```
AgentCore Gateway
    │
    ├──► MCP Server 1: Generator (ECS Fargate)
    │    • generate_asset — Create new articulated 3D from text
    │    • fork_asset — Modify existing models
    │    • get_generation_status — Poll async jobs
    │    • list_categories — Browse object types
    │    • download_asset — Get URDF package
    │         │
    │         ▼
    │    Articraft SDK → LLM → CadQuery → URDF → S3
    │
    └──► MCP Server 2: Knowledge Base (ECS Fargate)
         • search_assets — RAG over 10K asset descriptions
         • get_asset_metadata — Detailed part/joint info
         • get_asset_urdf — Presigned download URL
         • list_dataset_stats — Dataset overview
              │
              ▼
         Bedrock KB (RAG) ← S3 (Articraft-10K metadata)
```

## Dataset

**Articraft-10K**: 10,000 articulated 3D objects in URDF format.
- Source: https://huggingface.co/datasets/camvsl/Articraft-10K
- License: CC-BY-4.0
- Format: tar.gz per record (URDF + meshes + metadata)
- Joint types: revolute, prismatic, fixed, continuous
- Categories: furniture, electronics, appliances, tools, vehicles, kitchen, industrial, music, toys

## Setup

### 1. Upload Dataset to S3

```bash
pip install huggingface_hub boto3

# Upload first 100 records (for testing)
python scripts/upload_dataset.py --bucket articraft-assets-ACCOUNT_ID --max-records 100

# Upload all 10K records
python scripts/upload_dataset.py --bucket articraft-assets-ACCOUNT_ID
```

### 2. Create Bedrock Knowledge Base

```bash
# Create KB pointing to s3://articraft-assets-ACCOUNT/kb-docs/
# Use amazon.titan-embed-text-v2:0 embedding model
# Set ARTICRAFT_KB_ID env var in the KB service task definition
```

### 3. Build & Push Docker Image

```bash
cd agent/mcp-articraft
docker build -t articraft-mcp .
docker tag articraft-mcp:latest ACCOUNT.dkr.ecr.REGION.amazonaws.com/articraft-mcp:latest
docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/articraft-mcp:latest
```

### 4. Deploy Infrastructure

```bash
aws cloudformation create-stack \
  --stack-name articraft-mcp \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxx \
    ParameterKey=SubnetIds,ParameterValue="subnet-aaa,subnet-bbb" \
    ParameterKey=ArticraftImage,ParameterValue=ACCOUNT.dkr.ecr.REGION.amazonaws.com/articraft-mcp:latest
```

### 5. Register with AgentCore Gateway

```json
{
  "mcpServers": {
    "articraft-generator": {
      "transport": "sse",
      "url": "http://<generator-task-ip>:8080/sse",
      "description": "Generate articulated 3D assets from text descriptions"
    },
    "articraft-knowledge-base": {
      "transport": "sse",
      "url": "http://<kb-task-ip>:8081/sse",
      "description": "Search and retrieve existing 3D assets from Articraft-10K"
    }
  }
}
```

## Tools Reference

### Generator Server (port 8080)

| Tool | Description | Async |
|------|-------------|-------|
| `generate_asset` | Create new articulated 3D model from text | Yes (poll) |
| `fork_asset` | Modify existing model | Yes (poll) |
| `get_generation_status` | Check job progress | No |
| `list_categories` | Browse object categories | No |
| `download_asset` | Get presigned URL for URDF | No |

### Knowledge Base Server (port 8081)

| Tool | Description | Async |
|------|-------------|-------|
| `search_assets` | RAG search over 10K assets | No |
| `get_asset_metadata` | Full metadata for a record | No |
| `get_asset_urdf` | Presigned download URL | No |
| `list_dataset_stats` | Dataset statistics | No |

## Example Usage (from Agent)

```
Agent: "I need a desk lamp with two hinged arms for my simulation"

1. search_assets("desk lamp with hinged arms")
   → Found 3 existing matches (score: 0.85, 0.72, 0.68)

2. get_asset_urdf("rec_a-desk-lamp-with-weighted-base...")
   → Returns presigned URL for URDF package

3. Load into Isaac Sim for robot manipulation testing
```

```
Agent: "Generate a custom coffee machine with an articulated brew arm and lid"

1. generate_asset("A coffee machine with a hinged lid, articulated brew arm...")
   → job_id: "abc-123", status: "running"

2. get_generation_status("abc-123")
   → status: "completed", urdf_url: "https://..."

3. Download and load into simulation
```

## Integration with Isaac Sim

Generated URDFs load directly into Isaac Sim:

```python
from isaacsim.core.utils.stage import add_reference_to_stage

# Download URDF from S3 (via MCP tool result)
# Convert URDF to USD if needed, or load directly
add_reference_to_stage("/path/to/generated/model.urdf", "/World/Object")
```

## Local Development

```bash
# Run generator locally (stdio transport)
cd server && python generator.py

# Run KB server locally
cd server && MCP_TRANSPORT=stdio python knowledge_base.py

# Test with MCP inspector
mcp inspect server/generator.py
```

## Cost Estimates

| Component | Cost |
|-----------|------|
| ECS Fargate (generator, 2vCPU/8GB) | ~$0.10/hr |
| ECS Fargate (KB, 0.5vCPU/1GB) | ~$0.03/hr |
| S3 (10K records, ~50GB) | ~$1.15/month |
| DynamoDB (jobs) | < $0.01/month |
| Bedrock KB (RAG) | $0.10/sync + retrieval |
| LLM generation (per asset) | $0.50-2.00 |
