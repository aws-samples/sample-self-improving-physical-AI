"""Hardware profile dataclasses for multi-robot support.

Defines frozen dataclasses that encapsulate all robot-specific configuration:
safety limits, IoT connection parameters, and the complete hardware profile.
"""

from dataclasses import dataclass
from typing import Callable, Tuple


@dataclass(frozen=True)
class SafetyLimits:
    """Hardware-specific safety constraints read by the Governance layer."""

    max_speed: int
    max_vision_speed: int
    max_distance_per_step_cm: float
    max_cumulative_distance_cm: float
    max_navigation_steps: int


@dataclass(frozen=True)
class IoTConfig:
    """IoT connection parameters for a robot."""

    endpoint: str
    region: str
    thing_name: str
    command_topic: str


@dataclass(frozen=True)
class HardwareProfile:
    """Complete hardware profile for a robot platform.

    All required fields are validated in __post_init__. Construction raises
    ValueError listing every missing or empty required field if any fail
    validation.
    """

    robot_id: str
    display_name: str
    system_prompt_fragment: str
    tool_names: Tuple[str, ...]
    iot_config: IoTConfig
    safety_limits: SafetyLimits
    capability_tags: Tuple[str, ...]
    perception_prompt_fragment: str
    governance_prompt_fragment: str
    greeting_message: str
    send_command: Callable[[str, dict], dict]
    emergency_stop_actions: Tuple[str, ...] = ("emergency_stop",)

    def __post_init__(self) -> None:
        errors: list[str] = []

        # Required string fields — must be non-empty
        _required_str_fields = (
            "robot_id",
            "display_name",
            "system_prompt_fragment",
            "perception_prompt_fragment",
            "governance_prompt_fragment",
            "greeting_message",
        )
        for name in _required_str_fields:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                errors.append(name)

        # Required tuple fields — must be non-empty tuples
        _required_tuple_fields = ("tool_names", "capability_tags")
        for name in _required_tuple_fields:
            value = getattr(self, name)
            if not isinstance(value, tuple) or len(value) == 0:
                errors.append(name)

        # Type checks for nested dataclasses
        if not isinstance(self.iot_config, IoTConfig):
            errors.append("iot_config")

        if not isinstance(self.safety_limits, SafetyLimits):
            errors.append("safety_limits")

        # send_command must be callable
        if not callable(self.send_command):
            errors.append("send_command")

        if errors:
            raise ValueError(
                f"HardwareProfile validation failed — invalid or missing fields: "
                f"{', '.join(errors)}"
            )
