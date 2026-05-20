#!/usr/bin/env bash
# Deploy the Zumi IoT bridge, OTA agent, watchdog, and config, then restart.
set -uo pipefail

ZUMI_HOST="${ZUMI_HOST:-pi@10.131.141.40}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGING_DIR="${SCRIPT_DIR}/staging/robolink-zumi"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

echo "==> Deploying zumi_iot.py to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/zumi_iot.py" "${ZUMI_HOST}:/home/pi/zumi-iot/zumi_iot.py"

echo "==> Deploying ota_agent.py to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/ota_agent.py" "${ZUMI_HOST}:/home/pi/zumi-iot/ota_agent.py"

echo "==> Deploying vision_inference.py to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/vision_inference.py" "${ZUMI_HOST}:/home/pi/zumi-iot/vision_inference.py"

echo "==> Deploying nav_controller.py to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/nav_controller.py" "${ZUMI_HOST}:/home/pi/zumi-iot/nav_controller.py"

echo "==> Deploying ota_watchdog.sh to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/ota_watchdog.sh" "${ZUMI_HOST}:/home/pi/zumi-iot/ota_watchdog.sh"
ssh ${SSH_OPTS} "${ZUMI_HOST}" "chmod +x /home/pi/zumi-iot/ota_watchdog.sh"

echo "==> Deploying config.json to ${ZUMI_HOST}..."
scp ${SSH_OPTS} "${STAGING_DIR}/config.json" "${ZUMI_HOST}:/home/pi/zumi-iot/config.json"

echo "==> Creating OTA staging, backup, and models directories..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "mkdir -p /home/pi/zumi-iot/.ota-staging /home/pi/zumi-iot/.ota-backup /home/pi/models"

echo "==> Restarting zumi-iot service..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "sudo systemctl restart zumi-iot"

echo "==> Waiting for startup..."
sleep 10

echo "==> Checking service status..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "sudo systemctl status zumi-iot --no-pager -l | head -15"

echo ""
echo "==> Done. Test with: curl -X POST http://127.0.0.1:8000/api/chat -H 'Content-Type: application/json' -d '{\"message\": \"take a photo\"}'"
