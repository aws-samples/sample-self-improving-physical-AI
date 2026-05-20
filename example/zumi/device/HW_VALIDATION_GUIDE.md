# End-to-End Hardware Validation Guide

## Task 13: SageMaker Neo Vision Navigation — Hardware Validation

This guide walks through deploying and testing the vision navigation system
on the real Zumi hardware. Each section corresponds to a subtask in the spec.

---

## Prerequisites

- Zumi powered on and connected to the network at `10.131.141.40`
- AWS credentials configured locally (`aws configure`)
- `NEO_ROLE_ARN` environment variable set to your SageMaker execution role
- A pre-trained MobileNet V1 SSD TFLite model (128x128 input) available locally
- A `labels.txt` file with COCO class names (one per line, zero-indexed)

---

## 13.1 — Deploy Code to Device

```bash
# Deploy all device-side files (zumi_iot.py, ota_agent.py, vision_inference.py,
# nav_controller.py, ota_watchdog.sh, config.json)
bash robolink-zumi/scripts/deploy-chatbot-update.sh

# Verify service starts cleanly — look for "OTA Agent started" in logs
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 \
  "sudo systemctl restart zumi-iot && sleep 5 && sudo journalctl -u zumi-iot --no-pager -n 30"

# Verify model directory exists
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 "ls -la /home/pi/models/"
```

**Expected output**: Service starts, "OTA Agent started" appears in logs.
If model directory is empty, navigation will be disabled (expected until 13.3).

---

## 13.2 — Compile Model with SageMaker Neo and Validate

```bash
# Set your SageMaker role ARN
export NEO_ROLE_ARN="arn:aws:iam::ACCOUNT_ID:role/YOUR_SAGEMAKER_ROLE"

# Option A: Run the automated script
cd robolink-zumi/chatbot
python run_neo_compile_and_validate.py

# Option B: Run interactively in Python
cd robolink-zumi/chatbot
python3
```

```python
from neo_compiler import CompilationConfig, compile_model
config = CompilationConfig(
    s3_input_uri="s3://zumi-chatbot-photos/models/mobilenet_ssd_v1.tar.gz",
    s3_output_location="s3://zumi-chatbot-photos/neo-output/",
    framework="tflite",
    framework_version="1.15",
    input_shape={"input": [1, 128, 128, 3]},
    target_device="rasp3b",
    role_arn="<NEO_ROLE_ARN>",
    max_runtime_seconds=900,
)
result = compile_model(config)
print(result)
```

Then download the compiled model and validate:

```python
from model_validator import validate_tflite_model, validate_neo_output, validate_label_map
print(validate_tflite_model("model.tflite", (1, 128, 128, 3)))
print(validate_neo_output("compiled_model.tar.gz"))
print(validate_label_map("labels.txt"))
```

**Expected**: All validations return `valid=True`. The Neo output may have
warnings about NEON compatibility — this is expected since the TFLite
fallback will be used on the Pi Zero W.

---

## 13.3 — Deploy Model to Zumi via OTA

```bash
# Ensure model files are in robolink-zumi/chatbot/
cd robolink-zumi/chatbot

# Option A: Run the automated script
python run_model_deploy.py

# Option B: Run interactively
python3
```

```python
from model_deployer import deploy_model
result = deploy_model(
    compiled_tar_path="compiled_model.tar.gz",
    fallback_tflite_path="model.tflite",
    label_map_path="labels.txt",
    thing_name="robolink-zumi",
    target_model_dir="/home/pi/models/",
)
print(result)  # {"job_id": "...", "job_arn": "..."}
```

Monitor and verify:

```bash
# Check job status
aws iot describe-job-execution --job-id <JOB_ID> --thing-name robolink-zumi

# Verify files on device
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 "ls -la /home/pi/models/"

# Check device logs for OTA activity
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 \
  "sudo journalctl -u zumi-iot --no-pager -n 50"
```

**Expected**: Job status SUCCEEDED. Model files present and non-empty in
`/home/pi/models/`. Tar.gz extracted.

---

## 13.4 — Test Inference on Real Hardware

```bash
# Deploy the test script
scp -o StrictHostKeyChecking=no \
  robolink-zumi/scripts/test_inference_hw.py \
  pi@10.131.141.40:/home/pi/zumi-iot/test_inference_hw.py

# Run it (place a known object in front of the camera first)
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 \
  "python3 /home/pi/zumi-iot/test_inference_hw.py"
```

**Expected output**:
- Backend: `tflite` (DLR will likely fail due to NEON on ARMv6)
- Inference time < 2.0 seconds
- At least one detection if a known object is in view

---

## 13.5 — Test Navigation on Real Hardware

Place a target object (e.g., a cup) ~50cm in front of the Zumi on a flat surface.

```bash
# Watch device logs in one terminal
ssh -o StrictHostKeyChecking=no pi@10.131.141.40 \
  "sudo journalctl -u zumi-iot -f --no-pager"

# Send navigate command via MQTT (from another terminal)
aws iot-data publish \
  --topic "zumi/robolink-zumi/command" \
  --payload '{"action":"navigate_to_target","target_label":"cup","max_steps":30,"speed":25}' \
  --cli-binary-format raw-in-base64-out
```

**Expected**: Zumi moves toward the target, steering left/right as needed.
Navigation terminates with `target_reached` when close. Logs show
`navigation_status` messages each iteration.

---

## 13.6 — Test Obstacle Avoidance

Place an obstacle between the Zumi and the target object.

```bash
# Send navigate command
aws iot-data publish \
  --topic "zumi/robolink-zumi/command" \
  --payload '{"action":"navigate_to_target","target_label":"cup","max_steps":30,"speed":25}' \
  --cli-binary-format raw-in-base64-out
```

**Expected**: Zumi detects obstacle via IR, stops, reverses, turns away,
and resumes navigation. Logs show `obstacle_detected: true`.

For drop-off testing (table edge), use with caution:
- Place Zumi near a table edge
- Send a navigate command
- Verify it stops when bottom IR sensors detect the edge

---

## 13.7 — Test Stop Command During Navigation

```bash
# Start navigation
aws iot-data publish \
  --topic "zumi/robolink-zumi/command" \
  --payload '{"action":"navigate_to_target","target_label":"cup","max_steps":50,"speed":25}' \
  --cli-binary-format raw-in-base64-out

# Wait a few seconds, then send stop
sleep 3
aws iot-data publish \
  --topic "zumi/robolink-zumi/command" \
  --payload '{"action":"stop"}' \
  --cli-binary-format raw-in-base64-out
```

**Expected**: Navigation terminates immediately with reason `stopped`.
Motors halt. Final status published to telemetry.

---

## 13.8 — Document Results and Clean Up

Record the following evidence:
- Job ID from model deployment
- Model files deployed (ls output from device)
- Inference backend used (tflite or dlr)
- Navigation test results (target_reached, obstacle avoidance, stop)
- Device log excerpts

Clean up:

```bash
# Delete the test IoT Job
aws iot delete-job --job-id <JOB_ID> --force

# Leave model files on device for continued use
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Device unreachable | Check Zumi is powered on and on the network |
| Service won't start | Check logs: `ssh pi@10.131.141.40 "sudo journalctl -u zumi-iot --no-pager -n 50"` |
| Navigation disabled | Model directory empty — run 13.3 first |
| DLR fails to load | Expected on Pi Zero W (ARMv6/no NEON) — TFLite fallback should work |
| Inference too slow | Ensure 128x128 model is used, not a larger input size |
| OTA job stuck | Check device connectivity and OTA agent logs |
