#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: ShellCheck v0.10.0 + Semgrep OSS
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

#
# run_sim.sh - Wrapper to run Isaac Sim Python scripts inside the Docker container.
#
# Usage:
#   ./run_sim.sh <script_name.py> [script args...]
#
# Examples:
#   ./run_sim.sh manufacturing_scene.py --steps 200
#   ./run_sim.sh pick_and_place.py --pick-index 0 --place-pos "0.5,-0.8,0.5"
#   ./run_sim.sh robot_control.py --action home
#   ./run_sim.sh spawn_objects.py --type box --count 5
#   ./run_sim.sh capture_viewport.py --output /output/scene.png
#
# Environment variables:
#   ISAAC_SIM_IMAGE   - Docker image (default: nvcr.io/nvidia/isaac-sim:6.0.0-dev2)
#   ISAAC_SIM_HOME    - Cache/config directory (default: ~/docker/isaac-sim)
#   KEEP_CONTAINER    - If "1", don't remove container after run
#

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
ISAAC_SIM_IMAGE="${ISAAC_SIM_IMAGE:-nvcr.io/nvidia/isaac-sim:6.0.0-dev2}"
ISAAC_SIM_HOME="${ISAAC_SIM_HOME:-$HOME/docker/isaac-sim}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/../output"

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# ── Validate input ────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
    echo "Usage: $0 <script_name.py> [script args...]"
    echo ""
    echo "Available scripts:"
    echo "  manufacturing_scene.py  - Create a manufacturing environment"
    echo "  pick_and_place.py       - Robot pick and place demo"
    echo "  robot_control.py        - General robot arm control"
    echo "  spawn_objects.py        - Spawn objects in the scene"
    echo "  capture_viewport.py     - Capture a rendered image"
    echo ""
    echo "Examples:"
    echo "  $0 manufacturing_scene.py --steps 200 --capture /output/scene.png"
    echo "  $0 robot_control.py --action home"
    echo "  $0 pick_and_place.py --pick-index 0"
    exit 1
fi

SCRIPT_NAME="$1"
shift  # Remove script name, rest are script args

# Sanitize script name to prevent path traversal
SCRIPT_NAME=$(basename "$SCRIPT_NAME")
if [[ ! "$SCRIPT_NAME" =~ ^[a-zA-Z0-9_.-]+\.py$ ]]; then
    echo "ERROR: Invalid script name '${SCRIPT_NAME}'. Only alphanumeric, underscore, dash, and dot allowed. Must end in .py"
    exit 1
fi

SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"
if [ ! -f "${SCRIPT_PATH}" ]; then
    echo "ERROR: Script not found: ${SCRIPT_PATH}"
    echo "Available scripts in ${SCRIPT_DIR}:"
    ls -1 "${SCRIPT_DIR}"/*.py 2>/dev/null || echo "  (none)"
    exit 1
fi

# ── Check prerequisites ──────────────────────────────────────────────
echo "[run_sim] Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is not installed."
    exit 1
fi

if ! docker image inspect "${ISAAC_SIM_IMAGE}" &>/dev/null; then
    echo "ERROR: Isaac Sim image not found: ${ISAAC_SIM_IMAGE}"
    echo "Pull it with: docker pull ${ISAAC_SIM_IMAGE}"
    exit 1
fi

if ! nvidia-smi &>/dev/null; then
    echo "ERROR: NVIDIA GPU not detected (nvidia-smi failed)."
    exit 1
fi

echo "[run_sim] Prerequisites OK."
echo "[run_sim] Image: ${ISAAC_SIM_IMAGE}"
echo "[run_sim] Script: ${SCRIPT_NAME}"
echo "[run_sim] Args: $*"

# ── Ensure cache directories exist ───────────────────────────────────
mkdir -p "${ISAAC_SIM_HOME}/cache/main/ov"
mkdir -p "${ISAAC_SIM_HOME}/cache/main/warp"
mkdir -p "${ISAAC_SIM_HOME}/cache/computecache"
mkdir -p "${ISAAC_SIM_HOME}/config"
mkdir -p "${ISAAC_SIM_HOME}/data/documents"
mkdir -p "${ISAAC_SIM_HOME}/data/Kit"
mkdir -p "${ISAAC_SIM_HOME}/logs"
mkdir -p "${ISAAC_SIM_HOME}/pkg"

# ── Container name ────────────────────────────────────────────────────
CONTAINER_NAME="isaac-sim-$(echo "${SCRIPT_NAME}" | sed 's/\.py$//' | tr '.' '-')-$$"

# ── Cleanup trap ──────────────────────────────────────────────────────
cleanup() {
    if [ "${KEEP_CONTAINER:-0}" != "1" ]; then
        docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ── Run ───────────────────────────────────────────────────────────────
echo "[run_sim] Starting container: ${CONTAINER_NAME}"
echo "[run_sim] ──────────────────────────────────────────"

docker run \
    --name "${CONTAINER_NAME}" \
    --gpus all \
    --rm \
    --network=host \
    --security-opt=no-new-privileges:true \
    --cap-drop=ALL \
    --cap-add=SYS_ADMIN \
    --entrypoint ./python.sh \
    -e "ACCEPT_EULA=Y" \
    -e "PRIVACY_CONSENT=Y" \
    -e "OMNI_KIT_ACCEPT_EULA=YES" \
    -e "PYTHONUNBUFFERED=1" \
    -v "${ISAAC_SIM_HOME}/cache/main:/isaac-sim/.cache:rw" \
    -v "${ISAAC_SIM_HOME}/cache/computecache:/isaac-sim/.nv/ComputeCache:rw" \
    -v "${ISAAC_SIM_HOME}/logs:/isaac-sim/.nvidia-omniverse/logs:rw" \
    -v "${ISAAC_SIM_HOME}/config:/isaac-sim/.nvidia-omniverse/config:rw" \
    -v "${ISAAC_SIM_HOME}/data:/isaac-sim/.local/share/ov/data:rw" \
    -v "${ISAAC_SIM_HOME}/pkg:/isaac-sim/.local/share/ov/pkg:rw" \
    -v "${SCRIPT_DIR}:/scripts:ro" \
    -v "${OUTPUT_DIR}:/output:rw" \
    "${ISAAC_SIM_IMAGE}" \
    /scripts/${SCRIPT_NAME} "$@"

EXIT_CODE=$?

echo "[run_sim] ──────────────────────────────────────────"
echo "[run_sim] Container exited with code: ${EXIT_CODE}"

# ── Check for output files ────────────────────────────────────────────
if ls "${OUTPUT_DIR}"/* &>/dev/null 2>&1; then
    echo "[run_sim] Output files:"
    ls -la "${OUTPUT_DIR}/"
fi

exit ${EXIT_CODE}
