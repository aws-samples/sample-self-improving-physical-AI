"""
Unit tests for grip_reasoner.py.

Tests GripStrategyReasoner: prompt construction, response parsing,
rate limiting, and API failure graceful degradation.

Feature: xgo2-ball-grip-calibration, Task 5.4
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from unittest import mock

import numpy as np
import pytest

# Make modules importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordinate_mapper import BallPositionEstimate
from grip_reasoner import (
    DEFAULT_RATE_LIMIT_SECONDS,
    GripStrategyReasoner,
    _safe_int,
    _safe_str,
    _safe_str_list,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_frame():
    """A 320x240 BGR frame (typical camera resolution)."""
    return np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)


@pytest.fixture
def ball_position():
    """A sample BallPositionEstimate."""
    return BallPositionEstimate(depth=0.6, height=0.2, h_offset=-0.1)


@pytest.fixture
def arm_limits():
    """Standard arm workspace limits."""
    return {
        "arm_x_min": -80,
        "arm_x_max": 155,
        "arm_z_min": -95,
        "arm_z_max": 155,
    }


def _make_bedrock_response(strategy_dict):
    """Create a mock Bedrock API response containing the given strategy JSON."""
    response_body = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(strategy_dict),
            }
        ]
    }
    body_bytes = json.dumps(response_body).encode("utf-8")
    return {"body": io.BytesIO(body_bytes)}


def _make_reasoner_with_mock_client(rate_limit_seconds=DEFAULT_RATE_LIMIT_SECONDS):
    """Create a GripStrategyReasoner with a mocked boto3 client."""
    mock_boto3 = mock.MagicMock()
    mock_client = mock.MagicMock()
    mock_boto3.client.return_value = mock_client

    with mock.patch.dict("sys.modules", {"boto3": mock_boto3}):
        reasoner = GripStrategyReasoner(rate_limit_seconds=rate_limit_seconds)

    return reasoner, mock_client


# ---------------------------------------------------------------------------
# Test: Initialization
# ---------------------------------------------------------------------------


class TestGripStrategyReasonerInit:
    """Test GripStrategyReasoner initialization."""

    def test_init_with_boto3_available(self):
        """Should create a Bedrock client when boto3 is available."""
        mock_boto3 = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"boto3": mock_boto3}):
            reasoner = GripStrategyReasoner(region="us-west-2")

        assert reasoner._client is not None
        assert reasoner._region == "us-west-2"
        mock_boto3.client.assert_called_once_with(
            "bedrock-runtime", region_name="us-west-2"
        )

    def test_init_without_boto3(self):
        """Should set client to None when boto3 import fails."""
        with mock.patch.dict("sys.modules", {"boto3": None}):
            reasoner = GripStrategyReasoner()

        assert reasoner._client is None

    def test_init_with_boto3_client_error(self):
        """Should set client to None when boto3.client() raises."""
        mock_boto3 = mock.MagicMock()
        mock_boto3.client.side_effect = Exception("credential error")

        with mock.patch.dict("sys.modules", {"boto3": mock_boto3}):
            reasoner = GripStrategyReasoner()

        assert reasoner._client is None

    def test_init_custom_model_id(self):
        """Should accept a custom model ID."""
        mock_boto3 = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"boto3": mock_boto3}):
            reasoner = GripStrategyReasoner(
                model_id="anthropic.claude-3-sonnet-20240229-v1:0"
            )

        assert reasoner._model_id == "anthropic.claude-3-sonnet-20240229-v1:0"


# ---------------------------------------------------------------------------
# Test: Prompt construction
# ---------------------------------------------------------------------------


class TestBuildGripPrompt:
    """Test _build_grip_prompt constructs correct prompts."""

    def test_prompt_contains_ball_position(self, ball_position, arm_limits):
        """Prompt should include ball depth, height, and h_offset."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, arm_limits
        )

        assert "0.600" in prompt, "Prompt should contain ball depth"
        assert "0.200" in prompt, "Prompt should contain ball height"
        assert "-0.100" in prompt, "Prompt should contain ball h_offset"

    def test_prompt_contains_arm_limits(self, ball_position, arm_limits):
        """Prompt should include arm workspace bounds."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, arm_limits
        )

        assert "-80" in prompt, "Prompt should contain arm_x_min"
        assert "155" in prompt, "Prompt should contain arm_x_max"
        assert "-95" in prompt, "Prompt should contain arm_z_min"

    def test_prompt_requests_json_response(self, ball_position, arm_limits):
        """Prompt should ask for JSON output."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, arm_limits
        )

        assert "JSON" in prompt, "Prompt should request JSON format"

    def test_prompt_mentions_grip_strategy_fields(self, ball_position, arm_limits):
        """Prompt should mention expected response fields."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, arm_limits
        )

        assert "suggested_arm_x" in prompt
        assert "suggested_arm_z" in prompt
        assert "approach_direction" in prompt
        assert "warnings" in prompt

    def test_prompt_mentions_robot_context(self, ball_position, arm_limits):
        """Prompt should describe the robot and task."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, arm_limits
        )

        assert "XGO2" in prompt
        assert "red ball" in prompt
        assert "grip" in prompt.lower()

    def test_prompt_with_extreme_ball_position(self, arm_limits):
        """Prompt should handle extreme ball position values."""
        extreme_pos = BallPositionEstimate(depth=0.0, height=-1.0, h_offset=1.0)
        prompt = GripStrategyReasoner._build_grip_prompt(extreme_pos, arm_limits)

        assert "0.000" in prompt
        assert "-1.000" in prompt
        assert "1.000" in prompt

    def test_prompt_with_default_arm_limits(self, ball_position):
        """Prompt should use defaults when arm_limits keys are missing."""
        prompt = GripStrategyReasoner._build_grip_prompt(
            ball_position, {}
        )
        # Should fall back to defaults (-80, 155, -95, 155)
        assert "-80" in prompt
        assert "155" in prompt


# ---------------------------------------------------------------------------
# Test: Response parsing
# ---------------------------------------------------------------------------


class TestParseStrategyResponse:
    """Test _parse_strategy_response handles various response formats."""

    def test_parse_valid_json(self):
        """Should parse a well-formed JSON response."""
        raw = json.dumps({
            "suggested_arm_x": 50,
            "suggested_arm_z": 30,
            "approach_direction": "from_above",
            "warnings": ["ball is near edge"],
        })

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["suggested_arm_x"] == 50
        assert result["suggested_arm_z"] == 30
        assert result["approach_direction"] == "from_above"
        assert result["warnings"] == ["ball is near edge"]

    def test_parse_json_embedded_in_text(self):
        """Should extract JSON from surrounding text."""
        raw = 'Here is my analysis:\n{"suggested_arm_x": 10, "suggested_arm_z": -20, "approach_direction": "direct", "warnings": []}\nEnd.'

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["suggested_arm_x"] == 10
        assert result["suggested_arm_z"] == -20
        assert result["approach_direction"] == "direct"
        assert result["warnings"] == []

    def test_parse_missing_fields_uses_defaults(self):
        """Should use defaults for missing fields."""
        raw = json.dumps({"suggested_arm_x": 100})

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["suggested_arm_x"] == 100
        assert result["suggested_arm_z"] == 0  # default
        assert result["approach_direction"] == "direct"  # default
        assert result["warnings"] == []  # default

    def test_parse_invalid_json_returns_none(self):
        """Should return None for completely invalid text."""
        result = GripStrategyReasoner._parse_strategy_response(
            "I cannot provide a strategy."
        )
        assert result is None

    def test_parse_empty_string_returns_none(self):
        """Should return None for empty string."""
        result = GripStrategyReasoner._parse_strategy_response("")
        assert result is None

    def test_parse_non_dict_json_returns_none(self):
        """Should return None when JSON is a list, not a dict."""
        result = GripStrategyReasoner._parse_strategy_response("[1, 2, 3]")
        assert result is None

    def test_parse_preserves_raw_response(self):
        """Should include the raw response text in the result."""
        raw = json.dumps({"suggested_arm_x": 42})
        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["raw_response"] == raw

    def test_parse_non_integer_arm_values_uses_defaults(self):
        """Should use defaults when arm values are not valid integers."""
        raw = json.dumps({
            "suggested_arm_x": "not_a_number",
            "suggested_arm_z": None,
        })

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["suggested_arm_x"] == 0
        assert result["suggested_arm_z"] == 0

    def test_parse_float_arm_values_truncated_to_int(self):
        """Should truncate float arm values to int."""
        raw = json.dumps({
            "suggested_arm_x": 50.7,
            "suggested_arm_z": -30.2,
        })

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["suggested_arm_x"] == 50
        assert result["suggested_arm_z"] == -30

    def test_parse_non_string_approach_direction_uses_default(self):
        """Should use default when approach_direction is not a string."""
        raw = json.dumps({"approach_direction": 42})

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["approach_direction"] == "direct"

    def test_parse_warnings_non_list_returns_empty(self):
        """Should return empty list when warnings is not a list."""
        raw = json.dumps({"warnings": "single warning"})

        result = GripStrategyReasoner._parse_strategy_response(raw)

        assert result is not None
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Test: Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test rate limiting behavior (≤1 call per 10 seconds)."""

    def test_first_call_is_not_rate_limited(
        self, sample_frame, ball_position, arm_limits
    ):
        """First call should go through without rate limiting."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        strategy = {
            "suggested_arm_x": 50,
            "suggested_arm_z": 30,
            "approach_direction": "direct",
            "warnings": [],
        }
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is not None
        assert result["suggested_arm_x"] == 50
        mock_client.invoke_model.assert_called_once()

    def test_second_call_within_limit_is_rate_limited(
        self, sample_frame, ball_position, arm_limits
    ):
        """Second call within rate limit window should return None."""
        reasoner, mock_client = _make_reasoner_with_mock_client(
            rate_limit_seconds=10.0
        )

        strategy = {
            "suggested_arm_x": 50,
            "suggested_arm_z": 30,
            "approach_direction": "direct",
            "warnings": [],
        }
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # First call succeeds
            result1 = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )
            assert result1 is not None

            # Second call immediately after should be rate-limited
            result2 = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )
            assert result2 is None

        # Only one actual API call should have been made
        assert mock_client.invoke_model.call_count == 1

    def test_call_after_rate_limit_expires_succeeds(
        self, sample_frame, ball_position, arm_limits
    ):
        """Call after rate limit window should succeed."""
        reasoner, mock_client = _make_reasoner_with_mock_client(
            rate_limit_seconds=0.1  # Very short for testing
        )

        strategy = {
            "suggested_arm_x": 50,
            "suggested_arm_z": 30,
            "approach_direction": "direct",
            "warnings": [],
        }

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # First call
            mock_client.invoke_model.return_value = _make_bedrock_response(strategy)
            result1 = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )
            assert result1 is not None

            # Wait for rate limit to expire
            time.sleep(0.15)

            # Second call should succeed
            mock_client.invoke_model.return_value = _make_bedrock_response(strategy)
            result2 = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )
            assert result2 is not None

        assert mock_client.invoke_model.call_count == 2

    def test_rate_limit_not_updated_on_rate_limited_call(
        self, sample_frame, ball_position, arm_limits
    ):
        """Rate-limited calls should not reset the rate limit timer."""
        reasoner, mock_client = _make_reasoner_with_mock_client(
            rate_limit_seconds=10.0
        )

        strategy = {"suggested_arm_x": 50}
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # First call succeeds
            reasoner.get_grip_strategy(sample_frame, ball_position, arm_limits)
            first_call_time = reasoner._last_call_time

            # Rate-limited call should not update _last_call_time
            reasoner.get_grip_strategy(sample_frame, ball_position, arm_limits)
            assert reasoner._last_call_time == first_call_time


# ---------------------------------------------------------------------------
# Test: API failure graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulFailure:
    """Test that API failures return None without raising."""

    def test_returns_none_when_client_is_none(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should return None when Bedrock client is not available."""
        with mock.patch.dict("sys.modules", {"boto3": None}):
            reasoner = GripStrategyReasoner()

        result = reasoner.get_grip_strategy(
            sample_frame, ball_position, arm_limits
        )
        assert result is None

    def test_returns_none_on_invoke_model_exception(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should return None when invoke_model raises an exception."""
        reasoner, mock_client = _make_reasoner_with_mock_client()
        mock_client.invoke_model.side_effect = Exception("throttling")

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is None

    def test_returns_none_on_frame_encode_failure(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should return None when frame encoding fails."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (False, None)

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is None
        mock_client.invoke_model.assert_not_called()

    def test_returns_none_on_empty_bedrock_response(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should return None when Bedrock returns empty content."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        empty_response = {"content": []}
        body_bytes = json.dumps(empty_response).encode("utf-8")
        mock_client.invoke_model.return_value = {"body": io.BytesIO(body_bytes)}

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is None

    def test_returns_none_on_unparseable_response(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should return None when Bedrock returns non-JSON text."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        text_response = {
            "content": [{"type": "text", "text": "I cannot help with that."}]
        }
        body_bytes = json.dumps(text_response).encode("utf-8")
        mock_client.invoke_model.return_value = {"body": io.BytesIO(body_bytes)}

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is None

    def test_does_not_raise_on_any_failure(
        self, sample_frame, ball_position, arm_limits
    ):
        """get_grip_strategy should never raise, regardless of failure mode."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        # Simulate a response body that raises on read()
        mock_body = mock.MagicMock()
        mock_body.read.side_effect = IOError("connection reset")
        mock_client.invoke_model.return_value = {"body": mock_body}

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # Should not raise
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is None

    def test_rate_limit_not_updated_on_api_failure(
        self, sample_frame, ball_position, arm_limits
    ):
        """Failed API calls should not update the rate limit timer."""
        reasoner, mock_client = _make_reasoner_with_mock_client()
        mock_client.invoke_model.side_effect = Exception("network error")

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            reasoner.get_grip_strategy(sample_frame, ball_position, arm_limits)

        # _last_call_time should still be 0.0 (initial value)
        assert reasoner._last_call_time == 0.0


# ---------------------------------------------------------------------------
# Test: End-to-end get_grip_strategy flow
# ---------------------------------------------------------------------------


class TestGetGripStrategyFlow:
    """Test the full get_grip_strategy flow with mocked Bedrock."""

    def test_successful_strategy_request(
        self, sample_frame, ball_position, arm_limits
    ):
        """Full flow: encode frame, build prompt, call Bedrock, parse response."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        strategy = {
            "suggested_arm_x": 80,
            "suggested_arm_z": -10,
            "approach_direction": "from_above",
            "warnings": ["ball is partially occluded"],
        }
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = reasoner.get_grip_strategy(
                sample_frame, ball_position, arm_limits
            )

        assert result is not None
        assert result["suggested_arm_x"] == 80
        assert result["suggested_arm_z"] == -10
        assert result["approach_direction"] == "from_above"
        assert result["warnings"] == ["ball is partially occluded"]

    def test_invoke_model_called_with_correct_model_id(
        self, sample_frame, ball_position, arm_limits
    ):
        """Should call invoke_model with the configured model ID."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        strategy = {"suggested_arm_x": 0}
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            reasoner.get_grip_strategy(sample_frame, ball_position, arm_limits)

        call_kwargs = mock_client.invoke_model.call_args
        assert call_kwargs[1]["modelId"] == "anthropic.claude-3-haiku-20240307-v1:0"
        assert call_kwargs[1]["contentType"] == "application/json"

    def test_request_body_contains_image_and_prompt(
        self, sample_frame, ball_position, arm_limits
    ):
        """Request body should contain both the image and the grip prompt."""
        reasoner, mock_client = _make_reasoner_with_mock_client()

        strategy = {"suggested_arm_x": 0}
        mock_client.invoke_model.return_value = _make_bedrock_response(strategy)

        mock_cv2 = mock.MagicMock()
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            reasoner.get_grip_strategy(sample_frame, ball_position, arm_limits)

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs[1]["body"])

        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert body["max_tokens"] == 300

        messages = body["messages"]
        assert len(messages) == 1
        content = messages[0]["content"]
        assert len(content) == 2

        # First content block is the image
        assert content[0]["type"] == "image"
        assert content[0]["source"]["media_type"] == "image/jpeg"

        # Second content block is the text prompt
        assert content[1]["type"] == "text"
        assert "red ball" in content[1]["text"]
        assert "0.600" in content[1]["text"]  # ball depth


# ---------------------------------------------------------------------------
# Test: Utility helpers
# ---------------------------------------------------------------------------


class TestSafeHelpers:
    """Test _safe_int, _safe_str, _safe_str_list utility functions."""

    def test_safe_int_with_valid_int(self):
        assert _safe_int(42, 0) == 42

    def test_safe_int_with_valid_float(self):
        assert _safe_int(3.7, 0) == 3

    def test_safe_int_with_none(self):
        assert _safe_int(None, -1) == -1

    def test_safe_int_with_invalid_string(self):
        assert _safe_int("abc", 5) == 5

    def test_safe_str_with_valid_string(self):
        assert _safe_str("hello", "default") == "hello"

    def test_safe_str_with_none(self):
        assert _safe_str(None, "default") == "default"

    def test_safe_str_with_non_string(self):
        assert _safe_str(42, "default") == "default"

    def test_safe_str_list_with_valid_list(self):
        assert _safe_str_list(["a", "b"]) == ["a", "b"]

    def test_safe_str_list_with_none(self):
        assert _safe_str_list(None) == []

    def test_safe_str_list_with_non_list(self):
        assert _safe_str_list("not a list") == []

    def test_safe_str_list_converts_items_to_str(self):
        assert _safe_str_list([1, 2.5, True]) == ["1", "2.5", "True"]
