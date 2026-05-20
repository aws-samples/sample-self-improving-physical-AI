# IoT Architecture — Physical Robot Connectivity

## Overview

This layer connects the AI agent to physical robots using AWS IoT Core (for direct MQTT) and AWS IoT Greengrass (for managed edge deployments).

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Cloud                                                            │
│                                                                  │
│  Browser Chat UI → FastAPI → Bedrock Converse API (tool use)    │
│                        │                                         │
│                        ▼                                         │
│                  IoT Dispatcher                                   │
│                   /         \                                     │
│                  ▼           ▼                                    │
│          IoT Core        Greengrass                              │
│          (MQTT)          (Component Deploy)                      │
└──────────┼───────────────────┼───────────────────────────────────┘
           │                   │
           ▼                   ▼
┌──────────────────┐  ┌──────────────────┐
│ Zumi (Pi Zero W) │  │ XGO2 (Pi CM4)    │
│ zumi_iot.py      │  │ Greengrass Agent  │
│ MQTT + mTLS      │  │ Component Runtime │
└──────────────────┘  └──────────────────┘
```

## Connection Patterns

### Pattern 1: IoT Core Direct (Zumi)

- **Transport**: MQTT over mutual TLS (X.509 certificates)
- **Provisioning**: One-time script creates Thing, certs, policy
- **Device code**: Long-running Python process subscribes to command topic
- **Latency**: ~100-300ms round-trip
- **Best for**: Simple devices, direct command/response

### Pattern 2: IoT Greengrass (XGO2)

- **Transport**: Greengrass component deployment
- **Provisioning**: Greengrass core device setup + component recipes
- **Device code**: Managed components with lifecycle (install, run, shutdown)
- **Latency**: Deployment is async; runtime commands via local IPC
- **Best for**: Complex devices needing OTA updates, ML inference at edge

## Photo Upload Flow

```
Agent                    IoT Core              Device              S3
  │                        │                     │                  │
  │─── generate PUT URL ──►│                     │                  │
  │─── publish command ───►│──── command ───────►│                  │
  │                        │                     │── upload JPEG ──►│
  │                        │◄─── photo_ack ─────│                  │
  │◄── telemetry ─────────│                     │                  │
  │─── generate GET URL ──►│                     │                  │
  │─── return to user ────►│                     │                  │
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Device ↔ IoT Core | Mutual TLS (X.509 certificates per device) |
| Agent ↔ IoT Core | IAM role (iot:Publish, iot:Subscribe) |
| Photo upload | S3 presigned PUT URL (time-limited, scoped to key) |
| Photo download | S3 presigned GET URL (time-limited) |
| Greengrass | IAM role + component signing |

## Adding a New Robot Platform

1. Create `example/<platform>/device/` with the device-side bridge code
2. Add tool definitions in `agent/bedrock-converse/tools/`
3. Register the hardware profile in `agent/bedrock-converse/hardware_registry.py`
4. Choose connection pattern (IoT Core direct or Greengrass)
5. Add provisioning scripts to `iot/provisioning/` if using IoT Core
