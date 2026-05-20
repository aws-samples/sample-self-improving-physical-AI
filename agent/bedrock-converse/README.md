# Zumi Chatbot POC

A natural-language chatbot that controls a Robolink Zumi robot through AWS Bedrock + IoT Core.

## Architecture

```
User ──► Browser Chat UI ──► FastAPI Backend ──► Bedrock (Claude) ──► Tool Use
                                    │                                      │
                                    │              ┌───────────────────────┘
                                    ▼              ▼
                              AWS IoT Core ──► MQTT ──► Zumi (zumi_iot.py)
```

1. User types a natural language message in the chat UI
2. FastAPI sends it to Bedrock Converse API with Zumi tool definitions
3. Bedrock decides which tool(s) to call based on the user's intent
4. Backend publishes the corresponding command to IoT Core via MQTT
5. Zumi receives the command and executes it (lights, sound, screen, sensors)

## MVP Scope (non-movement)

- **Sensors**: IR readings, battery voltage, orientation, gyro angles
- **LEDs**: headlights, brake lights, hazard lights, turn signals
- **Buzzer**: play musical notes (C2–B6)
- **Screen**: display text, show emotions (happy, sad, angry, etc.)
- **Camera**: take a photo

## Prerequisites

- Python 3.11+
- AWS credentials configured (`aws configure`) with permissions for:
  - `bedrock:InvokeModel` (Bedrock runtime)
  - `iot:Publish` (IoT Data Plane)
- Zumi running `zumi_iot.py` and connected to IoT Core

## Setup

```bash
cd robolink-zumi/chatbot
pip install -r requirements.txt
```

## Run

```bash
uvicorn app:app --reload --port 8000
```

Then open http://localhost:8000

## Configuration

Environment variables (all optional, defaults match existing setup):

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDROCK_REGION` | `us-east-1` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | Bedrock model ID |
| `IOT_ENDPOINT` | `a3zsx6a5du4px-ats.iot.us-east-1.amazonaws.com` | IoT Core endpoint |
| `IOT_REGION` | `us-east-1` | AWS region for IoT |
| `IOT_THING_NAME` | `robolink-zumi` | IoT thing name |

## Example Prompts

- "Turn on the headlights"
- "Play a happy melody"
- "Show me a sad face"
- "What's the battery level?"
- "Check if there's something in front of Zumi"
- "Flash the hazard lights and display 'Hello World'"
- "Take a photo"
