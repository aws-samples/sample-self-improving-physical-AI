"""Per-layer model configuration for the agentic layered architecture.

Each agent layer (Perception, Reasoning, Act, Governance) has its own
model, temperature, and token limit. Configuration is loaded from
environment variables with sensible defaults, allowing model swaps
without code changes.
"""

from dataclasses import dataclass

from strands.models.bedrock import BedrockModel

from config import (
    BEDROCK_REGION,
    PERCEPTION_MODEL_ID,
    PERCEPTION_TEMPERATURE,
    PERCEPTION_MAX_TOKENS,
    REASONING_MODEL_ID,
    REASONING_TEMPERATURE,
    REASONING_MAX_TOKENS,
    ACT_MODEL_ID,
    ACT_TEMPERATURE,
    ACT_MAX_TOKENS,
    GOVERNANCE_MODEL_ID,
    GOVERNANCE_TEMPERATURE,
    GOVERNANCE_MAX_TOKENS,
)

# Default model IDs per layer
_DEFAULT_PERCEPTION_MODEL = "us.anthropic.claude-opus-4-1-20250805-v1:0"
_DEFAULT_REASONING_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
_DEFAULT_ACT_MODEL = "us.amazon.nova-micro-v1:0"
_DEFAULT_GOVERNANCE_MODEL = "global.amazon.nova-2-lite-v1:0"

# Default temperatures per layer
_DEFAULT_PERCEPTION_TEMPERATURE = 0.0
_DEFAULT_REASONING_TEMPERATURE = 0.7
_DEFAULT_ACT_TEMPERATURE = 0.0
_DEFAULT_GOVERNANCE_TEMPERATURE = 0.3

# Default max tokens per layer
_DEFAULT_PERCEPTION_MAX_TOKENS = 1024
_DEFAULT_REASONING_MAX_TOKENS = 4096
_DEFAULT_ACT_MAX_TOKENS = 512
_DEFAULT_GOVERNANCE_MAX_TOKENS = 1024


def _parse_float(value: str | None, default: float) -> float:
    """Parse a string to float, returning default if None or invalid."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_int(value: str | None, default: int) -> int:
    """Parse a string to int, returning default if None or invalid."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class LayerModelConfig:
    """Configuration for a single agent layer's model."""

    model_id: str
    region_name: str
    temperature: float
    max_tokens: int

    def to_bedrock_model(self) -> BedrockModel:
        """Create a Strands BedrockModel from this config."""
        return BedrockModel(
            model_id=self.model_id,
            region_name=self.region_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


@dataclass(frozen=True)
class AgentLayerConfigs:
    """All four layer configurations."""

    perception: LayerModelConfig
    reasoning: LayerModelConfig
    act: LayerModelConfig
    governance: LayerModelConfig


def load_layer_configs() -> AgentLayerConfigs:
    """Load layer configs from environment variables with defaults.

    Environment variables (all optional, defaults applied when unset):
      PERCEPTION_MODEL_ID, PERCEPTION_TEMPERATURE, PERCEPTION_MAX_TOKENS
      REASONING_MODEL_ID, REASONING_TEMPERATURE, REASONING_MAX_TOKENS
      ACT_MODEL_ID, ACT_TEMPERATURE, ACT_MAX_TOKENS
      GOVERNANCE_MODEL_ID, GOVERNANCE_TEMPERATURE, GOVERNANCE_MAX_TOKENS
      BEDROCK_REGION (shared across all layers)
    """
    region = BEDROCK_REGION

    perception = LayerModelConfig(
        model_id=PERCEPTION_MODEL_ID or _DEFAULT_PERCEPTION_MODEL,
        region_name=region,
        temperature=_parse_float(PERCEPTION_TEMPERATURE, _DEFAULT_PERCEPTION_TEMPERATURE),
        max_tokens=_parse_int(PERCEPTION_MAX_TOKENS, _DEFAULT_PERCEPTION_MAX_TOKENS),
    )

    reasoning = LayerModelConfig(
        model_id=REASONING_MODEL_ID or _DEFAULT_REASONING_MODEL,
        region_name=region,
        temperature=_parse_float(REASONING_TEMPERATURE, _DEFAULT_REASONING_TEMPERATURE),
        max_tokens=_parse_int(REASONING_MAX_TOKENS, _DEFAULT_REASONING_MAX_TOKENS),
    )

    act = LayerModelConfig(
        model_id=ACT_MODEL_ID or _DEFAULT_ACT_MODEL,
        region_name=region,
        temperature=_parse_float(ACT_TEMPERATURE, _DEFAULT_ACT_TEMPERATURE),
        max_tokens=_parse_int(ACT_MAX_TOKENS, _DEFAULT_ACT_MAX_TOKENS),
    )

    governance = LayerModelConfig(
        model_id=GOVERNANCE_MODEL_ID or _DEFAULT_GOVERNANCE_MODEL,
        region_name=region,
        temperature=_parse_float(GOVERNANCE_TEMPERATURE, _DEFAULT_GOVERNANCE_TEMPERATURE),
        max_tokens=_parse_int(GOVERNANCE_MAX_TOKENS, _DEFAULT_GOVERNANCE_MAX_TOKENS),
    )

    return AgentLayerConfigs(
        perception=perception,
        reasoning=reasoning,
        act=act,
        governance=governance,
    )
