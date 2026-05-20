#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# 03-verify-connection.sh
# Launches zumi_iot.py on the Zumi, waits for a telemetry message to
# appear in AWS IoT Core, then reports success/failure.
# ──────────────────────────────────────────────────────────────────────────
set -uo pipefail

THING_NAME="${1:-robolink-zumi}"
ZUMI_HOST="${ZUMI_HOST:-pi@10.131.141.40}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
REMOTE_DIR="/home/pi/zumi-iot"
TIMEOUT=30

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
TELEMETRY_TOPIC="zumi/${THING_NAME}/telemetry"

echo "==> Verifying Zumi IoT Core connection for thing: ${THING_NAME}"

# ── 1. Kill any existing instance ────────────────────────────────────────
echo "    Stopping any existing zumi_iot.py process..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" "kill \$(pgrep -f zumi_iot.py) 2>/dev/null; exit 0" || true
sleep 2

# ── 2. Start the app in background, capture output ──────────────────────
echo "    Starting zumi_iot.py on Zumi..."
ssh ${SSH_OPTS} "${ZUMI_HOST}" \
    "nohup python3 ${REMOTE_DIR}/zumi_iot.py > ${REMOTE_DIR}/zumi_iot.log 2>&1 & disown; exit 0"

# ── 3. Wait for the app to connect and publish ───────────────────────────
echo "    Waiting up to ${TIMEOUT}s for MQTT connection and first telemetry..."
CONNECTED=false
for i in $(seq 1 ${TIMEOUT}); do
    sleep 1
    # Check the log for the "Connected" and "Published telemetry" markers
    LOG_OUTPUT=$(ssh ${SSH_OPTS} "${ZUMI_HOST}" "cat ${REMOTE_DIR}/zumi_iot.log 2>/dev/null" || true)

    if echo "${LOG_OUTPUT}" | grep -q "Connected to AWS IoT Core"; then
        if echo "${LOG_OUTPUT}" | grep -q "Published telemetry"; then
            CONNECTED=true
            break
        fi
        # Connected but no telemetry yet — keep waiting
        printf "    [%02ds] Connected, waiting for first telemetry publish...\r" "$i"
    else
        printf "    [%02ds] Waiting for MQTT connection...\r" "$i"
    fi
done
echo ""

# ── 4. Show the log ──────────────────────────────────────────────────────
echo "--- Zumi app log (last 20 lines) ---"
ssh ${SSH_OPTS} "${ZUMI_HOST}" "tail -20 ${REMOTE_DIR}/zumi_iot.log 2>/dev/null" || true
echo "--- end log ---"

# ── 5. Report result ─────────────────────────────────────────────────────
if [ "${CONNECTED}" = true ]; then
    echo ""
    echo "============================================"
    echo "  SUCCESS: Zumi is connected to IoT Core!"
    echo "  Thing   : ${THING_NAME}"
    echo "  Topic   : ${TELEMETRY_TOPIC}"
    echo "============================================"
    echo ""
    echo "  The app is running in the background."
    echo "  To stop:  ssh ${ZUMI_HOST} 'pkill -f zumi_iot.py'"
    echo "  To view:  ssh ${ZUMI_HOST} 'tail -f ${REMOTE_DIR}/zumi_iot.log'"
    exit 0
else
    echo ""
    echo "============================================"
    echo "  FAILED: Could not verify connection"
    echo "  within ${TIMEOUT}s timeout."
    echo "============================================"
    echo ""
    echo "  Check the full log:"
    echo "    ssh ${ZUMI_HOST} 'cat ${REMOTE_DIR}/zumi_iot.log'"
    exit 1
fi
