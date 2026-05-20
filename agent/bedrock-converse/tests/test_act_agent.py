"""Unit tests for act_agent.py.

Tests verify:
- execute_physical_action looks up the active profile and dispatches through dispatch_command
- execute_physical_action returns descriptive error for unknown actions per profile
- execute_physical_action parses JSON parameters correctly
- execute_physical_action handles malformed JSON parameters
- execute_physical_action works with different robot_id values
- create_act_agent creates agent with correct tools and system prompt
"""

import sys
import json
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

import act_agent
from act_agent import (
    create_act_agent,
    init_act_agent,
    execute_physical_action,
    _ALL_ACT_TOOLS,
    _DIRECT_DISPATCH_ACTIONS,
    ACT_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers — build a mock profile
# ---------------------------------------------------------------------------

def _make_mock_profile(display_name="Zumi", tool_names=("headlights_on", "drive_forward", "show_emotion", "play_note", "display_text", "emergency_stop", "move_centimeters")):
    """Return a MagicMock that behaves like a HardwareProfile."""
    profile = MagicMock()
    profile.display_name = display_name
    profile.tool_names = tool_names
    return profile


# ---------------------------------------------------------------------------
# create_act_agent
# ---------------------------------------------------------------------------


@patch("act_agent.Agent")
def test_create_act_agent_uses_correct_tools_and_prompt(mock_agent_cls):
    mock_model = MagicMock()
    create_act_agent(mock_model)

    mock_agent_cls.assert_called_once_with(
        model=mock_model,
        tools=_ALL_ACT_TOOLS,
        system_prompt=ACT_SYSTEM_PROMPT,
        callback_handler=None,
    )


@patch("act_agent.Agent")
def test_create_act_agent_returns_agent_instance(mock_agent_cls):
    mock_model = MagicMock()
    mock_agent_cls.return_value = MagicMock(name="agent_instance")

    agent = create_act_agent(mock_model)

    assert agent is mock_agent_cls.return_value


@patch("act_agent.Agent")
def test_create_act_agent_has_all_27_tools(mock_agent_cls):
    """Verify the agent is created with all 27 act tools."""
    mock_model = MagicMock()
    create_act_agent(mock_model)

    call_kwargs = mock_agent_cls.call_args[1]
    tools = call_kwargs["tools"]
    # 7 drive + 5 advanced + 12 LED + 3 other = 27 tools
    assert len(tools) == 27


# ---------------------------------------------------------------------------
# init_act_agent
# ---------------------------------------------------------------------------


@patch("act_agent.create_act_agent")
def test_init_act_agent_sets_module_agent(mock_create):
    mock_model = MagicMock()
    mock_agent = MagicMock()
    mock_create.return_value = mock_agent

    init_act_agent(mock_model)

    mock_create.assert_called_once_with(mock_model)
    assert act_agent._act_agent is mock_agent

    # Clean up module state.
    act_agent._act_agent = None


# ---------------------------------------------------------------------------
# execute_physical_action — profile-based dispatch for known actions
# ---------------------------------------------------------------------------


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_headlights_on(mock_get_profile, mock_dispatch):
    """Known action dispatches through dispatch_command with the profile."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "headlights_on"}

    result = execute_physical_action(action="headlights_on", parameters="{}")

    mock_get_profile.assert_called_once_with("zumi")
    mock_dispatch.assert_called_once_with(profile, "headlights_on", {})
    assert result["status"] == "ok"
    assert result["action"] == "headlights_on"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_show_emotion(mock_get_profile, mock_dispatch):
    """show_emotion dispatches through profile — no LLM call needed."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "happy"}

    result = execute_physical_action(
        action="show_emotion",
        parameters='{"emotion": "happy"}',
    )

    mock_dispatch.assert_called_once_with(profile, "show_emotion", {"emotion": "happy"})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_play_note(mock_get_profile, mock_dispatch):
    """play_note dispatches through profile with correct parameters."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "play_note", "note": 25}

    result = execute_physical_action(
        action="play_note",
        parameters='{"note": 25, "duration_ms": 500}',
    )

    mock_dispatch.assert_called_once_with(profile, "play_note", {"note": 25, "duration_ms": 500})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_drive_forward(mock_get_profile, mock_dispatch):
    """Movement action dispatches through profile."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "forward"}

    result = execute_physical_action(
        action="drive_forward",
        parameters='{"speed": 40, "duration": 1.0}',
    )

    mock_dispatch.assert_called_once_with(profile, "drive_forward", {"speed": 40, "duration": 1.0})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_display_text(mock_get_profile, mock_dispatch):
    """display_text dispatches through profile."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "say", "message": "Hello!"}

    result = execute_physical_action(
        action="display_text",
        parameters='{"message": "Hello!"}',
    )

    mock_dispatch.assert_called_once_with(profile, "display_text", {"message": "Hello!"})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_emergency_stop(mock_get_profile, mock_dispatch):
    """emergency_stop dispatches through profile."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "stop"}

    result = execute_physical_action(action="emergency_stop", parameters="{}")

    mock_dispatch.assert_called_once_with(profile, "emergency_stop", {})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_move_centimeters(mock_get_profile, mock_dispatch):
    """move_centimeters dispatches through profile with distance param."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "move_centimeters"}

    result = execute_physical_action(
        action="move_centimeters",
        parameters='{"distance": 15.0}',
    )

    mock_dispatch.assert_called_once_with(profile, "move_centimeters", {"distance": 15.0})
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# execute_physical_action — XGO2 dispatch
# ---------------------------------------------------------------------------


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_xgo2_navigate(mock_get_profile, mock_dispatch):
    """XGO2 actions dispatch through the XGO2 profile."""
    profile = _make_mock_profile(
        display_name="XGO2 Robodog",
        tool_names=("xgo_navigate_to_target", "xgo_check_navigation_status", "xgo_stop_navigation"),
    )
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "xgo_navigate_to_target"}

    result = execute_physical_action(
        action="xgo_navigate_to_target",
        parameters='{"target_label": "cup", "speed": 15}',
        robot_id="xgo2",
    )

    mock_get_profile.assert_called_once_with("xgo2")
    mock_dispatch.assert_called_once_with(profile, "xgo_navigate_to_target", {"target_label": "cup", "speed": 15})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_dispatch_xgo2_stop_navigation(mock_get_profile, mock_dispatch):
    """XGO2 stop navigation dispatches through the XGO2 profile."""
    profile = _make_mock_profile(
        display_name="XGO2 Robodog",
        tool_names=("xgo_navigate_to_target", "xgo_check_navigation_status", "xgo_stop_navigation"),
    )
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "xgo_stop_navigation"}

    result = execute_physical_action(
        action="xgo_stop_navigation",
        parameters="{}",
        robot_id="xgo2",
    )

    mock_dispatch.assert_called_once_with(profile, "xgo_stop_navigation", {})
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# execute_physical_action — unknown action (profile-specific error)
# ---------------------------------------------------------------------------


@patch("act_agent.get_profile")
def test_unknown_action_returns_error_with_display_name(mock_get_profile):
    """Unknown actions return an error mentioning the profile's display name."""
    profile = _make_mock_profile(display_name="Zumi", tool_names=("headlights_on",))
    mock_get_profile.return_value = profile

    result = execute_physical_action(action="fly_away", parameters="{}")

    assert result["status"] == "error"
    assert result["action"] == "fly_away"
    assert "Unknown action for Zumi: fly_away" in result["message"]


@patch("act_agent.get_profile")
def test_unknown_action_xgo2_returns_error_with_display_name(mock_get_profile):
    """Unknown actions for XGO2 mention XGO2's display name."""
    profile = _make_mock_profile(
        display_name="XGO2 Robodog",
        tool_names=("xgo_navigate_to_target",),
    )
    mock_get_profile.return_value = profile

    result = execute_physical_action(action="headlights_on", parameters="{}", robot_id="xgo2")

    assert result["status"] == "error"
    assert "Unknown action for XGO2 Robodog: headlights_on" in result["message"]


# ---------------------------------------------------------------------------
# execute_physical_action — parameter parsing
# ---------------------------------------------------------------------------


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_empty_parameters_string(mock_get_profile, mock_dispatch):
    """Empty string parameters should parse to empty dict."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "headlights_on"}

    result = execute_physical_action(action="headlights_on", parameters="")

    mock_dispatch.assert_called_once_with(profile, "headlights_on", {})
    assert result["status"] == "ok"


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_malformed_json_parameters(mock_get_profile, mock_dispatch):
    """Malformed JSON should fall back to empty dict."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok", "action": "headlights_on"}

    result = execute_physical_action(action="headlights_on", parameters="not-json")

    mock_dispatch.assert_called_once_with(profile, "headlights_on", {})
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# execute_physical_action — default robot_id
# ---------------------------------------------------------------------------


@patch("act_agent.dispatch_command")
@patch("act_agent.get_profile")
def test_default_robot_id_is_zumi(mock_get_profile, mock_dispatch):
    """When robot_id is not specified, it defaults to 'zumi'."""
    profile = _make_mock_profile()
    mock_get_profile.return_value = profile
    mock_dispatch.return_value = {"status": "ok"}

    execute_physical_action(action="headlights_on", parameters="{}")

    mock_get_profile.assert_called_once_with("zumi")


# ---------------------------------------------------------------------------
# _DIRECT_DISPATCH_ACTIONS still exists (kept for backward compatibility)
# ---------------------------------------------------------------------------


def test_direct_dispatch_actions_set_exists():
    """_DIRECT_DISPATCH_ACTIONS set is still defined for backward compatibility."""
    assert isinstance(_DIRECT_DISPATCH_ACTIONS, set)
    assert "drive_forward" in _DIRECT_DISPATCH_ACTIONS
    assert "headlights_on" in _DIRECT_DISPATCH_ACTIONS
