# Robolink Zumi — Physical AI Example

A complete Physical AI implementation using the [Robolink Zumi](https://www.robolink.com/zumi) educational robot car.

## Hardware

- **Platform**: Robolink Zumi (Raspberry Pi Zero W)
- **Connectivity**: AWS IoT Core (MQTT over mutual TLS)
- **Capabilities**: IR sensors, LEDs, buzzer, OLED screen, camera, differential-drive motors

## Architecture

```
agent/bedrock-converse/ (cloud)
    │
    ▼ MQTT via IoT Core
device/zumi_iot.py (on Pi Zero W)
    │
    ▼ Zumi Python SDK
Hardware (motors, sensors, LEDs, camera)
```

## Directory Structure

```
example/zumi/
├── device/                    # Code that runs ON the Zumi (Pi Zero W)
│   ├── zumi_iot.py           # IoT bridge: MQTT commands → Zumi hardware
│   ├── nav_controller.py    # Autonomous navigation controller
│   ├── vision_inference.py  # On-device vision inference
│   ├── ota_agent.py         # Over-the-air update agent
│   ├── ota_watchdog.sh      # OTA watchdog script
│   ├── zumi-iot.service     # systemd unit file
│   └── test_inference_hw.py # Hardware inference test
└── specs/                    # Hardware reference documentation
    ├── hardware-reference.md
    └── how_does_zumi_see.md
```

## Deployment

```bash
# Provision IoT Thing (run once)
bash iot/provisioning/01-provision-iot-thing.sh my-zumi

# Deploy device code to Zumi
bash iot/provisioning/02-deploy-to-zumi.sh my-zumi

# Verify connection
bash iot/provisioning/03-verify-connection.sh my-zumi
```

## Device-Side Requirements

- Python 3.11 (runs on Pi Zero W)
- `awsiotsdk` — MQTT over mutual TLS
- `zumi` — hardware control library (pre-installed)
- `cv2` — image encoding for photo upload

## Running on Device

```bash
# Start manually
ssh pi@<device-ip> 'python3 /home/pi/zumi-iot/zumi_iot.py'

# Via systemd
ssh pi@<device-ip> 'sudo systemctl restart zumi-iot'
ssh pi@<device-ip> 'sudo systemctl status zumi-iot'
```
