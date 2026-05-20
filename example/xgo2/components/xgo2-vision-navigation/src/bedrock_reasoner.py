"""
Bedrock hybrid reasoning for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Sends camera frames to Amazon Bedrock (Claude 3 Haiku) for scene description
and suggested actions. Uses TES credentials provided by Greengrass Token
Exchange Service.

Requirements: 6.1-6.7
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class BedrockReasoner:
    """Cloud-side scene analysis via Amazon Bedrock (Claude 3 Haiku).

    Sends camera frames with detection context to Bedrock for rich scene
    descriptions and suggested robot actions. Rate-limited to avoid
    excessive API calls and throttling.

    The caller (nav_controller) is responsible for publishing the Bedrock
    response to the ``xgo-robodog/vision/bedrock`` MQTT topic.

    Args:
        region: AWS region for the Bedrock Runtime endpoint.
        model_id: Bedrock model identifier (default: Claude 3 Haiku).
        rate_limit_seconds: Minimum interval between API calls.
    """

    def __init__(
        self,
        region="us-east-1",       # type: str
        model_id="anthropic.claude-3-haiku-20240307-v1:0",  # type: str
        rate_limit_seconds=5.0,   # type: float
    ):
        # type: (...) -> None
        self._region = region
        self._model_id = model_id
        self._rate_limit_seconds = rate_limit_seconds
        self._last_call_time = 0.0  # type: float
        self._client = None  # type: Any

        # Create Bedrock Runtime client using TES credentials.
        # On a Greengrass device the default credential chain picks up
        # the Token Exchange Service credentials automatically.
        try:
            import boto3  # type: ignore[import-untyped]

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
            )
            logger.info(
                "Bedrock client initialized: region=%s, model=%s",
                self._region,
                self._model_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to create Bedrock client: %s. "
                "Scene analysis will be disabled.",
                exc,
            )
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_scene(
        self,
        frame,        # type: np.ndarray
        detections,   # type: List[Any]
    ):
        # type: (...) -> Optional[str]
        """Send a camera frame and detection context to Bedrock for analysis.

        Returns the response text from Claude, or ``None`` if the call is
        rate-limited, the client is unavailable, or an error occurs.

        Args:
            frame: BGR numpy array from OpenCV.
            detections: List of DetectionResult objects (or dicts with
                ``class_label``, ``confidence``, ``bounding_box``).

        Returns:
            Scene description string, or None.
        """
        if self._client is None:
            return None

        # --- Rate limit check (Req 6.5) ---
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < self._rate_limit_seconds:
            logger.debug(
                "Bedrock rate-limited: %.1fs since last call (limit %.1fs)",
                elapsed,
                self._rate_limit_seconds,
            )
            return None

        # --- Encode frame ---
        try:
            image_b64 = self._encode_frame(frame)
        except Exception:
            logger.warning("Failed to encode frame for Bedrock")
            return None

        # --- Build prompt with detection context ---
        prompt = self._build_prompt(detections)

        # --- Build Bedrock request body ---
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        # --- Call Bedrock (Req 6.1, 6.3) ---
        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            # Update rate limit timestamp on successful call
            self._last_call_time = time.monotonic()

            # --- Parse response ---
            response_body = json.loads(response["body"].read())
            content_blocks = response_body.get("content", [])
            text_parts = []  # type: List[str]
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            result = " ".join(text_parts).strip()
            if result:
                logger.info(
                    "Bedrock scene analysis received (%d chars)",
                    len(result),
                )
                return result

            logger.warning("Bedrock returned empty response")
            return None

        except Exception as exc:
            # Handle timeout, throttling, and all other API errors
            # gracefully so navigation continues (Req 6.6)
            logger.warning("Bedrock API call failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _encode_frame(self, frame):
        # type: (np.ndarray) -> str
        """Encode a numpy array frame as a base64 JPEG string.

        Args:
            frame: BGR numpy array from OpenCV.

        Returns:
            Base64-encoded JPEG string.

        Raises:
            RuntimeError: If JPEG encoding fails.
        """
        import cv2  # type: ignore[import-untyped]

        success, buffer = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("Failed to encode frame as JPEG")

        return base64.b64encode(buffer.tobytes()).decode("utf-8")

    @staticmethod
    def _build_prompt(detections):
        # type: (List[Any]) -> str
        """Build a text prompt describing the current detections.

        Args:
            detections: List of DetectionResult objects or dicts.

        Returns:
            Prompt string for the Bedrock model.
        """
        lines = [
            "You are an AI assistant on a small quadruped robot (XGO2). "
            "Analyze the camera image and provide:",
            "1. A brief description of the scene (1-2 sentences).",
            "2. Objects you can identify and their approximate positions.",
            "3. Suggested actions for the robot (e.g., move forward, "
            "turn left, avoid obstacle).",
            "",
        ]

        if detections:
            lines.append(
                "The robot's local object detector found the following:"
            )
            for det in detections:
                # Support both DetectionResult objects and plain dicts
                if hasattr(det, "class_label"):
                    label = det.class_label
                    conf = det.confidence
                else:
                    label = det.get("class_label", "unknown")
                    conf = det.get("confidence", 0.0)
                lines.append(
                    "- {label} (confidence: {conf:.0%})".format(
                        label=label, conf=conf
                    )
                )
            lines.append("")

        lines.append(
            "Keep your response concise (under 100 words). "
            "Focus on actionable information for navigation."
        )

        return "\n".join(lines)
