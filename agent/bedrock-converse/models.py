"""Data models for the agentic layered architecture.

Structured dataclasses used across the four agent layers (Perception,
Reasoning, Act, Governance) and the orchestrator.  These are plain
data containers — no Bedrock or IoT dependencies — so they can be
imported freely in tests and any layer module.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PerceptionResult:
    """Structured output from the Perception layer.

    Attributes:
        found: Whether the target was detected in the scene.
        position: Relative position in the camera frame
            ("left", "center", "right", or None).
        estimated_distance_cm: Estimated distance to the target in cm,
            or None if uncertain.  Must be positive when set.
        confidence: Confidence level of the observation
            ("high", "medium", or "low").
        description: Human-readable description of what was observed.
        image_url: Presigned S3 GET URL for the captured photo, if any.
        sensor_data: Optional supplementary sensor readings.
    """

    found: bool
    position: str | None
    estimated_distance_cm: float | None
    confidence: str  # "high" | "medium" | "low"
    description: str
    image_url: str | None = None
    sensor_data: dict = field(default_factory=dict)


@dataclass
class ActionRequest:
    """A request to execute a physical action, sent to Governance.

    Attributes:
        action: Zumi command name (e.g. "drive_forward", "turn_left").
        parameters: Action-specific parameters.
        goal_description: Optional high-level goal context.
        perception_before: Perception snapshot taken before the action.
    """

    action: str
    parameters: dict = field(default_factory=dict)
    goal_description: str = ""
    perception_before: PerceptionResult | None = None


@dataclass
class GovernanceDecision:
    """Output from the Governance layer's safety validation step.

    Attributes:
        approved: Whether the action passed safety checks.
        safety_notes: Human-readable warnings for the step trace.
        modified_parameters: Present only if governance clamped values.
        reason: Explanation when the action is blocked (non-empty if
            approved is False).
    """

    approved: bool
    safety_notes: list[str] = field(default_factory=list)
    modified_parameters: dict | None = None
    reason: str = ""


@dataclass
class ActionResult:
    """Combined result from governance validation + act execution + feedback.

    Attributes:
        status: Outcome — "ok", "blocked", or "error".
        action: The Zumi command that was requested.
        governance: The governance decision for this action.
        execution_result: Raw result dict from the Act layer, or None
            if the action was blocked.
        feedback: Post-execution assessment — "goal_met", "continue",
            or "abort".
        cumulative_distance_cm: Total distance moved so far in the
            conversation (never decreases).
    """

    status: str  # "ok" | "blocked" | "error"
    action: str
    governance: GovernanceDecision
    execution_result: dict | None = None
    feedback: str = "continue"  # "goal_met" | "continue" | "abort"
    cumulative_distance_cm: float = 0.0


@dataclass
class ConversationStep:
    """A single step in the reasoning trace, shown in the chat UI.

    Attributes:
        type: Step kind — "reasoning", "tool_call", or "tool_result".
        layer: Which agent layer produced this step — "perception",
            "reasoning", "act", or "governance".
        text: Reasoning text (for type="reasoning").
        tool: Tool name (for type="tool_call" or "tool_result").
        input_data: Tool input parameters (for type="tool_call").
        result: Tool result payload (for type="tool_result").
    """

    type: str  # "reasoning" | "tool_call" | "tool_result"
    layer: str  # "perception" | "reasoning" | "act" | "governance"
    text: str = ""
    tool: str = ""
    input_data: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize for JSON response, omitting empty fields.

        The output uses the key ``"input"`` (not ``"input_data"``) for
        backward compatibility with the existing frontend which reads
        ``s.input`` when rendering tool-call steps.
        """
        d: dict = {"type": self.type, "layer": self.layer}
        if self.text:
            d["text"] = self.text
        if self.tool:
            d["tool"] = self.tool
        if self.input_data:
            d["input"] = self.input_data
        if self.result:
            d["result"] = self.result
        return d
