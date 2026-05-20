# Hermes 3 — Agentic LLM for Robot Reasoning

[Hermes 3](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B) by Nous Research is a generalist language model optimized for agentic capabilities, function calling, and structured output — making it ideal for robot task planning and code generation.

## Role in This Project

Hermes 3 serves as an **alternative/local reasoning engine** for the Physical AI agent:
- Task decomposition (break "pick orange" into joint waypoints)
- Function calling (invoke Isaac Sim APIs, DynamoDB queries)
- Code generation (produce executable simulation scripts)
- Multi-turn reasoning (iterative strategy refinement)

## Why Hermes 3

| Capability | Benefit for Robotics |
|-----------|---------------------|
| Advanced function calling | Reliable tool use for simulation control |
| Structured output | JSON waypoints, joint configs |
| Agentic reasoning | Multi-step task planning |
| Open weights | Self-hosted, no API costs, air-gapped deployments |
| ChatML format | OpenAI-compatible, drop-in replacement |
| Roleplaying/steering | Can adopt "robot controller" persona |

## Available Models

| Model | Size | Use Case |
|-------|------|----------|
| Hermes-3-Llama-3.1-8B | 8B | Fast inference, single GPU |
| Hermes-3-Llama-3.1-70B | 70B | Best reasoning, multi-GPU |
| Hermes-3-Llama-3.1-405B | 405B | Maximum capability |

## Deployment Options

### 1. AWS Bedrock (Managed)
If available as a custom model import:
```bash
# Import to Bedrock for serverless inference
aws bedrock create-model-import-job \
  --job-name hermes-3-import \
  --imported-model-name hermes-3-8b \
  --model-data-source '{"s3DataSource":{"s3Uri":"s3://your-bucket/hermes-3/"}}'
```

### 2. Amazon SageMaker
```python
from sagemaker.huggingface import HuggingFaceModel

model = HuggingFaceModel(
    model_data="s3://your-bucket/hermes-3-8b/model.tar.gz",
    role="arn:aws:iam::ACCOUNT:role/SageMakerRole",
    transformers_version="4.37",
    pytorch_version="2.1",
    py_version="py310",
    env={
        "HF_MODEL_ID": "NousResearch/Hermes-3-Llama-3.1-8B",
        "SM_NUM_GPUS": "1"
    }
)
predictor = model.deploy(
    instance_type="ml.g5.2xlarge",
    initial_instance_count=1
)
```

### 3. Self-Hosted (vLLM)
```bash
pip install vllm

# Serve with OpenAI-compatible API
python -m vllm.entrypoints.openai.api_server \
  --model NousResearch/Hermes-3-Llama-3.1-8B \
  --port 8000 \
  --chat-template chatml
```

### 4. Ollama (Local)
```bash
ollama pull hermes3:8b
ollama serve
# API at http://localhost:11434
```

## Function Calling Format

Hermes 3 uses a structured function calling format:

```xml
<|im_start|>system
You are a robot control agent. You have access to these tools:
<tools>
{"type": "function", "function": {"name": "set_joint_positions", "description": "Move robot joints to target positions", "parameters": {"type": "object", "properties": {"joint_positions": {"type": "array", "items": {"type": "number"}}, "speed": {"type": "number"}}}}}
{"type": "function", "function": {"name": "query_episodes", "description": "Query past simulation episodes from DynamoDB", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "success_only": {"type": "boolean"}}}}}
</tools>
<|im_end|>
<|im_start|>user
Pick up the orange from the counter
<|im_end|>
<|im_start|>assistant
<tool_call>
{"name": "query_episodes", "arguments": {"task": "pick_orange_to_plate", "success_only": true}}
</tool_call>
<|im_end|>
```

## Integration with OpenClaw

OpenClaw supports Hermes 3 as a model backend:

```json
{
  "models": {
    "default": "ollama/hermes3:8b",
    "providers": {
      "ollama": {
        "baseUrl": "http://localhost:11434/v1"
      }
    }
  }
}
```

Or via vLLM:
```json
{
  "models": {
    "default": "openai/hermes-3",
    "providers": {
      "openai": {
        "baseUrl": "http://localhost:8000/v1",
        "apiKey": "not-needed"
      }
    }
  }
}
```

## Example: Robot Task Planning

**Input:** "Pick the orange closest to the robot and place it on the plate"

**Hermes 3 Output:**
```json
{
  "plan": [
    {"step": 1, "action": "query_scene", "description": "Get orange positions"},
    {"step": 2, "action": "select_target", "description": "Find closest orange to robot (2.13, -0.30)"},
    {"step": 3, "action": "plan_approach", "description": "Calculate pre-grasp position above orange"},
    {"step": 4, "action": "execute_grasp", "waypoints": [
      {"name": "reach", "joints": {"shoulder_pan": -15, "shoulder_lift": -30, "elbow_flex": 60}},
      {"name": "grasp", "joints": {"gripper": 30}},
      {"name": "lift", "joints": {"shoulder_lift": -80}},
      {"name": "move_to_plate", "joints": {"shoulder_pan": 25}},
      {"name": "release", "joints": {"gripper": -10}}
    ]}
  ]
}
```

## References

- [Hermes 3 Technical Report](https://arxiv.org/abs/2408.11857)
- [HuggingFace Model Card](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B)
- [Nous Research](https://nousresearch.com/)
- [ChatML Format](https://github.com/openai/openai-python/blob/main/chatml.md)
