# XGO-Lite V2 Robodog — Physical AI Example

A Physical AI implementation using the [XGO-Lite V2](https://www.luwu.com/xgo-lite2) quadruped robot dog.

## Hardware

- **Platform**: XGO-Lite V2 (Raspberry Pi CM4)
- **Connectivity**: AWS IoT Greengrass
- **Capabilities**: Walking gaits, LCD screen, camera, preset actions, vision navigation

## Architecture

```
agent/bedrock-converse/ (cloud)
    │
    ▼ Greengrass component deployment
device/ (on Pi CM4)
    │
    ▼ xgolib + camera
Hardware (servos, LCD, camera)
```

## Directory Structure

```
example/xgo2/
├── components/                        # Greengrass components
│   ├── simple-camera-test/           # Basic camera-to-LCD display
│   │   ├── recipe.yaml
│   │   ├── deployment.json
│   │   └── show_camera.py
│   └── xgo2-vision-navigation/      # Vision-guided navigation
│       ├── recipe.yaml
│       ├── deployment.json
│       ├── depth_training.py
│       ├── model_validator.py
│       ├── neo_compiler.py
│       ├── xgo_tools.py
│       ├── HW_VALIDATION_RESULTS.md
│       └── src/                      # Main application source
│           ├── main.py
│           ├── bedrock_reasoner.py
│           ├── coordinate_mapper.py
│           ├── depth_estimator.py
│           ├── grip_controller.py
│           ├── grip_reasoner.py
│           ├── lcd_display.py
│           ├── nav_controller.py
│           ├── vision_inference.py
│           └── requirements.txt
├── specs/                            # Design documents
│   ├── design.md
│   └── requirements.md
└── references/                       # Hardware API reference
    ├── references.md
    └── xgolib.py
```

## Deployment

```bash
# Deploy via Greengrass
python iot/greengrass/deploy.py
```

## Device-Side Requirements

- Python 3.9 (Raspberry Pi CM4)
- `xgolib` — robot motion control
- `LCD_2inch` — SPI display driver
- `cv2` + `PIL` — camera and image rendering
- AWS IoT Greengrass v2 runtime
