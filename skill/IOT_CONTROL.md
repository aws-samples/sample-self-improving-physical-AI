---
name: iot-device-control
description: Control physical robots via AWS IoT Core and Greengrass. Use when asked to send commands to real hardware (Zumi robot car, XGO2 robodog), read sensor telemetry, take photos, control LEDs/buzzer/screen, trigger OTA updates, or manage device connectivity. Covers MQTT command dispatch, presigned URL photo flow, and Greengrass component deployment.
---

# IoT Device Control — Physical Robot Commands

Send commands to physical robots via AWS IoT Core (MQTT) and manage deployments via Greengrass.

## Prerequisites

| Component | Required |
|-----------|----------|
| AWS credentials | IAM role with IoT Data + S3 access |
| IoT Thing | Provisioned via `iot/provisioning/` scripts |
| Device online | `zumi_iot.py` or Greengrass running on device |
| S3 bucket | For photo upload/download (presigned URLs) |

## Supported Platforms

| Platform | Connection | Device Code |
|----------|-----------|-------------|
| Robolink Zumi | IoT Core (MQTT + mTLS) | `example/zumi/device/zumi_iot.py` |
| XGO2 Robodog | IoT Greengrass | `example/xgo2/components/` |

## MQTT Topics

```
zumi/<thing_name>/command     # Cloud → Device (JSON command)
zumi/<thing_name>/telemetry   # Device → Cloud (sensor data)
zumi/<thing_name>/photo_ack   # Device → Cloud (photo upload done)
```

## Command Format

```json
{
  "action": "read_sensors" | "set_led" | "play_buzzer" | "show_screen" | "take_photo" | "drive",
  "parameters": { ... }
}
```

## Photo Flow (Presigned URL)

1. Agent generates S3 PUT presigned URL
2. Sends URL to device via MQTT command
3. Device captures photo, uploads JPEG to S3
4. Device publishes `photo_ack` on telemetry topic
5. Agent generates GET presigned URL, returns to user

## Agent Integration

The chatbot agent (`agent/bedrock-converse/`) uses:
- `iot_client.py` — Publish commands, generate presigned URLs
- `iot_dispatcher.py` — Route commands to correct device/topic
- `hardware_registry.py` — Select correct tool set per platform

## Provisioning New Devices

```bash
# IoT Core (Zumi)
bash iot/provisioning/01-provision-iot-thing.sh <thing_name>
bash iot/provisioning/02-deploy-to-zumi.sh <thing_name>
bash iot/provisioning/03-verify-connection.sh <thing_name>

# Greengrass (XGO2)
python iot/greengrass/deploy.py
```
