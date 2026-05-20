"""Unit tests for the data model classes in models.py."""

from models import (
    ActionRequest,
    ActionResult,
    ConversationStep,
    GovernanceDecision,
    PerceptionResult,
)


# ---------------------------------------------------------------------------
# PerceptionResult
# ---------------------------------------------------------------------------

def test_perception_result_defaults():
    pr = PerceptionResult(
        found=True,
        position="center",
        estimated_distance_cm=15.0,
        confidence="high",
        description="Wrist watch detected",
    )
    assert pr.found is True
    assert pr.position == "center"
    assert pr.estimated_distance_cm == 15.0
    assert pr.confidence == "high"
    assert pr.description == "Wrist watch detected"
    assert pr.image_url is None
    assert pr.sensor_data == {}


def test_perception_result_with_optional_fields():
    pr = PerceptionResult(
        found=False,
        position=None,
        estimated_distance_cm=None,
        confidence="low",
        description="Nothing detected",
        image_url="https://s3.example.com/photo.jpg",
        sensor_data={"ir_front_left": 120},
    )
    assert pr.image_url == "https://s3.example.com/photo.jpg"
    assert pr.sensor_data == {"ir_front_left": 120}


# ---------------------------------------------------------------------------
# ActionRequest
# ---------------------------------------------------------------------------

def test_action_request_defaults():
    ar = ActionRequest(action="drive_forward")
    assert ar.action == "drive_forward"
    assert ar.parameters == {}
    assert ar.goal_description == ""
    assert ar.perception_before is None


def test_action_request_with_perception():
    pr = PerceptionResult(
        found=True, position="left", estimated_distance_cm=30.0,
        confidence="medium", description="Object on the left",
    )
    ar = ActionRequest(
        action="turn_left",
        parameters={"angle": 15},
        goal_description="Align with target",
        perception_before=pr,
    )
    assert ar.perception_before is not None
    assert ar.perception_before.position == "left"


# ---------------------------------------------------------------------------
# GovernanceDecision
# ---------------------------------------------------------------------------

def test_governance_decision_defaults():
    gd = GovernanceDecision(approved=True)
    assert gd.approved is True
    assert gd.safety_notes == []
    assert gd.modified_parameters is None
    assert gd.reason == ""


def test_governance_decision_blocked():
    gd = GovernanceDecision(
        approved=False,
        safety_notes=["Speed exceeds safe limit"],
        reason="Cumulative distance exceeded 100cm",
    )
    assert gd.approved is False
    assert len(gd.safety_notes) == 1
    assert gd.reason != ""


# ---------------------------------------------------------------------------
# ActionResult
# ---------------------------------------------------------------------------

def test_action_result_defaults():
    gd = GovernanceDecision(approved=True)
    ar = ActionResult(status="ok", action="drive_forward", governance=gd)
    assert ar.status == "ok"
    assert ar.execution_result is None
    assert ar.feedback == "continue"
    assert ar.cumulative_distance_cm == 0.0


def test_action_result_blocked():
    gd = GovernanceDecision(approved=False, reason="Too fast")
    ar = ActionResult(
        status="blocked",
        action="drive_forward",
        governance=gd,
        execution_result=None,
        feedback="abort",
    )
    assert ar.status == "blocked"
    assert ar.execution_result is None
    assert ar.feedback == "abort"


# ---------------------------------------------------------------------------
# ConversationStep
# ---------------------------------------------------------------------------

def test_conversation_step_reasoning_to_dict():
    step = ConversationStep(
        type="reasoning",
        layer="reasoning",
        text="Planning next move",
    )
    d = step.to_dict()
    assert d == {"type": "reasoning", "layer": "reasoning", "text": "Planning next move"}
    # Empty fields should be omitted
    assert "tool" not in d
    assert "input" not in d
    assert "result" not in d


def test_conversation_step_tool_call_to_dict():
    step = ConversationStep(
        type="tool_call",
        layer="perception",
        tool="take_photo",
        input_data={"target": "wrist watch"},
    )
    d = step.to_dict()
    assert d == {
        "type": "tool_call",
        "layer": "perception",
        "tool": "take_photo",
        "input": {"target": "wrist watch"},
    }
    # Key must be "input", not "input_data"
    assert "input_data" not in d
    assert "text" not in d
    assert "result" not in d


def test_conversation_step_tool_result_to_dict():
    step = ConversationStep(
        type="tool_result",
        layer="act",
        tool="drive_forward",
        result={"status": "ok", "clamped_speed": 40},
    )
    d = step.to_dict()
    assert d == {
        "type": "tool_result",
        "layer": "act",
        "tool": "drive_forward",
        "result": {"status": "ok", "clamped_speed": 40},
    }
    assert "text" not in d
    assert "input" not in d


def test_conversation_step_empty_fields_omitted():
    """All optional fields empty → only type and layer in output."""
    step = ConversationStep(type="reasoning", layer="governance")
    d = step.to_dict()
    assert d == {"type": "reasoning", "layer": "governance"}


def test_conversation_step_all_fields_populated():
    step = ConversationStep(
        type="tool_call",
        layer="governance",
        text="Validating action",
        tool="validate_action",
        input_data={"action": "drive_forward", "speed": 80},
        result={"approved": True},
    )
    d = step.to_dict()
    assert d["type"] == "tool_call"
    assert d["layer"] == "governance"
    assert d["text"] == "Validating action"
    assert d["tool"] == "validate_action"
    assert d["input"] == {"action": "drive_forward", "speed": 80}
    assert d["result"] == {"approved": True}


# ---------------------------------------------------------------------------
# Default factory isolation (mutable defaults don't leak between instances)
# ---------------------------------------------------------------------------

def test_mutable_defaults_are_independent():
    """Verify that mutable default fields are independent across instances."""
    pr1 = PerceptionResult(
        found=True, position="center", estimated_distance_cm=10.0,
        confidence="high", description="A",
    )
    pr2 = PerceptionResult(
        found=False, position=None, estimated_distance_cm=None,
        confidence="low", description="B",
    )
    pr1.sensor_data["ir"] = 100
    assert pr2.sensor_data == {}

    gd1 = GovernanceDecision(approved=True)
    gd2 = GovernanceDecision(approved=False, reason="blocked")
    gd1.safety_notes.append("note")
    assert gd2.safety_notes == []

    s1 = ConversationStep(type="reasoning", layer="reasoning")
    s2 = ConversationStep(type="tool_call", layer="act")
    s1.input_data["x"] = 1
    s1.result["y"] = 2
    assert s2.input_data == {}
    assert s2.result == {}
