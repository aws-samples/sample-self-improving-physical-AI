# Hardware Validation Results — XGO2 Vision Navigation

**Date:** 2026-04-21
**Component:** com.xgo.VisionNavigation v1.0.5
**Device:** xgo-robodog (Raspberry Pi CM4, aarch64)

## Deployment Summary

| Item | Value |
|------|-------|
| Final deployment ID | `9064c2fd-9af8-474a-be62-1dbcf032a24c` |
| Component version | 1.0.5 |
| Component state | RUNNING |
| S3 bucket | 654654616949-use1-greengrass |
| Target device | xgo-robodog |
| Region | us-east-1 |

## Task 14.2: Model Compilation and Validation

### Neo Compilation
- **Job name:** xgo2-neo-ecae564d
- **Framework:** TFLite 1.15
- **Input shape:** `{"normalized_input_image_tensor": [1, 300, 300, 3]}`
- **Target device:** rasp4b (CM4 aarch64 with NEON SIMD)
- **Status:** COMPLETED
- **Output:** `s3://654654616949-use1-greengrass/neo-output/ssd_mobilenet_v1_coco-rasp4b.tar.gz`
- **Neo output contents:** compiled.so, libdlr.so, compiled.params, compiled_model.json, compiled.meta, manifest, dlr.h

### Model Validation
| Check | Result | Details |
|-------|--------|---------|
| TFLite model | PASS | Input shape (1, 300, 300, 3), uint8 quantized |
| TFLite outputs | PASS | 4 tensors: boxes [1,10,4], classes [1,10], scores [1,10], count [1] |
| Neo output archive | PASS | 2 .so files, 3 model files |
| Label map | PASS | 91 COCO class names |

### Model Package
- **model.zip:** 7.9 MB (TFLite fallback + Neo-compiled DLR model + labels)

### Issues Found and Fixed
1. **Framework version:** Neo requires `1.15` or `2.4` for TFLite, not `2.0`
2. **Input tensor name:** Must use `normalized_input_image_tensor` (not `input`)

## Task 14.3: Inference on Real Hardware

### Component Initialization
| Component | Status | Details |
|-----------|--------|---------|
| XGO dog | OK | port=/dev/ttyAMA0, version=xgolite |
| Camera | OK | index=0, 320x240 |
| LCD display | OK | 320x240 SPI |
| Labels | OK | 91 labels loaded |
| DLR backend | FAILED | No `dlr` module installed (expected) |
| TFLite backend | OK | Loaded detect.tflite via tensorflow.lite |
| Inference engine | OK | backend=tflite |
| Bedrock client | OK | region=us-east-1, Claude 3 Haiku |
| Greengrass IPC | OK | Connected to /greengrass/v2/ipc.socket |
| MQTT subscription | OK | xgo-robodog/vision/command |

### Issues Found and Fixed
1. **xgolib not found:** Greengrass runs as root, `/home/pi/cm4-main` not in PYTHONPATH. Fixed by adding `PYTHONPATH` export in recipe run script.
2. **model.zip nesting:** ZIP contained `model/` prefix, causing double-nesting at `artifacts-unarchived/.../model/model/`. Fixed by packaging files at ZIP root.
3. **TensorFlow not found:** TF installed in pi user's site-packages, not system-wide. Fixed by adding `/home/pi/.local/lib/python3.9/site-packages` to PYTHONPATH.
4. **uint8 input mismatch:** Quantized model expects uint8 input, but `preprocess()` normalized to float32. Fixed `_detect_tflite()` to check input dtype and pass uint8 for quantized models.
5. **Camera conflict:** `main.py` opened camera during init, `NavigationSession.run()` tried to open a second instance. Fixed by passing shared camera via config dict.

## Task 14.4: Navigation on Real Hardware

### Navigation Test
- **Command:** `{"action": "navigate_to_target", "target_label": "cup", "max_steps": 30, "speed": 15}`
- **Result:** Navigation loop executed successfully
- **Inference:** Running without errors (uint8 input fix applied)
- **IMU reading:** Serial data received from XGO (roll/pitch)
- **Steering:** Turn commands sent to XGO motors during scan
- **Termination:** `target_lost` after 11 steps (no cup in front of camera)
- **dog.reset():** Called on termination (reset command visible in serial data)
- **LCD:** Camera feed with detection overlays displayed

## Task 14.5: Safety Features

| Feature | Status | Evidence |
|---------|--------|----------|
| Stop command | VERIFIED | "Stop command received" in logs |
| Target lost detection | VERIFIED | "Target lost after 10 frames, scanning..." |
| Scan behavior | VERIFIED | Robot physically rotated (turn commands in serial data) |
| dog.reset() on termination | VERIFIED | Reset command in serial data after session end |
| IMU tilt detection | CODE VERIFIED | Logic in place, requires physical tilt to trigger |
| Battery check | CODE VERIFIED | Logic in place, requires low battery to trigger |
| Speed clamping | CODE VERIFIED | max 25, enforced in clamp_speed() |
| Duration clamping | CODE VERIFIED | max 1.0s, enforced in clamp_duration() |

## Task 14.6: Bedrock Integration

| Feature | Status | Evidence |
|---------|--------|----------|
| Bedrock client init | VERIFIED | "Bedrock client initialized: region=us-east-1, model=anthropic.claude-3-haiku" |
| TES credentials | VERIFIED | Client created using default credential chain (TES) |
| Rate limiting | CODE VERIFIED | 5-second minimum between calls |
| Non-blocking errors | CODE VERIFIED | Errors caught, navigation continues |
| MQTT publishing | CODE VERIFIED | Responses published to xgo-robodog/vision/bedrock |

Note: Bedrock trigger requires high-confidence detection (>0.7) with a real object. The code path is verified through initialization and navigation loop structure.

## Version History

| Version | Changes |
|---------|---------|
| 1.0.0 | Initial deployment — xgolib not found |
| 1.0.1 | Added sys.path for /home/pi/cm4-main — labels not found |
| 1.0.2 | Fixed model.zip structure (root-level files) — TFLite not found |
| 1.0.3 | Added PYTHONPATH in recipe for pi user packages — RUNNING |
| 1.0.4 | Fixed camera sharing (shared VideoCapture) — inference dtype error |
| 1.0.5 | Fixed uint8 input for quantized model — full navigation working |

## Component Left Deployed

The component `com.xgo.VisionNavigation` v1.0.5 is left deployed and RUNNING on `xgo-robodog` for continued use. The standby screen is displayed on the LCD, and the component is listening for navigation commands on `xgo-robodog/vision/command`.
