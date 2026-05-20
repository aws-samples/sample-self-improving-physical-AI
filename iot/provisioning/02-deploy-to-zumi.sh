#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# 02-deploy-to-zumi.sh
# Transfers the IoT app + certs to the Zumi hardware over SSH and
# launches the app to verify connectivity.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

THING_NAME="${1:-robolink-zumi}"
ZUMI_HOST="${ZUMI_HOST:-pi@10.131.141.40}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE_DIR="${SCRIPT_DIR}/staging/${THING_NAME}"
REMOTE_DIR="/home/pi/zumi-iot"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# ── Validate staging directory exists ─────────────────────────────────────
if [ ! -d "${STAGE_DIR}" ]; then
    echo "ERROR: Staging directory not found: ${STAGE_DIR}"
    echo "       Run 01-provision-iot-thing.sh first."
    exit 1
fi

if [ ! -f "${STAGE_DIR}/config.json" ]; then
    echo "ERROR: config.json not found in staging directory."
    exit 1
fi

echo "==> Deploying to ${ZUMI_HOST}:${REMOTE_DIR}"

# ── 1. Create remote directory structure ──────────────────────────────────
echo "    Creating remote directories..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "mkdir -p ${REMOTE_DIR}/certs"

# ── 2. Transfer files ────────────────────────────────────────────────────
echo "    Transferring app and config..."
scp ${SSH_OPTS} "${SCRIPT_DIR}/zumi_iot.py" "${ZUMI_HOST}:${REMOTE_DIR}/zumi_iot.py"
scp ${SSH_OPTS} "${STAGE_DIR}/config.json" "${ZUMI_HOST}:${REMOTE_DIR}/config.json"

echo "    Transferring certificates..."
scp ${SSH_OPTS} "${STAGE_DIR}/certs/device-certificate.pem.crt" "${ZUMI_HOST}:${REMOTE_DIR}/certs/"
scp ${SSH_OPTS} "${STAGE_DIR}/certs/private.pem.key" "${ZUMI_HOST}:${REMOTE_DIR}/certs/"
scp ${SSH_OPTS} "${STAGE_DIR}/certs/AmazonRootCA1.pem" "${ZUMI_HOST}:${REMOTE_DIR}/certs/"

# ── 3. Set permissions ───────────────────────────────────────────────────
echo "    Setting permissions..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "chmod 600 ${REMOTE_DIR}/certs/private.pem.key"
ssh ${SSH_OPTS} "${ZUMI_HOST}" "chmod 644 ${REMOTE_DIR}/certs/device-certificate.pem.crt ${REMOTE_DIR}/certs/AmazonRootCA1.pem"

# ── 4. Verify files on device ────────────────────────────────────────────
echo "    Verifying deployment..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "ls -la ${REMOTE_DIR}/ ${REMOTE_DIR}/certs/"

echo ""
echo "==> Deployment complete!"
echo "    Remote path: ${REMOTE_DIR}"
echo ""
echo "    To run manually:  ssh ${ZUMI_HOST} 'python3 ${REMOTE_DIR}/zumi_iot.py'"
echo "    To test (03):     bash ${SCRIPT_DIR}/03-verify-connection.sh ${THING_NAME}"
