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

# Run LeIsaac Kitchen Orange Picking scene in Isaac Sim streaming mode
# Prerequisites: Docker, NVIDIA GPU, assets downloaded (run download_assets.sh first)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSET_DIR="${ASSET_DIR:-/tmp/leisaac_assets}"
CACHE_DIR="${CACHE_DIR:-$HOME/docker/isaac-sim}"
IMAGE="nvcr.io/nvidia/isaac-sim:6.0.0-dev2"
CONTAINER_NAME="isaac-sim-kitchen"

# Validate environment variable paths (prevent directory traversal)
if [[ "$ASSET_DIR" == *".."* ]] || [[ ! "$ASSET_DIR" =~ ^/ ]]; then
    echo "ERROR: ASSET_DIR must be an absolute path without '..' components"
    exit 1
fi
if [[ "$CACHE_DIR" == *".."* ]] || [[ ! "$CACHE_DIR" =~ ^/ ]]; then
    echo "ERROR: CACHE_DIR must be an absolute path without '..' components"
    exit 1
fi

# Check assets exist
if [ ! -f "$ASSET_DIR/kitchen_with_orange/scene.usd" ]; then
    echo "Error: Kitchen scene not found. Run download_assets.sh first."
    echo "  bash $SCRIPT_DIR/download_assets.sh $ASSET_DIR"
    exit 1
fi

if [ ! -f "$ASSET_DIR/so101_follower.usd" ]; then
    echo "Error: SO-101 robot USD not found. Run download_assets.sh first."
    exit 1
fi

# Create cache directories
mkdir -p "$CACHE_DIR/cache/main" "$CACHE_DIR/cache/computecache" \
         "$CACHE_DIR/logs" "$CACHE_DIR/config" "$CACHE_DIR/data"

# Stop existing container
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "Starting Isaac Sim with LeIsaac Kitchen scene..."
echo "  Image: $IMAGE"
echo "  Assets: $ASSET_DIR"
echo "  Mode: WebRTC streaming (connect via Streaming Client -> localhost)"
echo ""
echo "  Security: --network=host required for WebRTC signaling (port 49100)"
echo "            Compensating control: Security Group restricts inbound to operator CIDR"


docker run -d --name "$CONTAINER_NAME" \
  --gpus all \
  -e "ACCEPT_EULA=Y" -e "PRIVACY_CONSENT=Y" \
  --network=host \
  --security-opt=no-new-privileges:true \
  --cap-drop=ALL \
  --cap-add=SYS_ADMIN \
  -v "$CACHE_DIR/cache/main:/isaac-sim/.cache:rw" \
  -v "$CACHE_DIR/cache/computecache:/isaac-sim/.nv/ComputeCache:rw" \
  -v "$CACHE_DIR/logs:/isaac-sim/.nvidia-omniverse/logs:rw" \
  -v "$CACHE_DIR/config:/isaac-sim/.nvidia-omniverse/config:rw" \
  -v "$CACHE_DIR/data:/isaac-sim/.local/share/ov/data:rw" \
  -v "$ASSET_DIR:/scene_data/scenes:ro" \
  -v "$ASSET_DIR/so101_follower.usd:/scene_data/robot.usd:ro" \
  -v "$SCRIPT_DIR/load_kitchen_scene.py:/isaac-sim/load_kitchen.py:ro" \
  --restart unless-stopped \
  "$IMAGE" \
  ./runheadless.sh \
  --/app/renderer/resolution/width=1280 \
  --/app/renderer/resolution/height=720 \
  --/exts/omni.kit.livestream.webrtc/maxBitrate=5000000 \
  --/exts/omni.kit.livestream.webrtc/maxFps=30 \
  --exec "/isaac-sim/load_kitchen.py"

echo ""
echo "Container '$CONTAINER_NAME' started."
echo "Wait ~60s for scene to load, then connect with:"
echo "  NVIDIA Streaming Client -> localhost"
echo ""
echo "Monitor progress:"
echo "  docker logs -f $CONTAINER_NAME 2>&1 | grep '[startup]'"
