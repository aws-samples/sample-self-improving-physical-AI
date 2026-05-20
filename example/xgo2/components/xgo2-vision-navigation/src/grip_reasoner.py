"""
Grip strategy reasoner for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Sends camera frames with ball detection context to Amazon Bedrock
(Claude 3 Haiku) for high-level grip strategy reasoning. Uses TES
credentials provided by the Greengrass Token Exchange Service.

Rate-limited to at most one Bedrock call per 10 seconds.
Graceful failure: logs errors and returns None so the servoing loop
is never interrupted.

Requirements: 8.1-8.6
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

from coordinate_mapper import BallPositionEstimate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
DEFAULT_RATE_LIMIT_SECONDS = 10.0
MAX_TOKENS = 300


class GripStrategyReasoner:
    """Cloud-side grip strategy analysis via Amazon Bedrock (Claude 3 Haiku).

    Sends camera frames with ball position and arm workspace context to
    Bedrock for high-level grip strategy decisions. Rate-limited to avoid
    excessive API calls and throttling.

    The caller (grip_controller) uses the returned strategy hints to
    adjust initial arm position and approach direction.

    Args:
        region: AWS region for the Bedrock Runtime endpoint.
        model_id: Bedrock model identifier (default: Claude 3 Haiku).
        rate_limit_seconds: Minimum interval between API calls.
    """

    def __init__(
        self,
        region=DEFAULT_REGION,              # type: str
        model_id=DEFAULT_MODEL_ID,          # type: str
        rate_limit_seconds=DEFAULT_RATE_LIMIT_SECONDS,  # type: float
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
                "Grip reasoner Bedrock client initialized: region=%s, model=%s",
                self._region,
                self._model_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to create Bedrock client for grip reasoner: %s. "
                "Grip strategy reasoning will be disabled.",
                exc,
            )
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_grip_strategy(
        self,
        frame,           # type: np.ndarray
        ball_position,   # type: BallPositionEstimate
        arm_limits,      # type: Dict[str, Any]
    ):
        # type: (...) -> Optional[Dict[str, Any]]
        """Request a grip strategy assessment from Bedrock.

        Sends the camera frame with ball position context and arm workspace
        limits to Claude 3 Haiku. Parses the response for actionable
        parameters: suggested initial arm position, approach direction,
        and warnings.

        Returns None if the call is rate-limited, the client is unavailable,
        or an error occurs. Never raises — the servoing loop must not be
        interrupted.

        Args:
            frame: BGR numpy array from OpenCV (320x240).
            ball_position: Estimated ball position in camera-frame coords.
            arm_limits: Dict with arm workspace bounds, e.g.
                {"arm_x_min": -80, "arm_x_max": 155,
                 "arm_z_min": -95, "arm_z_max": 155}.

        Returns:
            Dict with parsed strategy parameters, or None.
        """
        if self._client is None:
            return None

        # --- Rate limit check (Req 8.4) ---
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < self._rate_limit_seconds:
            logger.debug(
                "Grip reasoner rate-limited: %.1fs since last call (limit %.1fs)",
                elapsed,
                self._rate_limit_seconds,
            )
            return None

        # --- Encode frame ---
        try:
            image_b64 = self._encode_frame(frame)
        except Exception:
            logger.warning("Failed to encode frame for grip reasoner")
            return None

        # --- Build grip-specific prompt (Req 8.2) ---
        prompt = self._build_grip_prompt(ball_position, arm_limits)

        # --- Build Bedrock request body ---
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
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

        # --- Call Bedrock (Req 8.1, 8.6) ---
        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            # Update rate limit timestamp on successful call
            self._last_call_time = time.monotonic()

            # --- Parse response (Req 8.3) ---
            response_body = json.loads(response["body"].read())
            content_blocks = response_body.get("content", [])
            text_parts = []  # type: List[str]
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            raw_text = " ".join(text_parts).strip()
            if not raw_text:
                logger.warning("Grip reasoner: Bedrock returned empty response")
                return None

            logger.info(
                "Grip strategy response received (%d chars)", len(raw_text)
            )

            return self._parse_strategy_response(raw_text)

        except Exception as exc:
            # Graceful failure (Req 8.5): log and return None
            logger.warning("Grip reasoner Bedrock API call failed: %s", exc)
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
    def _build_grip_prompt(ball_position, arm_limits):
        # type: (BallPositionEstimate, Dict[str, Any]) -> str
        """Build a grip-specific prompt with ball position and arm limits.

        Args:
            ball_position: Estimated ball position in camera-frame coords.
            arm_limits: Dict with arm workspace bounds.

        Returns:
            Prompt string for the Bedrock model.
        """
        lines = [
            "You are an AI assistant on a small quadruped robot (XGO2) "
            "equipped with a front-mounted arm and claw gripper.",
            "The robot is attempting to grip a red ball detected in the camera image.",
            "",
            "Ball position (camera-frame estimates):",
            "- Depth (0=far, 1=close): %.3f" % ball_position.depth,
            "- Height (-1=top, 1=bottom): %.3f" % ball_position.height,
            "- Horizontal offset (-1=left, 1=right): %.3f" % ball_position.h_offset,
            "",
            "Arm workspace limits:",
            "- arm_x range: %d (back) to %d (forward)" % (
                arm_limits.get("arm_x_min", -80),
                arm_limits.get("arm_x_max", 155),
            ),
            "- arm_z range: %d (down) to %d (up)" % (
                arm_limits.get("arm_z_min", -95),
                arm_limits.get("arm_z_max", 155),
            ),
            "",
            "Analyze the scene and provide a grip strategy as JSON with these fields:",
            '- "suggested_arm_x": integer, suggested initial arm x position',
            '- "suggested_arm_z": integer, suggested initial arm z position',
            '- "approach_direction": one of "direct", "from_above", "from_below", "from_left", "from_right"',
            '- "warnings": list of strings with any concerns about the scene',
            "",
            "Respond ONLY with the JSON object, no other text.",
        ]

        return "\n".join(lines)

    @staticmethod
    def _parse_strategy_response(raw_text):
        # type: (str) -> Optional[Dict[str, Any]]
        """Parse the Bedrock response text into a strategy dict.

        Attempts to extract a JSON object from the response. Falls back
        to a default strategy if parsing fails.

        Args:
            raw_text: Raw text response from Bedrock.

        Returns:
            Dict with keys: suggested_arm_x, suggested_arm_z,
            approach_direction, warnings. Or None if parsing fails entirely.
        """
        # Try to extract JSON from the response
        try:
            # Try direct JSON parse first
            strategy = json.loads(raw_text)
        except (ValueError, TypeError):
            # Try to find JSON object in the text
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    strategy = json.loads(raw_text[start:end + 1])
                except (ValueError, TypeError):
                    logger.warning(
                        "Grip reasoner: failed to parse JSON from response"
                    )
                    return None
            else:
                logger.warning(
                    "Grip reasoner: no JSON object found in response"
                )
                return None

        if not isinstance(strategy, dict):
            logger.warning("Grip reasoner: response is not a JSON object")
            return None

        # Validate and extract expected fields with defaults
        result = {
            "suggested_arm_x": _safe_int(strategy.get("suggested_arm_x"), 0),
            "suggested_arm_z": _safe_int(strategy.get("suggested_arm_z"), 0),
            "approach_direction": _safe_str(
                strategy.get("approach_direction"), "direct"
            ),
            "warnings": _safe_str_list(strategy.get("warnings")),
            "raw_response": raw_text,
        }

        return result


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_int(value, default):
    # type: (Any, int) -> int
    """Safely convert a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value, default):
    # type: (Any, str) -> str
    """Safely convert a value to str, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return default


def _safe_str_list(value):
    # type: (Any) -> List[str]
    """Safely convert a value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
