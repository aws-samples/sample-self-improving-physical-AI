name: cosmos-world-model
description: Host and run NVIDIA Cosmos 3 world models on AWS EC2 GPU instances for Physical AI world generation, reasoning, and action modeling. Use when asked to generate synthetic environments, predict robot futures, run world simulation, produce training rollouts, do physical reasoning from video, or serve Cosmos 3 (Super/Nano/Edge) models for text-to-video, image-to-video, forward dynamics, or action policy inference. Supports Generator (diffusion) and Reasoner (VLM) modes via vLLM-Omni or Diffusers.
---

# Cosmos 3 World Model — EC2 Deployment

Host NVIDIA Cosmos 3 omnimodal world models on AWS EC2 GPU instances for Physical AI applications:
world generation, simulation, physical reasoning, action prediction, and synthetic data.

## Model Family

| Model | Size | GPU Requirement | Best For |
|-------|------|-----------------|----------|
| Cosmos3-Super | 64B | 4× H100 80GB (p5.8xlarge) or 2× H200 (p5e.2xlarge) | Highest quality generation, teacher for distillation |
| Cosmos3-Nano | 16B | 1× H100 80GB (p5.2xlarge) or 1× A100 80GB (p4d.xlarge) | Balanced speed/quality, post-training base |
| Cosmos3-Edge | 4B | 1× L4 24GB (g6.xlarge) or 1× A10G (g5.xlarge) | Real-time robotic policy, edge reasoning |

## Two Runtime Surfaces

| Surface | Inputs | Outputs | Use Cases |
|---------|--------|---------|-----------|
| **Reasoner** | Text, Vision | Text | Physical reasoning, task planning, action forecasting, embodied agent reasoning |
| **Generator** | Text, Vision, Sound, Action | Vision, Sound, Action | World simulation, synthetic data, forward dynamics, policy learning |

## EC2 Instance Recommendations

### Cosmos3-Nano (Recommended Starting Point)

```bash
# Instance: p5.2xlarge (1× H100 80GB) or g6e.4xlarge (1× L40S 48GB for Reasoner only)
# AMI: Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)
# Storage: 500 GB gp3 (model weights ~32GB + workspace)
# Cost: ~$32/hr (p5.2xlarge on-demand), ~$12/hr (spot)
```

### Cosmos3-Edge (Cheapest GPU)

```bash
# Instance: g6.xlarge (1× L4 24GB) — ~$0.80/hr spot
# Good for: Real-time robotic policy inference, Reasoner mode
# AMI: Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)
# Storage: 200 GB gp3
```



## Option 1: NVIDIA NIM Container (Recommended — Production-Ready)

NIM (NVIDIA Inference Microservices) is the **simplest** way to deploy Cosmos on EC2.
One Docker command, auto-downloads model, exposes OpenAI-compatible API.

### Prerequisites

- NGC API Key from [NGC Setup](https://org.ngc.nvidia.com/setup) (select "NGC Catalog")
- EC2 instance with NVIDIA GPU + Docker + NVIDIA Container Toolkit
- Recommended AMI: **Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)**

### Launch Cosmos3-Generator NIM (Nano — 8B, default)

```bash
#!/bin/bash
# cosmos-nim-setup.sh — One-command Cosmos on EC2

# 1. Set your NGC API Key
export NGC_API_KEY="<your-ngc-api-key>"

# 2. Docker login to NGC
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

# 3. Create cache directory
export LOCAL_NIM_CACHE=~/.cache/nim
mkdir -p "$LOCAL_NIM_CACHE"
chmod -R 777 "$LOCAL_NIM_CACHE" 2>/dev/null || true

# 4. Launch Cosmos3-Generator NIM (nano, fp8, latency-optimized)
docker run -it --rm \
    --name cosmos3-generator \
    --runtime=nvidia \
    --gpus all \
    --shm-size=32GB \
    --ulimit nofile=65536:65536 \
    -e NGC_API_KEY=$NGC_API_KEY \
    -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
    -p 8000:8000 \
    nvcr.io/nim/nvidia/cosmos3-generator:1.0.0
```

### Launch Cosmos3-Generator (Super — 32B)

```bash
# Requires 2× H100 80GB (p5.4xlarge) or 4× A100 (p4d.24xlarge)
docker run -it --rm \
    --name cosmos3-generator \
    --runtime=nvidia \
    --gpus all \
    --shm-size=32GB \
    --ulimit nofile=65536:65536 \
    -e NGC_API_KEY=$NGC_API_KEY \
    -e NIM_MODEL_SIZE=super \
    -e NIM_PRECISION=fp8 \
    -e NIM_PERF_PROFILE=latency \
    -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
    -p 8000:8000 \
    nvcr.io/nim/nvidia/cosmos3-generator:1.0.0
```

### Other Available NIM Containers

| NIM Container | Use Case | GPU Requirement |
|---------------|----------|-----------------|
| `cosmos3-generator` (nano) | Text/Image→Video, Action policy | 1× H100 80GB |
| `cosmos3-generator` (super) | Highest quality generation | 2-4× H100 80GB |
| `cosmos-predict1-7b-text2world` | Text-to-world video | 1× A100/H100 |
| `cosmos-predict1-7b-video2world` | Video-to-world continuation | 1× A100/H100 |
| `cosmos-predict2.5-2b` | Lightweight prediction | 1× L4/A10G |
| `cosmos-transfer2.5-2b` | Style/domain transfer | 1× L4/A10G |

### NIM Environment Variables

| Variable | Values | Default | Purpose |
|----------|--------|---------|---------|
| `NIM_MODEL_SIZE` | nano, super | nano | Model variant |
| `NIM_PRECISION` | bf16, fp8, nvfp4 | fp8 | Quantization level |
| `NIM_PERF_PROFILE` | latency, throughput | latency | Optimization target |

### Test the API

```bash
# Health check
curl -s http://localhost:8000/v1/health/ready

# Text-to-video generation
curl -X POST http://localhost:8000/v1/cosmos/generate \
    -H "Content-Type: application/json" \
    -d '{
        "prompt": "A robotic arm smoothly picks up an orange from a kitchen counter",
        "num_frames": 121,
        "resolution": "480p",
        "fps": 24
    }' \
    --output robot_pickup.mp4

# Image-to-video (provide starting frame)
curl -X POST http://localhost:8000/v1/cosmos/generate \
    -H "Content-Type: application/json" \
    -d '{
        "prompt": "The robot arm moves to grasp the object",
        "image": "'$(base64 -w0 start_frame.png)'",
        "num_frames": 61
    }' \
    --output continuation.mp4
```

### Run as systemd Service (Production)

```bash
cat > /etc/systemd/system/cosmos-nim.service << 'EOF'
[Unit]
Description=NVIDIA Cosmos NIM World Model
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
Environment=NGC_API_KEY=<your-key>
ExecStartPre=-/usr/bin/docker rm -f cosmos3-generator
ExecStart=/usr/bin/docker run --rm \
    --name cosmos3-generator \
    --runtime=nvidia --gpus all \
    --shm-size=32GB --ulimit nofile=65536:65536 \
    -e NGC_API_KEY=${NGC_API_KEY} \
    -v /opt/nim-cache:/opt/nim/.cache \
    -p 8000:8000 \
    nvcr.io/nim/nvidia/cosmos3-generator:1.0.0
ExecStop=/usr/bin/docker stop cosmos3-generator

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cosmos-nim
sudo systemctl start cosmos-nim
```


## Option 2: Manual Setup (uv + HuggingFace)



Run this on a fresh EC2 GPU instance:

```bash
#!/bin/bash
# cosmos-setup.sh — Deploy Cosmos 3 on EC2
set -euo pipefail

MODEL=${1:-"nvidia/Cosmos3-Nano"}
MODE=${2:-"generator"}  # generator or reasoner

echo "=== Installing dependencies ==="
sudo apt-get update && sudo apt-get install -y python3-pip git-lfs
pip install uv --break-system-packages

echo "=== Setting up Cosmos ==="
git clone https://github.com/NVIDIA/Cosmos.git ~/cosmos
cd ~/cosmos

# Install with uv (recommended by NVIDIA)
uv sync --extra ${MODE}

echo "=== Downloading model weights ==="
# Requires: huggingface-cli login (with HF token that accepted Cosmos license)
huggingface-cli download ${MODEL} --local-dir ~/cosmos-weights/${MODEL##*/}

echo "=== Setup complete ==="
echo "Model: ${MODEL}"
echo "Mode: ${MODE}"
echo "Weights: ~/cosmos-weights/${MODEL##*/}"
```

### Serving Options

### Option A: vLLM-Omni (OpenAI-Compatible API — Recommended for Production)

Best for Generator mode. Provides an OpenAI-compatible endpoint.

```bash
# Start vLLM-Omni server
cd ~/cosmos
uv run python -m cosmos.serve.vllm_omni \
    --model ~/cosmos-weights/Cosmos3-Nano \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1

# Test with curl
curl http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Cosmos3-Nano",
        "messages": [
            {"role": "user", "content": "Generate a video of a robot arm picking up an orange from a kitchen counter"}
        ],
        "max_tokens": 20000
    }'
```

### Option B: vLLM (Reasoner Mode)

```bash
cd ~/cosmos
uv run python -m cosmos.serve.vllm \
    --model ~/cosmos-weights/Cosmos3-Nano \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1

# Physical reasoning query
curl http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Cosmos3-Nano",
        "messages": [
            {"role": "user", "content": [
                {"type": "video", "video": {"url": "file:///tmp/robot_episode.mp4"}},
                {"type": "text", "text": "What will the robot do next? Predict the next 5 actions."}
            ]}
        ]
    }'
```

### Option C: Diffusers (Python Script — Quick Prototyping)

```python
# cosmos_generate.py
from cosmos.models import Cosmos3Generator

model = Cosmos3Generator.from_pretrained(
    "~/cosmos-weights/Cosmos3-Nano",
    torch_dtype="bfloat16"
)

# Text-to-video generation
output = model.generate(
    prompt="A SO-ARM101 robot arm picks up an orange from a kitchen counter, "
           "smooth motion, realistic physics, 480p, 24fps",
    num_frames=121,     # ~5 seconds at 24fps
    resolution="480p",
    fps=24,
)
output.save("robot_pickup.mp4")
```

### Option D: SGLang (High-Throughput Serving)

```bash
cd ~/cosmos
uv run python -m cosmos.serve.sglang \
    --model ~/cosmos-weights/Cosmos3-Nano \
    --host 0.0.0.0 \
    --port 8000 \
    --tp 1
```

## CloudFormation / CDK Setup

```yaml
# cosmos-ec2-stack.yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Cosmos 3 World Model on EC2

Parameters:
  InstanceType:
    Type: String
    Default: p5.2xlarge
    AllowedValues: [g5.xlarge, g6.xlarge, g6e.4xlarge, p4d.xlarge, p5.2xlarge]
  HuggingFaceToken:
    Type: String
    NoEcho: true

Resources:
  CosmosInstance:
    Type: AWS::EC2::Instance
    Properties:
      InstanceType: !Ref InstanceType
      ImageId: ami-0a0e5d9c7acc336f1  # Deep Learning AMI (Ubuntu 22.04) us-west-2
      BlockDeviceMappings:
        - DeviceName: /dev/sda1
          Ebs:
            VolumeSize: 500
            VolumeType: gp3
            Iops: 6000
            Throughput: 500
      SecurityGroups:
        - !Ref CosmosSecurityGroup
      IamInstanceProfile: !Ref CosmosInstanceProfile
      UserData:
        Fn::Base64: !Sub |
          #!/bin/bash
          set -e
          export HF_TOKEN=${HuggingFaceToken}
          
          # Install uv + clone Cosmos
          pip install uv huggingface-hub --break-system-packages
          git clone https://github.com/NVIDIA/Cosmos.git /opt/cosmos
          cd /opt/cosmos && uv sync --extra generator
          
          # Download model
          huggingface-cli login --token $HF_TOKEN
          huggingface-cli download nvidia/Cosmos3-Nano --local-dir /opt/cosmos-weights/Cosmos3-Nano
          
          # Start server via systemd
          cat > /etc/systemd/system/cosmos.service << EOF
          [Unit]
          Description=Cosmos 3 World Model Server
          After=network.target
          
          [Service]
          Type=simple
          WorkingDirectory=/opt/cosmos
          ExecStart=/root/.local/bin/uv run python -m cosmos.serve.vllm_omni --model /opt/cosmos-weights/Cosmos3-Nano --host 0.0.0.0 --port 8000 --tensor-parallel-size 1
          Restart=always
          Environment=CUDA_VISIBLE_DEVICES=0
          
          [Install]
          WantedBy=multi-user.target
          EOF
          
          systemctl daemon-reload
          systemctl enable cosmos
          systemctl start cosmos

  CosmosSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Cosmos World Model
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 8000
          ToPort: 8000
          CidrIp: 10.0.0.0/8  # VPC only
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0

  CosmosInstanceProfile:
    Type: AWS::IAM::InstanceProfile
    Properties:
      Roles: [!Ref CosmosRole]

  CosmosRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Effect: Allow
            Principal: { Service: ec2.amazonaws.com }
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

Outputs:
  Endpoint:
    Value: !Sub "http://${CosmosInstance.PrivateIp}:8000"
  InstanceId:
    Value: !Ref CosmosInstance
```

## Integration with Self-Improving Physical AI

Cosmos 3 serves as the **world simulator** in the self-improving loop:

```
Agent (Bedrock) → [Plan action] → Cosmos Generator → [Simulate rollout video]
                                                    ↓
Agent (Bedrock) ← [Evaluate outcome] ← Cosmos Reasoner ← [Physical reasoning on video]
                                                    ↓
                                        [Update policy / retry]
```

### MCP Tool Registration

Register Cosmos as an MCP tool via AgentCore Gateway:

```json
{
    "name": "cosmos_simulate",
    "description": "Generate a simulation video of a robot performing an action using Cosmos 3 world model",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Action description for the robot"},
            "image_url": {"type": "string", "description": "Starting scene image (optional)"},
            "action_sequence": {"type": "array", "description": "Robot joint actions (optional)"},
            "num_frames": {"type": "integer", "default": 121},
            "resolution": {"type": "string", "enum": ["256p", "480p", "720p"], "default": "480p"}
        },
        "required": ["prompt"]
    }
}
```

```json
{
    "name": "cosmos_reason",
    "description": "Analyze a robot video for physical reasoning, next-action prediction, or plausibility check",
    "input_schema": {
        "type": "object",
        "properties": {
            "video_url": {"type": "string", "description": "S3 or local path to episode video"},
            "question": {"type": "string", "description": "Physical reasoning question"},
            "task": {"type": "string", "enum": ["next_action", "plausibility", "caption", "planning"], "default": "next_action"}
        },
        "required": ["video_url", "question"]
    }
}
```

## Supported Generation Settings

| Setting | Values |
|---------|--------|
| Resolution | 256p, 480p, 720p (default: 480p) |
| Aspect ratio | 16:9, 4:3, 1:1, 3:4, 9:16 |
| Frame rate | 10, 16, 24, 30 fps (default: 24) |
| Frame count | 5–300 (default: 189) |
| Precision | BF16 |
| Action dims | Camera (9D), AV (9D), Single-arm (10D), Dual-arm (20D), Humanoid (29D) |

## Health Check

```bash
# Check if server is running
curl -s http://localhost:8000/health | jq .

# Check GPU utilization
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv

# Test generation
curl http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"Cosmos3-Nano","messages":[{"role":"user","content":"Describe this scene: a robot arm in a kitchen"}],"max_tokens":200}'
```

## Cost Estimation

| Instance | GPU | Hourly (On-Demand) | Hourly (Spot) | Model |
|----------|-----|-------|------|-------|
| g6.xlarge | 1× L4 24GB | $0.98 | ~$0.40 | Cosmos3-Edge (4B) |
| g5.xlarge | 1× A10G 24GB | $1.01 | ~$0.45 | Cosmos3-Edge (4B) |
| g6e.4xlarge | 1× L40S 48GB | $3.36 | ~$1.40 | Cosmos3-Nano Reasoner |
| p5.2xlarge | 1× H100 80GB | $32.77 | ~$12.00 | Cosmos3-Nano full |
| p5.8xlarge | 4× H100 80GB | $131.08 | ~$50.00 | Cosmos3-Super |

**Recommended for demos:** g6.xlarge (Cosmos3-Edge) at ~$0.40/hr spot for real-time policy inference.
**Recommended for full pipeline:** p5.2xlarge (Cosmos3-Nano) for generation + reasoning.
