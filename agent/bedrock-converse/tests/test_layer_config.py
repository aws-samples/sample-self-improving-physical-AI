"""Unit tests for layer_config.py."""

from unittest.mock import patch

import pytest

from layer_config import (
    LayerModelConfig,
    AgentLayerConfigs,
    load_layer_configs,
    _parse_float,
    _parse_int,
)


class TestParseHelpers:
    """Tests for _parse_float and _parse_int helper functions."""

    def test_parse_float_none_returns_default(self):
        assert _parse_float(None, 0.7) == 0.7

    def test_parse_float_valid_string(self):
        assert _parse_float("0.5", 0.7) == 0.5

    def test_parse_float_invalid_string_returns_default(self):
        assert _parse_float("not_a_number", 0.7) == 0.7

    def test_parse_float_empty_string_returns_default(self):
        assert _parse_float("", 0.7) == 0.7

    def test_parse_int_none_returns_default(self):
        assert _parse_int(None, 1024) == 1024

    def test_parse_int_valid_string(self):
        assert _parse_int("2048", 1024) == 2048

    def test_parse_int_invalid_string_returns_default(self):
        assert _parse_int("abc", 1024) == 1024

    def test_parse_int_empty_string_returns_default(self):
        assert _parse_int("", 1024) == 1024


class TestLayerModelConfig:
    """Tests for the LayerModelConfig frozen dataclass."""

    def test_frozen_dataclass(self):
        cfg = LayerModelConfig(
            model_id="test-model",
            region_name="us-east-1",
            temperature=0.5,
            max_tokens=1024,
        )
        with pytest.raises(AttributeError):
            cfg.model_id = "other-model"

    def test_fields_stored_correctly(self):
        cfg = LayerModelConfig(
            model_id="my-model",
            region_name="us-west-2",
            temperature=0.3,
            max_tokens=512,
        )
        assert cfg.model_id == "my-model"
        assert cfg.region_name == "us-west-2"
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 512


class TestAgentLayerConfigs:
    """Tests for the AgentLayerConfigs frozen dataclass."""

    def test_frozen_dataclass(self):
        cfg = LayerModelConfig("m", "r", 0.0, 100)
        configs = AgentLayerConfigs(
            perception=cfg, reasoning=cfg, act=cfg, governance=cfg
        )
        with pytest.raises(AttributeError):
            configs.perception = cfg

    def test_all_four_layers_accessible(self):
        p = LayerModelConfig("p-model", "us-east-1", 0.0, 1024)
        r = LayerModelConfig("r-model", "us-east-1", 0.7, 4096)
        a = LayerModelConfig("a-model", "us-east-1", 0.0, 512)
        g = LayerModelConfig("g-model", "us-east-1", 0.3, 1024)
        configs = AgentLayerConfigs(perception=p, reasoning=r, act=a, governance=g)
        assert configs.perception.model_id == "p-model"
        assert configs.reasoning.model_id == "r-model"
        assert configs.act.model_id == "a-model"
        assert configs.governance.model_id == "g-model"


class TestLoadLayerConfigs:
    """Tests for load_layer_configs() with default and custom env vars."""

    def _mock_config(self, overrides=None):
        """Return a dict of config module attributes with defaults, applying overrides."""
        defaults = {
            "BEDROCK_REGION": "us-east-1",
            "PERCEPTION_MODEL_ID": None,
            "PERCEPTION_TEMPERATURE": None,
            "PERCEPTION_MAX_TOKENS": None,
            "REASONING_MODEL_ID": None,
            "REASONING_TEMPERATURE": None,
            "REASONING_MAX_TOKENS": None,
            "ACT_MODEL_ID": None,
            "ACT_TEMPERATURE": None,
            "ACT_MAX_TOKENS": None,
            "GOVERNANCE_MODEL_ID": None,
            "GOVERNANCE_TEMPERATURE": None,
            "GOVERNANCE_MAX_TOKENS": None,
        }
        if overrides:
            defaults.update(overrides)
        return defaults

    def _load_with_config(self, overrides=None):
        """Call load_layer_configs with patched config module attributes."""
        attrs = self._mock_config(overrides)
        with patch.multiple("layer_config", **attrs):
            return load_layer_configs()

    def test_defaults_when_no_env_vars(self):
        """All defaults should be applied when no layer env vars are set."""
        configs = self._load_with_config()

        # Perception defaults
        assert configs.perception.model_id == "us.anthropic.claude-opus-4-1-20250805-v1:0"
        assert configs.perception.temperature == 0.0
        assert configs.perception.max_tokens == 1024

        # Reasoning defaults
        assert configs.reasoning.model_id == "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert configs.reasoning.temperature == 0.7
        assert configs.reasoning.max_tokens == 4096

        # Act defaults
        assert configs.act.model_id == "us.amazon.nova-micro-v1:0"
        assert configs.act.temperature == 0.0
        assert configs.act.max_tokens == 512

        # Governance defaults
        assert configs.governance.model_id == "global.amazon.nova-2-lite-v1:0"
        assert configs.governance.temperature == 0.3
        assert configs.governance.max_tokens == 1024

    def test_custom_env_vars_override_defaults(self):
        """Custom env vars should override the defaults."""
        configs = self._load_with_config({
            "PERCEPTION_MODEL_ID": "custom-perception-model",
            "PERCEPTION_TEMPERATURE": "0.5",
            "PERCEPTION_MAX_TOKENS": "2048",
            "REASONING_MODEL_ID": "custom-reasoning-model",
            "BEDROCK_REGION": "eu-west-1",
        })

        assert configs.perception.model_id == "custom-perception-model"
        assert configs.perception.temperature == 0.5
        assert configs.perception.max_tokens == 2048
        assert configs.reasoning.model_id == "custom-reasoning-model"
        # All layers share the region
        assert configs.perception.region_name == "eu-west-1"
        assert configs.reasoning.region_name == "eu-west-1"
        assert configs.act.region_name == "eu-west-1"
        assert configs.governance.region_name == "eu-west-1"

    def test_invalid_temperature_falls_back_to_default(self):
        """Invalid temperature string should fall back to default."""
        configs = self._load_with_config({"ACT_TEMPERATURE": "not_a_float"})
        assert configs.act.temperature == 0.0

    def test_invalid_max_tokens_falls_back_to_default(self):
        """Invalid max_tokens string should fall back to default."""
        configs = self._load_with_config({"GOVERNANCE_MAX_TOKENS": "xyz"})
        assert configs.governance.max_tokens == 1024

    def test_all_layers_have_non_empty_model_id(self):
        """Every layer must have a non-empty model_id."""
        configs = self._load_with_config()
        assert configs.perception.model_id
        assert configs.reasoning.model_id
        assert configs.act.model_id
        assert configs.governance.model_id

    def test_shared_region_applied_to_all_layers(self):
        """BEDROCK_REGION should be applied to all four layers."""
        configs = self._load_with_config({"BEDROCK_REGION": "ap-southeast-1"})
        assert configs.perception.region_name == "ap-southeast-1"
        assert configs.reasoning.region_name == "ap-southeast-1"
        assert configs.act.region_name == "ap-southeast-1"
        assert configs.governance.region_name == "ap-southeast-1"
