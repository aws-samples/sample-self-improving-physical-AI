# Hardware Reference: Robolink Zumi

## Device Identity

- **Thing name in IoT Core:** `robolink-zumi`
- **AWS Account:** 654654616949
- **Region:** us-east-1
- **IoT Endpoint:** `a3zsx6a5du4px-ats.iot.us-east-1.amazonaws.com`
- **Network IP:** 10.131.141.40
- **SSH:** `pi@10.131.141.40` (key auth, passwordless)

## System Specs

| Component | Detail |
|-----------|--------|
| Board | Raspberry Pi Zero W |
| Architecture | armv6l |
| OS | Raspbian GNU/Linux, kernel 4.19.42+ |
| Python | **3.5.3** |
| RAM | 512 MB |
| WiFi | 802.11n (2.4 GHz) |
| Home directory | `/home/pi/` |

## Sensors & Actuators

### Motors
- 2 DC motors (left + right), differential drive
- Speed range: 0–80 (forward/reverse), 0–127 (low-level `control_motors`)
- PID-controlled heading correction via gyroscope

### IR Sensors (6 total)
- Front left, front right (obstacle detection)
- Bottom left, bottom right (line following)
- Back left, back right (reverse collision avoidance)
- Value range: 0–255 (lower = more reflected light)
- Default detection threshold: 100
- Requires 0.1s delay between rapid reads (I2C bus)

### MPU (Motion Processing Unit)
- Gyroscope: X, Y, Z angular velocity → integrated to angles
- Accelerometer: X, Y, Z linear acceleration
- Orientation detection: upright, upside down, left/right side, face up/down, falling, accelerating
- Calibration: `calibrate_gyro()` — must be on flat surface, not moving

### Camera (PiCamera)
- Default resolution: 160×128 (configurable up to 1280×960)
- Interface: `zumi.util.camera.Camera`
- No X11 display server — use OLED screen or save to file

### OLED Screen
- 128×64 monochrome
- Interface: `zumi.util.screen.Screen`
- Supports text, shapes, emotion faces, clock

### LEDs
- 2 front white LEDs (headlights)
- 2 rear LEDs (brake lights)
- Individually controllable, support hazard/signal patterns

### Buzzer
- Notes C2 (1) through B6 (60)
- Duration: 0–2500ms in 100ms increments
- Note 0 = silence

### Battery
- LiPo, 3.0V (empty) to 4.2V (full)
- Reads ~0.07V when USB-powered/charging (not on battery)
- Updated every 500ms

## Pre-installed Software

```
awscrt==0.11.17
awsiotsdk==1.5.15
zumi==1.66
zumidashboard==2.91
```

## Filesystem Layout

```
/home/pi/
├── Dashboard/           # Zumi web dashboard
├── Desktop/
├── offsets.txt          # MPU calibration offsets
├── zumi-iot/            # Our deployed IoT app
│   ├── zumi_iot.py
│   ├── config.json
│   └── certs/
│       ├── device-certificate.pem.crt
│       ├── private.pem.key
│       └── AmazonRootCA1.pem
└── log_Zumi_Content*    # Zumi system logs
```

## Validated Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| SSH passwordless access | ✅ Verified | Key auth to pi@10.131.141.40 |
| Python 3.5 execution | ✅ Verified | No f-strings, no dataclasses |
| awsiotsdk import | ✅ Verified | awscrt + awsiot both load |
| MQTT connect to IoT Core | ✅ Verified | mTLS with X.509 certs |
| MQTT publish telemetry | ✅ Verified | QoS 1, JSON payload |
| MQTT subscribe to commands | ✅ Verified | Callback-based |
| Zumi motor control | ✅ Available | `from zumi.zumi import Zumi` |
| Zumi screen | ✅ Available | `from zumi.util.screen import Screen` |
| Zumi IR sensors | ✅ Available | 6 sensors, 0–255 range |
| Zumi gyroscope | ✅ Available | 3-axis angles |
| Zumi battery read | ✅ Available | Returns voltage |
| datetime.timezone.utc | ✅ Verified | Works on Python 3.5.3 |
| nohup background process | ✅ Verified | Requires `disown; exit 0` pattern |

## Known Limitations

1. **Python 3.5.3** — no f-strings, no dataclasses, no walrus operator, no match/case
2. **512 MB RAM** — not suitable for heavy ML models (TensorFlow, PyTorch)
3. **armv6l** — many modern Python wheels don't ship armv6l binaries
4. **No GPU** — CPU-only inference
5. **Single-core** — Pi Zero W has a single ARM1176JZF-S core
6. **2.4 GHz WiFi only** — no 5 GHz support
7. **Old OpenSSH** — triggers post-quantum key exchange warnings (harmless)
