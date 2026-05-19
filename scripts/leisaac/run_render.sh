#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: ShellCheck v0.10.0 + Semgrep OSS
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

# Render static images from the LeIsaac Kitchen Orange Picking scene
# Captures 4 viewpoints: front, closeup, top-down, side

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSET_DIR="${ASSET_DIR:-/tmp/leisaac_assets}"
OUTPUT_DIR="${OUTPUT_DIR:-$(pwd)/output}"
CACHE_DIR="${CACHE_DIR:-$HOME/docker/isaac-sim}"
IMAGE="nvcr.io/nvidia/isaac-sim:6.0.0-dev2"
CONTAINER_NAME="kitchen-render"
WARMUP_STEPS="${WARMUP_STEPS:-300}"

# Check assets
if [ ! -f "$ASSET_DIR/kitchen_with_orange/scene.usd" ]; then
    echo "Error: Kitchen scene not found. Run download_assets.sh first."
    exit 1
fi

mkdir -p "$OUTPUT_DIR" "$CACHE_DIR/cache/main" "$CACHE_DIR/cache/computecache" \
         "$CACHE_DIR/logs" "$CACHE_DIR/config" "$CACHE_DIR/data"

# Stop existing
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "Rendering LeIsaac Kitchen scene (warm-up: $WARMUP_STEPS steps)..."
echo "Output: $OUTPUT_DIR"

docker run --name "$CONTAINER_NAME" \
  --gpus all \
  -e "ACCEPT_EULA=Y" -e "PRIVACY_CONSENT=Y" -e "OMNI_KIT_ACCEPT_EULA=YES" \
  -v "$CACHE_DIR/cache/main:/isaac-sim/.cache:rw" \
  -v "$CACHE_DIR/cache/computecache:/isaac-sim/.nv/ComputeCache:rw" \
  -v "$CACHE_DIR/logs:/isaac-sim/.nvidia-omniverse/logs:rw" \
  -v "$CACHE_DIR/config:/isaac-sim/.nvidia-omniverse/config:rw" \
  -v "$CACHE_DIR/data:/isaac-sim/.local/share/ov/data:rw" \
  -v "$ASSET_DIR:/scene_data/scenes:ro" \
  -v "$ASSET_DIR/so101_follower.usd:/scene_data/robot.usd:ro" \
  -v "$SCRIPT_DIR/render_kitchen.py:/isaac-sim/render.py:ro" \
  -v "$OUTPUT_DIR:/output:rw" \
  --entrypoint ./python.sh \
  "$IMAGE" \
  /isaac-sim/render.py --warmup "$WARMUP_STEPS"

echo ""
echo "Render complete. Output:"
ls -lh "$OUTPUT_DIR"/kitchen_*.png 2>/dev/null || echo "No output files found"
