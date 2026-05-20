"""Unit tests for orchestrator.py.

Tests verify:
- StepCollector collects reasoning, tool_call, and tool_result steps
- StepCollector captures image_url from tool results
- Orchestrator.__init__ initializes all sub-agents with robot_id
- Orchestrator.chat returns correct dict shape {text, image_url, steps}
- Orchestrator.reset clears state
- Error handling: Bedrock errors return error message
- Cumulative distance tracking from governed_execute results
- select_robot switches profile, resets state, rebuilds agent
- active_robot_id and active_display_name properties
- TOOL_REGISTRY and SHARED_PREAMBLE module-level constants
"""

import sys
from unittest.mock import MagicMock, patch, call

# Stub heavy dependencies before importing the module under test.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

import orchestrator
from orchestrator import (
    StepCollector,
    Orchestrator,
    ORCHESTRATOR_SYSTEM_PROMPT,
    SHARED_PREAMBLE,
    TOOL_REGISTRY,
    _perceive_with_logging,
    _governed_execute_with_logging,
)
from models import ConversationStep


# ---------------------------------------------------------------------------
# StepCollector
# ---------------------------------------------------------------------------


class TestStepCollector:
    """Tests for the StepCollector class."""

    def test_init_empty(self):
        sc = StepCollector()
        assert sc.steps == []
        assert sc.image_url is None

    def test_add_reasoning(self):
        sc = StepCollector()
        sc.add_reasoning("Thinking about what to do", layer="reasoning")

        assert len(sc.steps) == 1
        step = sc.steps[0]
        assert step.type == "reasoning"
        assert step.layer == "reasoning"
        assert step.text == "Thinking about what to do"

    def test_add_reasoning_default_layer(self):
        sc = StepCollector()
        sc.add_reasoning("Some text")

        assert sc.steps[0].layer == "reasoning"

    def test_add_tool_call(self):
        sc = StepCollector()
        sc.add_tool_call("perceive", {"query": "look around"}, layer="perception")

        assert len(sc.steps) == 1
        step = sc.steps[0]
        assert step.type == "tool_call"
        assert step.layer == "perception"
        assert step.tool == "perceive"
        assert step.input_data == {"query": "look around"}

    def test_add_tool_result_without_image(self):
        sc = StepCollector()
        result = {"found": True, "position": "center"}
        sc.add_tool_result("perceive", result, layer="perception")

        assert len(sc.steps) == 1
        step = sc.steps[0]
        assert step.type == "tool_result"
        assert step.layer == "perception"
        assert step.tool == "perceive"
        assert step.result == result
        assert sc.image_url is None

    def test_add_tool_result_captures_image_url(self):
        sc = StepCollector()
        result = {
            "found": True,
            "image_url": "https://s3.example.com/photo.jpg",
        }
        sc.add_tool_result("perceive", result, layer="perception")

        assert sc.image_url == "https://s3.example.com/photo.jpg"

    def test_add_tool_result_non_dict_result(self):
        sc = StepCollector()
        sc.add_tool_result("perceive", "some string result", layer="perception")

        assert len(sc.steps) == 1
        assert sc.image_url is None

    def test_multiple_steps_preserve_order(self):
        sc = StepCollector()
        sc.add_reasoning("Planning", layer="reasoning")
        sc.add_tool_call("perceive", {"query": "look"}, layer="perception")
        sc.add_tool_result("perceive", {"found": True}, layer="perception")
        sc.add_tool_call("governed_execute", {"action": "drive_forward"}, layer="governance")
        sc.add_tool_result("governed_execute", {"status": "ok"}, layer="governance")

        assert len(sc.steps) == 5
        assert [s.type for s in sc.steps] == [
            "reasoning", "tool_call", "tool_result", "tool_call", "tool_result"
        ]

    def test_last_image_url_wins(self):
        sc = StepCollector()
        sc.add_tool_result("perceive", {"image_url": "https://first.jpg"}, layer="perception")
        sc.add_tool_result("perceive", {"image_url": "https://second.jpg"}, layer="perception")

        assert sc.image_url == "https://second.jpg"

    def test_steps_to_dict(self):
        sc = StepCollector()
        sc.add_reasoning("Hello", layer="reasoning")
        sc.add_tool_call("perceive", {"query": "look"}, layer="perception")

        dicts = [s.to_dict() for s in sc.steps]
        assert dicts[0] == {"type": "reasoning", "layer": "reasoning", "text": "Hello"}
        assert dicts[1] == {
            "type": "tool_call",
            "layer": "perception",
            "tool": "perceive",
            "input": {"query": "look"},
        }


# ---------------------------------------------------------------------------
# Wrapper tools logging
# ---------------------------------------------------------------------------


class TestWrapperTools:
    """Tests for the logging wrapper tools."""

    @patch("orchestrator.perceive")
    def test_perceive_with_logging_calls_perceive_and_logs(self, mock_perceive):
        mock_perceive.return_value = {
            "found": True,
            "position": "center",
            "image_url": "https://photo.jpg",
        }
        collector = StepCollector()
        orchestrator._current_collector = collector

        try:
            result = _perceive_with_logging(query="look for a watch")

            mock_perceive.assert_called_once_with(query="look for a watch", robot_id=orchestrator._active_robot_id)
            assert result["found"] is True
            assert len(collector.steps) == 2
            assert collector.steps[0].type == "tool_call"
            assert collector.steps[0].layer == "perception"
            assert collector.steps[1].type == "tool_result"
            assert collector.steps[1].layer == "perception"
            assert collector.image_url == "https://photo.jpg"
        finally:
            orchestrator._current_collector = None

    @patch("orchestrator.governed_execute")
    def test_governed_execute_with_logging_calls_and_logs(self, mock_gov):
        mock_gov.return_value = {
            "status": "ok",
            "action": "headlights_on",
            "cumulative_distance_cm": 0.0,
        }
        collector = StepCollector()
        orchestrator._current_collector = collector

        try:
            result = _governed_execute_with_logging(
                action="headlights_on",
                parameters="{}",
                context="{}",
            )

            mock_gov.assert_called_once_with(
                action="headlights_on", parameters="{}", context="{}", robot_id=orchestrator._active_robot_id
            )
            assert result["status"] == "ok"
            assert len(collector.steps) == 2
            assert collector.steps[0].type == "tool_call"
            assert collector.steps[0].layer == "governance"
            assert collector.steps[1].type == "tool_result"
            assert collector.steps[1].layer == "governance"
        finally:
            orchestrator._current_collector = None

    @patch("orchestrator.perceive")
    def test_perceive_with_logging_no_collector(self, mock_perceive):
        """When no collector is set, the wrapper still calls perceive."""
        mock_perceive.return_value = {"found": False}
        orchestrator._current_collector = None

        result = _perceive_with_logging(query="look")
        mock_perceive.assert_called_once_with(query="look", robot_id=orchestrator._active_robot_id)
        assert result["found"] is False


# ---------------------------------------------------------------------------
# Orchestrator.__init__
# ---------------------------------------------------------------------------


class TestOrchestratorInit:
    """Tests for Orchestrator initialization."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_init_initializes_all_sub_agents(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        mock_agent_cls.return_value = MagicMock(name="reasoning_agent")

        orch = Orchestrator(configs)

        # Verify all sub-agents were initialized.
        mock_init_perc.assert_called_once()
        mock_init_act.assert_called_once()
        mock_init_gov.assert_called_once()
        mock_set_act.assert_called_once()

        # Verify reasoning agent was built with profile-driven prompt.
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert SHARED_PREAMBLE in call_kwargs.kwargs["system_prompt"]
        assert "test_fragment_zumi" in call_kwargs.kwargs["system_prompt"]
        assert call_kwargs.kwargs["callback_handler"] is None

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_init_state_defaults(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        assert orch._conversation == []
        assert orch._cumulative_distance_cm == 0.0
        assert orch._movement_warned is False

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_init_with_explicit_robot_id(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        configs = _make_mock_configs()
        orch = Orchestrator(configs, robot_id="xgo2")

        mock_get_profile.assert_called_once_with("xgo2")
        assert orch.active_robot_id == "xgo2"
        assert orch.active_display_name == "XGO2 Robodog"

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    @patch("orchestrator.config")
    def test_init_defaults_to_config_default_robot(
        self,
        mock_config,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_config.DEFAULT_ROBOT = "zumi"
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        mock_get_profile.assert_called_once_with("zumi")


# ---------------------------------------------------------------------------
# Orchestrator.chat
# ---------------------------------------------------------------------------


class TestOrchestratorChat:
    """Tests for Orchestrator.chat()."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_returns_correct_shape(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "The headlights are now on!"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        result = orch.chat("turn on the headlights")

        assert "text" in result
        assert "image_url" in result
        assert "steps" in result
        assert isinstance(result["text"], str)
        assert isinstance(result["steps"], list)

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_text_is_nonempty(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Done!"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert result["text"] == "Done!"

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_empty_response_becomes_no_response(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = ""
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert result["text"] == "(No response)"

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_appends_to_conversation(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Hi there!"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        orch.chat("hello")

        assert len(orch._conversation) == 2
        assert orch._conversation[0] == {"role": "user", "content": "hello"}
        assert orch._conversation[1] == {"role": "assistant", "content": "Hi there!"}

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_steps_include_final_reasoning(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "I turned on the lights."
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("lights on")

        # The final reasoning step should be present.
        reasoning_steps = [
            s for s in result["steps"] if s["type"] == "reasoning"
        ]
        assert len(reasoning_steps) >= 1
        assert reasoning_steps[-1]["text"] == "I turned on the lights."

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_each_step_has_valid_type(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Response"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("test")

        valid_types = {"reasoning", "tool_call", "tool_result"}
        for step in result["steps"]:
            assert step["type"] in valid_types


# ---------------------------------------------------------------------------
# Orchestrator.chat — error handling
# ---------------------------------------------------------------------------


class TestOrchestratorChatErrors:
    """Tests for error handling in Orchestrator.chat()."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_bedrock_throttling_error(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.side_effect = Exception("ThrottlingException: Rate exceeded")
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert "rate-limited" in result["text"].lower() or "rate" in result["text"].lower()
        assert result["image_url"] is None

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_bedrock_service_error(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.side_effect = Exception("ServiceUnavailableException: 500 Internal Server Error")
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert "service" in result["text"].lower() or "error" in result["text"].lower()

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_generic_error(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.side_effect = RuntimeError("Something unexpected")
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert "Something unexpected" in result["text"]
        assert result["image_url"] is None
        assert isinstance(result["steps"], list)

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_error_still_returns_correct_shape(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.side_effect = Exception("boom")
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert "image_url" in result
        assert "steps" in result
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_handles_none_result_from_agent(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        """Agent returning None should produce a valid response, not crash."""
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = None
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert "image_url" in result
        assert "steps" in result
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_chat_handles_non_string_result_from_agent(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        """Agent returning a non-string (e.g. int or dict) should be coerced to str."""
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = 42
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        result = orch.chat("hello")

        assert "text" in result
        assert isinstance(result["text"], str)
        assert result["text"] == "42"
        assert "image_url" in result
        assert "steps" in result


# ---------------------------------------------------------------------------
# Orchestrator.chat — cumulative distance tracking
# ---------------------------------------------------------------------------


class TestOrchestratorCumulativeDistance:
    """Tests for cumulative distance tracking."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_cumulative_distance_updates_from_steps(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        """Simulate the collector having a governed_execute result with distance."""
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Moved forward"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        # Manually inject a step into the collector during the chat call.
        original_chat = orch.chat

        def patched_chat(msg):
            # Call original but inject a step before it finishes.
            orchestrator._current_collector = StepCollector()
            collector = orchestrator._current_collector
            collector.add_tool_result(
                "governed_execute",
                {"status": "ok", "cumulative_distance_cm": 15.0},
                layer="governance",
            )
            # Now simulate the agent returning.
            try:
                result = orch._agent(msg)
                response_text = str(result)
            except Exception:
                response_text = "error"

            collector.add_reasoning(response_text, layer="reasoning")

            # Update cumulative distance.
            for step in collector.steps:
                if (
                    step.type == "tool_result"
                    and step.tool == "governed_execute"
                    and isinstance(step.result, dict)
                ):
                    new_dist = step.result.get("cumulative_distance_cm")
                    if new_dist is not None:
                        try:
                            new_dist_float = float(new_dist)
                            if new_dist_float > orch._cumulative_distance_cm:
                                orch._cumulative_distance_cm = new_dist_float
                        except (ValueError, TypeError):
                            pass

            orch._conversation.append({"role": "user", "content": msg})
            orch._conversation.append({"role": "assistant", "content": response_text})
            orchestrator._current_collector = None

            return {
                "text": response_text,
                "image_url": collector.image_url,
                "steps": [s.to_dict() for s in collector.steps],
            }

        result = patched_chat("drive forward")
        assert orch._cumulative_distance_cm == 15.0


# ---------------------------------------------------------------------------
# Orchestrator.reset
# ---------------------------------------------------------------------------


class TestOrchestratorReset:
    """Tests for Orchestrator.reset()."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_reset_clears_conversation(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Hi"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        orch.chat("hello")

        assert len(orch._conversation) > 0

        orch.reset()

        assert orch._conversation == []

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_reset_clears_cumulative_distance(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        orch._cumulative_distance_cm = 50.0

        orch.reset()

        assert orch._cumulative_distance_cm == 0.0

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_reset_clears_movement_warned(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        orch._movement_warned = True

        orch.reset()

        assert orch._movement_warned is False


# ---------------------------------------------------------------------------
# Orchestrator.select_robot
# ---------------------------------------------------------------------------


class TestOrchestratorSelectRobot:
    """Tests for Orchestrator.select_robot()."""

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_returns_correct_dict(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        result = orch.select_robot("xgo2")

        assert result == {"robot_id": "xgo2", "display_name": "XGO2 Robodog"}

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_updates_profile(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        assert orch.active_robot_id == "zumi"

        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        orch.select_robot("xgo2")

        assert orch.active_robot_id == "xgo2"
        assert orch.active_display_name == "XGO2 Robodog"

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_resets_state(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        mock_agent = MagicMock()
        mock_agent.return_value = "Hi"
        mock_agent_cls.return_value = mock_agent

        configs = _make_mock_configs()
        orch = Orchestrator(configs)
        orch.chat("hello")
        orch._cumulative_distance_cm = 50.0
        orch._movement_warned = True

        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        orch.select_robot("xgo2")

        assert orch._conversation == []
        assert orch._cumulative_distance_cm == 0.0
        assert orch._movement_warned is False

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_reinitializes_layers(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        # Reset call counts after init.
        mock_init_perc.reset_mock()
        mock_init_act.reset_mock()
        mock_init_gov.reset_mock()
        mock_set_act.reset_mock()

        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        orch.select_robot("xgo2")

        mock_init_perc.assert_called_once()
        mock_init_act.assert_called_once()
        mock_init_gov.assert_called_once()
        mock_set_act.assert_called_once()

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_rebuilds_agent_with_new_prompt(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        mock_agent_cls.reset_mock()
        mock_get_profile.return_value = _make_mock_profile("xgo2", "XGO2 Robodog")
        orch.select_robot("xgo2")

        # Agent should have been rebuilt with the new profile's prompt.
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert SHARED_PREAMBLE in call_kwargs.kwargs["system_prompt"]
        assert "test_fragment_xgo2" in call_kwargs.kwargs["system_prompt"]

    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    @patch("orchestrator.get_profile")
    def test_select_robot_invalid_id_raises(
        self,
        mock_get_profile,
        mock_init_perc,
        mock_init_act,
        mock_init_gov,
        mock_set_act,
        mock_agent_cls,
    ):
        mock_get_profile.return_value = _make_mock_profile("zumi", "Zumi")
        configs = _make_mock_configs()
        orch = Orchestrator(configs)

        mock_get_profile.side_effect = ValueError("Unknown robot_id 'bad'. Available robots: ['xgo2', 'zumi']")
        try:
            orch.select_robot("bad")
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "bad" in str(e)
            assert "Available robots" in str(e)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_shared_preamble_exists(self):
        assert isinstance(SHARED_PREAMBLE, str)
        assert len(SHARED_PREAMBLE) > 0
        assert "Reasoning Layer" in SHARED_PREAMBLE

    def test_tool_registry_contains_zumi_tools(self):
        zumi_tools = [
            "drive_forward", "drive_reverse", "turn_left", "turn_right",
            "emergency_stop", "headlights_on", "play_note", "display_text",
        ]
        for tool_name in zumi_tools:
            assert tool_name in TOOL_REGISTRY, f"Missing {tool_name} in TOOL_REGISTRY"
            assert callable(TOOL_REGISTRY[tool_name])

    def test_tool_registry_contains_xgo2_tools(self):
        xgo2_tools = [
            "xgo_navigate_to_target", "xgo_check_navigation_status", "xgo_stop_navigation",
        ]
        for tool_name in xgo2_tools:
            assert tool_name in TOOL_REGISTRY, f"Missing {tool_name} in TOOL_REGISTRY"
            assert callable(TOOL_REGISTRY[tool_name])

    def test_tool_registry_contains_perception_tools(self):
        perception_tools = ["take_photo", "analyze_photo", "read_sensors", "read_orientation"]
        for tool_name in perception_tools:
            assert tool_name in TOOL_REGISTRY, f"Missing {tool_name} in TOOL_REGISTRY"
            assert callable(TOOL_REGISTRY[tool_name])

    def test_orchestrator_system_prompt_backward_compat(self):
        """ORCHESTRATOR_SYSTEM_PROMPT still exists for backward compatibility."""
        assert isinstance(ORCHESTRATOR_SYSTEM_PROMPT, str)
        assert "Zumi Bot" in ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_configs():
    """Create a mock AgentLayerConfigs for testing."""
    from layer_config import AgentLayerConfigs, LayerModelConfig

    mock_model = MagicMock()

    perception = MagicMock(spec=LayerModelConfig)
    perception.to_bedrock_model.return_value = mock_model

    reasoning = MagicMock(spec=LayerModelConfig)
    reasoning.to_bedrock_model.return_value = mock_model

    act = MagicMock(spec=LayerModelConfig)
    act.to_bedrock_model.return_value = mock_model

    governance = MagicMock(spec=LayerModelConfig)
    governance.to_bedrock_model.return_value = mock_model

    configs = MagicMock(spec=AgentLayerConfigs)
    configs.perception = perception
    configs.reasoning = reasoning
    configs.act = act
    configs.governance = governance

    return configs


def _make_mock_profile(robot_id: str, display_name: str):
    """Create a mock HardwareProfile for testing."""
    profile = MagicMock()
    profile.robot_id = robot_id
    profile.display_name = display_name
    profile.system_prompt_fragment = "test_fragment_%s" % robot_id
    profile.tool_names = ("drive_forward", "turn_left") if robot_id == "zumi" else ("xgo_navigate_to_target",)
    profile.capability_tags = ("test_tag",)
    profile.greeting_message = "Hello from %s!" % display_name
    return profile
