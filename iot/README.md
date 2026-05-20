# IoT — Device Connectivity Layer

This directory contains the infrastructure and tooling for connecting physical robots to the cloud via AWS IoT Core and AWS IoT Greengrass.

## Architecture

```
Cloud Agent (agent/bedrock-converse/)
    │
    ▼ MQTT publish
AWS IoT Core ──── mutual TLS ────► Device (example/zumi/, example/xgo2/)
    │                                       │
    ▼                                       ▼
S3 (presigned URLs)                  Telemetry / Photo ack
```

## Directory Structure

```
iot/
├── provisioning/              # Scripts to set up IoT Things and deploy to devices
│   ├── 01-provision-iot-thing.sh    # Create IoT Thing, certs, policy
│   ├── 02-deploy-to-zumi.sh        # SCP app + certs to device
│   ├── 03-verify-connection.sh     # Verify MQTT connectivity
│   └── deploy-chatbot-update.sh    # Quick redeploy after code changes
├── greengrass/                # Greengrass deployment tooling
│   ├── deploy.py             # Component deployment script
│   └── greengrass.json       # Greengrass core device info
└── README.md
```

## Provisioning a New Device

```bash
# 1. Create IoT Thing, certificates, and policy
bash iot/provisioning/01-provision-iot-thing.sh [thing_name]

# 2. Deploy app + certs to device over SSH
bash iot/provisioning/02-deploy-to-zumi.sh [thing_name]

# 3. Verify MQTT connectivity
bash iot/provisioning/03-verify-connection.sh [thing_name]
```

## MQTT Topic Convention

Topics follow the pattern: `<platform>/<thing_name>/<channel>`

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `zumi/<thing>/command` | Cloud → Device | Command dispatch |
| `zumi/<thing>/telemetry` | Device → Cloud | Sensor readings |
| `zumi/<thing>/photo_ack` | Device → Cloud | Photo upload confirmation |

## Greengrass (XGO2)

The XGO2 robodog uses AWS IoT Greengrass for component deployment. See `greengrass/deploy.py` for the deployment workflow.
