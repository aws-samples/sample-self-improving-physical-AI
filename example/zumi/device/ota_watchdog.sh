#!/usr/bin/env bash
# ota_watchdog.sh — OTA self-update watchdog
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Called by the OTA Agent when the update includes ota_agent.py or
# zumi_iot.py itself (Req 6.5). Since the Python process will be
# replaced, this script handles the restart and health check externally.
#
# Usage: ota_watchdog.sh <job_id> <thing_name>
#
# Flow:
#   1. Restart the zumi-iot systemd service
#   2. Poll systemctl is-active for up to 60 seconds
#   3. On success: write SUCCEEDED result JSON
#   4. On failure: restore backup files, restart service, write FAILED result JSON
#
# The result is written to /home/pi/zumi-iot/.ota-watchdog-result.json
# which the OTA Agent reads on startup to report final job status.
#
# Uses set -uo pipefail (no -e) per SSH gotchas in steering rules.
set -uo pipefail

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
JOB_ID="${1:?Usage: ota_watchdog.sh <job_id> <thing_name>}"
THING_NAME="${2:?Usage: ota_watchdog.sh <job_id> <thing_name>}"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULT_FILE="/home/pi/zumi-iot/.ota-watchdog-result.json"
BACKUP_DIR="/home/pi/zumi-iot/.ota-backup"
HEALTH_CHECK_TIMEOUT=60
POLL_INTERVAL=2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
    echo "[ota_watchdog] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

write_result() {
    # Write the result JSON atomically (write to tmp, then move)
    local tmp_file="${RESULT_FILE}.tmp"
    echo "$1" > "${tmp_file}"
    mv "${tmp_file}" "${RESULT_FILE}"
    log "Result written to ${RESULT_FILE}"
}

# ---------------------------------------------------------------------------
# Step 1: Restart the zumi-iot service
# ---------------------------------------------------------------------------
log "Restarting zumi-iot service (job: ${JOB_ID})"
sudo systemctl restart zumi-iot

# ---------------------------------------------------------------------------
# Step 2: Poll health check — wait for active state
# ---------------------------------------------------------------------------
log "Polling service health (timeout: ${HEALTH_CHECK_TIMEOUT}s, interval: ${POLL_INTERVAL}s)"
elapsed=0
healthy=false

while [ "${elapsed}" -lt "${HEALTH_CHECK_TIMEOUT}" ]; do
    status=$(systemctl is-active zumi-iot 2>/dev/null || true)
    if [ "${status}" = "active" ]; then
        healthy=true
        break
    fi
    sleep "${POLL_INTERVAL}"
    elapsed=$((elapsed + POLL_INTERVAL))
done

# ---------------------------------------------------------------------------
# Step 3: Write result
# ---------------------------------------------------------------------------
timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

if [ "${healthy}" = true ]; then
    # -----------------------------------------------------------------------
    # Success — service is active
    # -----------------------------------------------------------------------
    log "Health check passed after ${elapsed}s"
    write_result "{
  \"status\": \"SUCCEEDED\",
  \"job_id\": \"${JOB_ID}\",
  \"timestamp\": \"${timestamp}\"
}"
else
    # -----------------------------------------------------------------------
    # Failure — health check timed out, perform rollback
    # -----------------------------------------------------------------------
    log "Health check FAILED after ${HEALTH_CHECK_TIMEOUT}s — starting rollback"

    rollback_ok=true
    manifest_file="${BACKUP_DIR}/manifest.json"

    if [ -f "${manifest_file}" ]; then
        # Read each backed-up file from the manifest and restore it.
        # The manifest is JSON; we parse it with a simple Python one-liner
        # written to a temp script (per agent rules: never use python3 -c).
        restore_script=$(mktemp /tmp/ota_restore_XXXXXX.py)
        cat > "${restore_script}" << 'PYEOF'
import json, sys, shutil, os
manifest_path = sys.argv[1]
with open(manifest_path, "r") as f:
    manifest = json.load(f)
for entry in manifest.get("files", []):
    src = entry.get("backup_path", "")
    dst = entry.get("original_path", "")
    if not src or not dst:
        continue
    if not os.path.isfile(src):
        print("WARN: backup file missing: %s" % src)
        continue
    target_dir = os.path.dirname(dst)
    if target_dir and not os.path.isdir(target_dir):
        os.makedirs(target_dir)
    shutil.copy2(src, dst)
    perms = entry.get("permissions", "")
    if perms:
        try:
            os.chmod(dst, int(perms, 8))
        except (ValueError, TypeError):
            pass
    print("Restored: %s -> %s" % (src, dst))
PYEOF
        log "Restoring backup files from ${manifest_file}"
        if python3 "${restore_script}" "${manifest_file}"; then
            log "Backup files restored successfully"
        else
            log "ERROR: Failed to restore some backup files"
            rollback_ok=false
        fi
        rm -f "${restore_script}"
    else
        log "WARNING: No backup manifest found at ${manifest_file} — cannot restore files"
        rollback_ok=false
    fi

    # Restart the service with restored files
    log "Restarting zumi-iot service after rollback"
    sudo systemctl restart zumi-iot

    write_result "{
  \"status\": \"FAILED\",
  \"job_id\": \"${JOB_ID}\",
  \"reason\": \"health_check_timeout\",
  \"rollback_performed\": true,
  \"timestamp\": \"${timestamp}\"
}"

    if [ "${rollback_ok}" = true ]; then
        log "Rollback complete"
    else
        log "Rollback completed with warnings — manual intervention may be needed"
    fi
fi

log "Watchdog finished (job: ${JOB_ID})"
