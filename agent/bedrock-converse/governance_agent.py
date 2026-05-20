"""Governance Agent — validates actions and evaluates outcomes.

This module implements the Governance layer of the agentic architecture.
It wraps the Act layer with safety validation: every physical command is
checked against safety policies before execution, and outcomes are
evaluated afterward.

The ``governed_execute`` @tool function calls governance tools DIRECTLY
as pure functions (the validation logic is deterministic and does not
need LLM reasoning).  The Strands governance agent is created for
potential future use but is not invoked in the hot path.

The module uses a lazy-init pattern: call ``init_governance_agent(model)``
once at startup, then ``governed_execute`` is ready for use.
"""

from __future__ import annotations

import json
from typing import Any

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

import config
from hardware_registry import get_profile
from tools.governance_tools import (
    validate_action,
    evaluate_outcome,
    check_safety_state,
)

# ── System Prompt ─────────────────────────────────────────────────────────

GOVERNANCE_SYSTEM_PROMPT = """\
You are the Governance and Feedback Layer of a Zumi robot control system.
You have two responsibilities:

1. SAFETY VALIDATION (before action):
   - Check if the requested action is safe to execute
   - Verify parameters are within safe ranges
   - Block dangerous sequences
   - Apply safety policies: max 20cm per movement step during vision-guided navigation,
     max speed 60 for autonomous movement, emergency stop on safety concern

2. FEEDBACK EVALUATION (after action):
   - Assess whether the action achieved its intended goal
   - Compare perception before/after to measure progress
   - Decide: goal_met, continue (more steps needed), or abort (unsafe/stuck)
   - Track cumulative movement to prevent runaway sequences

Safety policies:
- Movement during vision-guided nav: max 20cm per step, max speed 60
- Total movement per command: max 100cm cumulative
- If 5 consecutive actions without progress toward goal: recommend abort
- Emergency stop takes priority over all other actions"""


def create_governance_agent(model: BedrockModel) -> Agent:
    """Create the governance layer agent with safety tools."""
    return Agent(
        model=model,
        tools=[validate_action, evaluate_outcome, check_safety_state],
        system_prompt=GOVERNANCE_SYSTEM_PROMPT,
        callback_handler=None,
    )


# ── Module-level state (lazy-init) ────────────────────────────────────────

_governance_agent: Agent | None = None
_act_agent_ref: Any = None  # reference to execute_physical_action tool


def init_governance_agent(model: BedrockModel) -> None:
    """Initialize the module-level governance agent.

    Must be called once at startup before ``governed_execute`` is used.
    """
    global _governance_agent
    _governance_agent = create_governance_agent(model)


def set_act_agent(act_agent: Any) -> None:
    """Set the reference to the act agent's execute_physical_action tool.

    This allows the governance layer to delegate approved actions to the
    act layer without a circular import.

    Args:
        act_agent: The ``execute_physical_action`` callable from
            ``act_agent.py``.
    """
    global _act_agent_ref
    _act_agent_ref = act_agent


# ── Distance estimation helpers ───────────────────────────────────────────

_SHAPE_ACTIONS = {
    "drive_circle", "drive_square", "drive_figure_8",
    "parallel_park", "j_turn",
}

_TURN_ACTIONS = {"turn_left", "turn_right"}


def _estimate_distance_cm(action: str, params: dict) -> float:
    """Estimate the distance in cm that a movement action covers.

    Returns 0.0 for non-movement actions.
    """
    if action == "move_centimeters":
        return abs(float(params.get("distance", 0)))

    if action == "move_inches":
        return abs(float(params.get("distance", 0))) * 2.54

    if action in ("drive_forward", "drive_reverse"):
        speed = float(params.get("speed", 40))
        duration = float(params.get("duration", 1.0))
        return speed * duration * 0.3

    if action in _TURN_ACTIONS:
        return 10.0

    if action in _SHAPE_ACTIONS:
        return 30.0

    return 0.0


# ── Main tool ─────────────────────────────────────────────────────────────

@tool
def governed_execute(action: str, parameters: str, context: str, robot_id: str = "") -> dict:
    """Validate and execute a physical action with safety governance.

    Calls governance tools directly (deterministic logic, no LLM needed),
    then delegates approved actions to the Act layer.

    Args:
        action: The action name (e.g. "drive_forward", "xgo_navigate_to_target").
        parameters: JSON string of action parameters.
        context: JSON string of current state context
            (e.g. '{"cumulative_distance_cm": 50, "vision_guided": true}').
        robot_id: Robot identifier. Defaults to config.DEFAULT_ROBOT.

    Returns:
        dict with keys: status, action, governance, execution_result,
        feedback, cumulative_distance_cm.
    """
    _robot_id = robot_id or config.DEFAULT_ROBOT
    profile = get_profile(_robot_id)

    # Parse JSON string parameters.
    try:
        params: dict = json.loads(parameters) if parameters else {}
    except (ValueError, TypeError):
        params = {}

    try:
        ctx: dict = json.loads(context) if context else {}
    except (ValueError, TypeError):
        ctx = {}

    cumulative = float(ctx.get("cumulative_distance_cm", 0.0))

    # ── Emergency stop: always approved, skip governance ──────────────
    if action in profile.emergency_stop_actions:
        exec_result: dict[str, Any] = {"status": "error", "action": action, "message": "Act agent not initialized"}
        if _act_agent_ref is not None:
            try:
                exec_result = _act_agent_ref(action=action, parameters=json.dumps(params), robot_id=_robot_id)
            except Exception as e:
                exec_result = {"status": "error", "action": action, "message": str(e)}

        return {
            "status": "ok",
            "action": action,
            "governance": {
                "approved": True,
                "safety_notes": [],
                "modified_parameters": None,
                "reason": "",
            },
            "execution_result": exec_result,
            "feedback": "goal_met",
            "cumulative_distance_cm": cumulative,
        }

    # ── Check act agent is initialized ────────────────────────────────
    if _act_agent_ref is None:
        return {
            "status": "error",
            "action": action,
            "governance": {
                "approved": False,
                "safety_notes": [],
                "modified_parameters": None,
                "reason": "Act agent not initialized",
            },
            "execution_result": None,
            "feedback": "abort",
            "cumulative_distance_cm": cumulative,
        }

    # ── Step 1: Validate action ───────────────────────────────────────
    decision = validate_action(
        action=action,
        parameters=json.dumps(params),
        context=json.dumps(ctx),
        robot_id=_robot_id,
    )

    # ── Step 2: If not approved, return blocked ───────────────────────
    if not decision.get("approved", False):
        feedback = "abort" if "unsafe" in decision.get("reason", "").lower() else "continue"
        return {
            "status": "blocked",
            "action": action,
            "governance": decision,
            "execution_result": None,
            "feedback": feedback,
            "cumulative_distance_cm": cumulative,
        }

    # ── Step 3: Get effective parameters ──────────────────────────────
    effective_params = decision.get("modified_parameters") or params

    # ── Step 4: Execute via act layer ─────────────────────────────────
    try:
        exec_result = _act_agent_ref(
            action=action,
            parameters=json.dumps(effective_params),
            robot_id=_robot_id,
        )
    except Exception as e:
        return {
            "status": "error",
            "action": action,
            "governance": decision,
            "execution_result": {"status": "error", "message": str(e)},
            "feedback": "abort",
            "cumulative_distance_cm": cumulative,
        }

    # ── Step 5: Update cumulative distance ────────────────────────────
    distance_added = _estimate_distance_cm(action, effective_params)
    new_cumulative = cumulative + distance_added

    # ── Step 6: Evaluate outcome ──────────────────────────────────────
    outcome = evaluate_outcome(
        action=action,
        result=json.dumps(exec_result) if isinstance(exec_result, dict) else str(exec_result),
        context=json.dumps(ctx),
    )
    feedback = outcome.get("feedback", "continue")

    return {
        "status": "ok",
        "action": action,
        "governance": decision,
        "execution_result": exec_result,
        "feedback": feedback,
        "cumulative_distance_cm": new_cumulative,
    }
