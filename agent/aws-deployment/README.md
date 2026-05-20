# AWS Deployment Guide — Physical AI Agent Stack

Deploy the complete Physical AI agent infrastructure on AWS. This guide covers compute (GPU), agent runtime, memory pipeline, and networking.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  EC2 G-Series Instance (GPU)                                │
│  ┌─────────────────┐  ┌──────────────────────────────────┐  │
│  │  OpenClaw Agent  │  │  Isaac Sim (Docker)              │  │
│  │  (Node.js)       │  │  • Physics simulation            │  │
│  │  • Telegram bot   │  │  • RTX rendering                │  │
│  │  • MCP servers    │  │  • WebRTC streaming             │  │
│  │  • Skills         │  │  • USD scene management         │  │
│  └────────┬──────────┘  └──────────────────────────────────┘  │
│           │                                                    │
│  ┌────────┴──────────────────────────────────────────────┐   │
│  │  Sim2Real Bridge                                       │   │
│  │  • Episode logging → DynamoDB                          │   │
│  │  • Knowledge upload → S3                               │   │
│  │  • Trajectory transfer → Real robot                    │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│  DynamoDB   │    │ OpenSearch       │    │ Bedrock KB   │
│  (Episodes) │    │ Serverless       │    │ (RAG)        │
│             │    │ (Vector Store)   │    │              │
└─────────────┘    └──────────────────┘    └──────────────┘
                           │
                   ┌───────┴───────┐
                   │  S3 (Knowledge │
                   │  Documents)    │
                   └───────────────┘
```

## Prerequisites

- AWS Account with GPU instance quota (G5/G6e)
- IAM permissions (see below)
- NVIDIA GPU driver 550+
- Docker + nvidia-container-toolkit

## Step 1: Launch EC2 GPU Instance

### Recommended Instance Types

| Instance | GPU | VRAM | Use Case |
|----------|-----|------|----------|
| g5.xlarge | A10G | 24 GB | Development, small scenes |
| g5.2xlarge | A10G | 24 GB | Production, more CPU/RAM |
| g6e.xlarge | L40S | 48 GB | Complex scenes, high-res rendering |
| p4d.24xlarge | A100 x8 | 320 GB | Multi-robot, large environments |

### Launch
```bash
aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \
  --instance-type g6e.xlarge \
  --key-name your-key \
  --security-group-ids sg-xxx \
  --iam-instance-profile Name=PhysicalAI-InstanceProfile \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":200,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=physical-ai-gpu}]'
```

### Security Group Rules
| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH |
| 8443 | TCP | Your IP | NICE DCV remote desktop |
| 49100 | TCP | Your IP | WebRTC signaling |
| 47998 | UDP | Your IP | WebRTC media |
| 18789 | TCP | Your IP | OpenClaw Control UI |

## Step 2: Install Dependencies

```bash
# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Pull Isaac Sim
docker pull nvcr.io/nvidia/isaac-sim:6.0.0-dev2

# Install OpenClaw
curl -fsSL https://openclaw.ai/install.sh | bash
openclaw onboard --install-daemon

# Install Python dependencies
pip install boto3 opensearch-py requests-aws4auth
```

## Step 3: IAM Configuration

### Instance Role Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/sim-episodes"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::physical-ai-sim-knowledge-*",
        "arn:aws:s3:::physical-ai-sim-knowledge-*/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:Retrieve",
        "bedrock-agent-runtime:Retrieve"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "aoss:*",
      "Resource": "*"
    }
  ]
}
```

### Bedrock KB Service Role

A separate role for Bedrock Knowledge Base (trust: `bedrock.amazonaws.com`):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "arn:aws:bedrock:*::foundation-model/*"},
    {"Effect": "Allow", "Action": "aoss:*", "Resource": "*"},
    {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::physical-ai-sim-knowledge-*/*"},
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::physical-ai-sim-knowledge-*"}
  ]
}
```

## Step 4: Deploy Memory Pipeline

### Option A: CloudFormation (Full Stack)
```bash
aws cloudformation create-stack \
  --stack-name physical-ai-sim-memory \
  --template-body file://infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

### Option B: Manual Step-by-Step

More reliable — avoids CloudFormation timing issues with OpenSearch Serverless:

```bash
# 1. Create OpenSearch Serverless security policies
aws opensearchserverless create-security-policy \
  --name physical-ai-sim-enc --type encryption \
  --policy '{"Rules":[{"ResourceType":"collection","Resource":["collection/physical-ai-sim"]}],"AWSOwnedKey":true}'

aws opensearchserverless create-security-policy \
  --name physical-ai-sim-net --type network \
  --policy '[{"Rules":[{"ResourceType":"collection","Resource":["collection/physical-ai-sim"]},{"ResourceType":"dashboard","Resource":["collection/physical-ai-sim"]}],"AllowFromPublic":true}]'

# 2. Create collection (wait for ACTIVE)
aws opensearchserverless create-collection \
  --name physical-ai-sim --type VECTORSEARCH

# 3. Create vector index (use Python — see scripts/sim2real/)
# 4. Create Bedrock KB
# 5. Add S3 data source
# 6. Trigger ingestion

# See scripts/sim2real/README.md for full details
```

### DynamoDB Table
```bash
aws dynamodb create-table \
  --table-name sim-episodes \
  --attribute-definitions \
    AttributeName=episode_id,AttributeType=S \
    AttributeName=task,AttributeType=S \
  --key-schema \
    AttributeName=episode_id,KeyType=HASH \
  --global-secondary-indexes '[{
    "IndexName": "task-index",
    "KeySchema": [{"AttributeName":"task","KeyType":"HASH"}],
    "Projection": {"ProjectionType":"ALL"}
  }]' \
  --billing-mode PAY_PER_REQUEST \
  --region us-west-2
```

## Step 5: Run the Platform

```bash
# 1. Download simulation assets
bash scripts/leisaac/download_assets.sh

# 2. Start Isaac Sim streaming
bash scripts/leisaac/run_streaming.sh

# 3. Verify agent is running
openclaw gateway status

# 4. Send test command via Telegram
# Message your bot: "Show me the kitchen scene"
```

## Cost Estimates (us-west-2)

| Resource | Cost |
|----------|------|
| g6e.xlarge (on-demand) | ~$1.86/hr |
| g5.xlarge (on-demand) | ~$1.01/hr |
| DynamoDB (on-demand) | ~$0.01/month (low volume) |
| OpenSearch Serverless | ~$0.24/hr (2 OCU minimum) |
| Bedrock KB | $0.10/sync + retrieval costs |
| S3 | < $0.01/month |

**Tip:** Use Spot instances for development (60-70% savings on GPU instances).

## Monitoring

```bash
# GPU utilization
nvidia-smi

# Isaac Sim container
docker logs isaac-sim-streaming --tail 50

# OpenClaw agent
openclaw gateway status
journalctl --user -u openclaw -f

# DynamoDB episodes
aws dynamodb scan --table-name sim-episodes --select COUNT
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Isaac Sim EULA segfault | Never use `-u 1234:1234` in docker run |
| WebRTC no video | Check ports 49100/TCP + 47998/UDP |
| Bedrock KB 403 | Ensure data access policy includes both roles |
| OpenSearch Serverless permission denied | Need `aoss:*` (not `es:*`) |
| Container OOM | Use g6e.xlarge (48GB VRAM) for complex scenes |
| Shader compilation slow | First run takes 8-12min; cached after |
