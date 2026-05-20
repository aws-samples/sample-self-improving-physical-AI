"""End-to-end integration tests for the agentic layered architecture.

These tests exercise the full pipeline from Orchestrator down through
Governance → Act → IoT Client, with mocked AWS services (Bedrock, IoT,
S3).  The Strands reasoning agent is also mocked so we can control
exactly which tools it calls and verify the full chain.

The tests validate:
1. A simple non-movement command flows through all layers correctly
2. A movement command flows through governance clamping and IoT publish
3. Emergency stop bypasses governance and reaches IoT immediately
4. Governance blocks unsafe actions before they reach IoT
5. Multi-step sequences track cumulative distance correctly
6. The API response shape matches the ChatResponse contract throughout

These tests also document a known limitation: movement commands currently
have no device-side acknowledgment.  The IoT client returns "ok" after
the MQTT publish succeeds, but there is no confirmation that the robot
actually executed the command.  See TestFeedbackGap for details.
"""

import sys
import json
from unittest.mock import MagicMock, patch, call

# Stub heavy dependencies before any chatbot imports.
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("boto3", MagicMock())

import iot_client
import orchestrator
import governance_agent
import act_agent
import perception_agent
from orchestrator import Orchestrator, StepCollector
from governance_agent import governed_execute, set_act_agent, init_governance_agent
from act_agent import execute_physical_action, init_act_agent
from perception_agent import perceive, init_perception_agent
from layer_config import LayerModelConfig, AgentLayerConfigs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_configs():
    """Create AgentLayerConfigs with mock models (no real Bedrock calls)."""
    mock_model = MagicMock()
    p = MagicMock(spec=LayerModelConfig)
    p.to_bedrock_model.return_value = mock_model
    r = MagicMock(spec=LayerModelConfig)
    r.to_bedrock_model.return_value = mock_model
    a = MagicMock(spec=LayerModelConfig)
    a.to_bedrock_model.return_value = mock_model
    g = MagicMock(spec=LayerModelConfig)
    g.to_bedrock_model.return_value = mock_model
    return AgentLayerConfigs(perception=p, reasoning=r, act=a, governance=g)


# ---------------------------------------------------------------------------
# 1. Simple non-movement command: headlights_on
#
# User says "turn on the headlights"
# Expected flow:
#   Orchestrator → governed_execute("headlights_on", "{}", "{}") →
#   Governance: approved (non-movement) →
#   Act agent → iot_client.send_tool_command("headlights_on", {}) →
#   IoT: publish_command({"action": "headlights_on"}) →
#   Result bubbles back up through all layers
# ---------------------------------------------------------------------------

class TestE2ESimpleCommand:
    """End-to-end: headlights_on flows through all layers to IoT publish."""

    @patch.object(iot_client, "publish_command")
    def test_headlights_on_reaches_iot(self, mock_publish):
        """Verify that a headlights_on command reaches iot_client.publish_command."""
        mock_publish.return_value = {}

        # Wire governance to use the real execute_physical_action,
        # which now dispatches directly to iot_client.send_tool_command.
        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="headlights_on",
                parameters="{}",
                context="{}",
                robot_id="zumi",
            )

            # Verify the full chain executed
            assert result["status"] == "ok"
            assert result["action"] == "headlights_on"
            assert result["governance"]["approved"] is True
            assert result["execution_result"] is not None

            # IoT publish was called with the correct payload
            mock_publish.assert_called_once_with({"action": "headlights_on"})

        finally:
            governance_agent._act_agent_ref = None

    @patch.object(iot_client, "publish_command")
    def test_headlights_on_mqtt_payload(self, mock_publish):
        """Verify the exact MQTT payload sent for headlights_on."""
        mock_publish.return_value = {}

        # Bypass the act agent's Strands Agent — call send_tool_command directly
        result = iot_client.send_tool_command("headlights_on", {})

        mock_publish.assert_called_once_with({"action": "headlights_on"})
        assert result == {"status": "ok", "action": "headlights_on"}


# ---------------------------------------------------------------------------
# 2. Movement command: drive_forward with governance clamping
#
# Expected flow:
#   governed_execute("drive_forward", '{"speed": 80, "duration": 1.0}',
#                    '{"vision_guided": true}') →
#   Governance: approved, speed clamped 80→60 (vision-guided max) →
#   Act agent → iot_client.send_tool_command("drive_forward",
#                                            {"speed": 60, "duration": 1.0}) →
#   IoT: publish_command({"action": "forward", "speed": 60, "duration": 1.0})
# ---------------------------------------------------------------------------

class TestE2EMovementWithClamping:
    """End-to-end: movement command with governance safety clamping."""

    @patch.object(iot_client, "publish_command")
    def test_vision_guided_speed_clamped(self, mock_publish):
        """Speed 80 should be clamped to 60 during vision-guided nav."""
        mock_publish.return_value = {}

        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="drive_forward",
                parameters='{"speed": 80, "duration": 1.0}',
                context='{"vision_guided": true, "cumulative_distance_cm": 0}',
                robot_id="zumi",
            )

            assert result["status"] == "ok"
            assert result["governance"]["approved"] is True
            # Speed should have been clamped
            assert result["governance"]["modified_parameters"] is not None
            assert result["governance"]["modified_parameters"]["speed"] == 60
            assert any("Speed clamped" in n for n in result["governance"]["safety_notes"])

            # IoT publish was called with the CLAMPED speed (60, not 80)
            mock_publish.assert_called_once_with({
                "action": "forward", "speed": 60, "duration": 1.0
            })

        finally:
            governance_agent._act_agent_ref = None

    @patch.object(iot_client, "publish_command")
    def test_cumulative_distance_tracked(self, mock_publish):
        """Cumulative distance should increase after a movement command."""
        mock_publish.return_value = {}

        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="move_centimeters",
                parameters='{"distance": 15}',
                context='{"cumulative_distance_cm": 10}',
                robot_id="zumi",
            )

            assert result["status"] == "ok"
            # 10 (existing) + 15 (this move) = 25
            assert result["cumulative_distance_cm"] == 25.0

        finally:
            governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# 3. Emergency stop bypasses governance
# ---------------------------------------------------------------------------

class TestE2EEmergencyStop:
    """End-to-end: emergency stop always executes immediately."""

    @patch.object(iot_client, "publish_command")
    def test_emergency_stop_even_at_high_cumulative(self, mock_publish):
        """Emergency stop should work even when cumulative distance > 100cm."""
        mock_publish.return_value = {}

        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="emergency_stop",
                parameters="{}",
                context='{"cumulative_distance_cm": 200}',
                robot_id="zumi",
            )

            assert result["status"] == "ok"
            assert result["governance"]["approved"] is True
            assert result["governance"]["modified_parameters"] is None
            # Cumulative distance should NOT increase
            assert result["cumulative_distance_cm"] == 200.0
            # IoT publish was called with the stop command
            mock_publish.assert_called_once_with({"action": "stop"})

        finally:
            governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# 4. Governance blocks unsafe action
# ---------------------------------------------------------------------------

class TestE2EGovernanceBlock:
    """End-to-end: governance blocks movement when cumulative > 100cm."""

    @patch.object(iot_client, "publish_command")
    def test_movement_blocked_at_high_cumulative(self, mock_publish):
        """Movement should be blocked when cumulative distance exceeds 100cm."""
        mock_act_agent = MagicMock()
        act_agent._act_agent = mock_act_agent

        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="drive_forward",
                parameters='{"speed": 40, "duration": 1.0}',
                context='{"cumulative_distance_cm": 105}',
                robot_id="zumi",
            )

            assert result["status"] == "blocked"
            assert result["governance"]["approved"] is False
            assert "Cumulative distance" in result["governance"]["reason"]
            assert result["execution_result"] is None

            # IoT should NOT have been called
            mock_publish.assert_not_called()
            # Act agent should NOT have been called
            mock_act_agent.assert_not_called()

        finally:
            act_agent._act_agent = None
            governance_agent._act_agent_ref = None

    @patch.object(iot_client, "publish_command")
    def test_unknown_action_blocked(self, mock_publish):
        """Unknown actions should be blocked by governance."""
        mock_act_agent = MagicMock()
        act_agent._act_agent = mock_act_agent

        set_act_agent(execute_physical_action)

        try:
            result = governed_execute(
                action="self_destruct",
                parameters="{}",
                context="{}",
                robot_id="zumi",
            )

            assert result["status"] == "blocked"
            assert result["governance"]["approved"] is False
            assert "Unknown action" in result["governance"]["reason"]
            mock_publish.assert_not_called()
            mock_act_agent.assert_not_called()

        finally:
            act_agent._act_agent = None
            governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# 5. Multi-step sequence: turn + move + verify distance tracking
# ---------------------------------------------------------------------------

class TestE2EMultiStepSequence:
    """End-to-end: multi-step sequence tracks cumulative distance."""

    @patch.object(iot_client, "publish_command")
    def test_turn_then_move_cumulative_distance(self, mock_publish):
        """A turn followed by a move should accumulate distance correctly."""
        mock_publish.return_value = {}

        set_act_agent(execute_physical_action)

        try:
            # Step 1: Turn left (estimated 10cm)
            r1 = governed_execute(
                action="turn_left",
                parameters='{"angle": 15}',
                context='{"cumulative_distance_cm": 0}',
                robot_id="zumi",
            )
            assert r1["status"] == "ok"
            assert r1["cumulative_distance_cm"] == 10.0  # turn estimate

            # Step 2: Move forward 15cm (pass updated cumulative)
            r2 = governed_execute(
                action="move_centimeters",
                parameters='{"distance": 15}',
                context='{"cumulative_distance_cm": 10}',
                robot_id="zumi",
            )
            assert r2["status"] == "ok"
            assert r2["cumulative_distance_cm"] == 25.0  # 10 + 15

            # Step 3: Another move of 20cm
            r3 = governed_execute(
                action="move_centimeters",
                parameters='{"distance": 20}',
                context='{"cumulative_distance_cm": 25}',
                robot_id="zumi",
            )
            assert r3["status"] == "ok"
            assert r3["cumulative_distance_cm"] == 45.0  # 25 + 20

            # IoT publish was called 3 times
            assert mock_publish.call_count == 3

        finally:
            governance_agent._act_agent_ref = None


# ---------------------------------------------------------------------------
# 6. API response shape validation
# ---------------------------------------------------------------------------

class TestE2EResponseShape:
    """Verify the API response shape matches ChatResponse at every layer."""

    @patch("orchestrator.get_profile")
    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    def test_orchestrator_chat_response_shape(
        self, mock_perc, mock_act, mock_gov, mock_set, mock_agent_cls, mock_get_profile
    ):
        """Orchestrator.chat() must return {text, image_url, steps}."""
        _profile = MagicMock()
        _profile.robot_id = "zumi"
        _profile.display_name = "Zumi"
        _profile.system_prompt_fragment = "test fragment"
        mock_get_profile.return_value = _profile

        mock_agent = MagicMock()
        mock_agent.return_value = "I turned on the headlights!"
        mock_agent_cls.return_value = mock_agent

        configs = _make_configs()
        orch = Orchestrator(configs)
        result = orch.chat("turn on the headlights")

        # Required keys
        assert "text" in result
        assert "image_url" in result
        assert "steps" in result

        # Types
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0
        assert result["image_url"] is None or isinstance(result["image_url"], str)
        assert isinstance(result["steps"], list)

        # Each step has required keys
        for step in result["steps"]:
            assert "type" in step
            assert step["type"] in ("reasoning", "tool_call", "tool_result")
            assert "layer" in step
            assert step["layer"] in ("perception", "reasoning", "act", "governance")

    @patch("orchestrator.get_profile")
    @patch("orchestrator.Agent")
    @patch("orchestrator.set_act_agent")
    @patch("orchestrator.init_governance_agent")
    @patch("orchestrator.init_act_agent")
    @patch("orchestrator.init_perception_agent")
    def test_orchestrator_reset_clears_state(
        self, mock_perc, mock_act, mock_gov, mock_set, mock_agent_cls, mock_get_profile
    ):
        """Reset should clear conversation and cumulative distance."""
        _profile = MagicMock()
        _profile.robot_id = "zumi"
        _profile.display_name = "Zumi"
        _profile.system_prompt_fragment = "test fragment"
        mock_get_profile.return_value = _profile

        mock_agent = MagicMock()
        mock_agent.return_value = "Done"
        mock_agent_cls.return_value = mock_agent

        configs = _make_configs()
        orch = Orchestrator(configs)
        orch.chat("hello")
        orch._cumulative_distance_cm = 50.0

        orch.reset()

        assert orch._conversation == []
        assert orch._cumulative_distance_cm == 0.0
        assert orch._movement_warned is False


# ---------------------------------------------------------------------------
# 7. FEEDBACK GAP: Movement commands lack device acknowledgment
#
# This test documents the current limitation and shows what validation
# WOULD look like if the device sent back an ack after executing a
# movement command.
# ---------------------------------------------------------------------------

class TestFeedbackGap:
    """Document and test the feedback gap for movement commands.

    CURRENT STATE:
    - send_tool_command("drive_forward", {...}) publishes MQTT and returns
      {"status": "ok"} immediately — this only confirms the MQTT publish
      succeeded, NOT that the robot moved.
    - The device-side zumi_iot.py executes zumi.forward() but does NOT
      publish any acknowledgment back on the telemetry topic.
    - Sensor reads (read_sensors, read_battery, etc.) DO publish results
      back, so we know those work.

    WHAT'S MISSING:
    - After executing a movement command, the device should publish an ack
      like: {"type": "command_ack", "action": "forward", "status": "ok",
             "gyro_after": {...}, "duration_actual": 1.0}
    - The chatbot backend should wait for this ack (with timeout) before
      returning "ok" to the orchestrator.
    - This would let the governance layer verify that the robot actually
      moved and by how much (using gyro delta).

    WORKAROUND:
    - For now, the orchestrator uses perceive() (take photo + analyze)
      after each movement to visually verify progress. This is the
      "re-perceive after each move" pattern in the design doc.
    - This is slower but more robust than gyro-only feedback.
    """

    @patch.object(iot_client, "publish_command")
    def test_drive_forward_returns_ok_without_device_ack(self, mock_publish):
        """drive_forward returns 'ok' based on MQTT publish, not device execution."""
        mock_publish.return_value = {}

        result = iot_client.send_tool_command(
            "drive_forward", {"speed": 40, "duration": 1.0}
        )

        # This "ok" only means MQTT publish succeeded
        assert result["status"] == "ok"
        assert result["action"] == "forward"

        # There is NO field like "device_ack" or "gyro_after" or "actual_distance"
        assert "device_ack" not in result
        assert "gyro_after" not in result
        assert "actual_distance_cm" not in result

    @patch.object(iot_client, "publish_command")
    def test_sensor_reads_do_publish_back(self, mock_publish):
        """Sensor reads publish results back — movement commands should too."""
        mock_publish.return_value = {}

        result = iot_client.send_tool_command("read_sensors", {})

        # Sensor reads at least acknowledge the command was sent
        assert result["status"] == "requested"
        assert "note" in result

        # The device-side code publishes sensor data back on telemetry topic.
        # Movement commands should do the same with execution confirmation.

    @patch.object(iot_client, "publish_command")
    def test_move_centimeters_no_actual_distance_feedback(self, mock_publish):
        """move_centimeters returns ok but doesn't report actual distance moved."""
        mock_publish.return_value = {}

        result = iot_client.send_tool_command(
            "move_centimeters", {"distance": 15.0}
        )

        assert result["status"] == "ok"
        assert result["action"] == "move_centimeters"
        # No feedback about actual distance achieved
        assert "actual_distance_cm" not in result

    @patch.object(iot_client, "publish_command")
    def test_turn_left_no_actual_angle_feedback(self, mock_publish):
        """turn_left returns ok but doesn't report actual angle turned."""
        mock_publish.return_value = {}

        result = iot_client.send_tool_command("turn_left", {"angle": 90})

        assert result["status"] == "ok"
        assert result["action"] == "turn_left"
        # No feedback about actual angle achieved
        assert "actual_angle" not in result


# ---------------------------------------------------------------------------
# 8. Full chain: IoT payload format preservation
#
# Verify that the MQTT payloads sent to the device match the format
# that zumi_iot.py expects, ensuring device compatibility.
# ---------------------------------------------------------------------------

class TestE2EIoTPayloadFormat:
    """Verify MQTT payloads match the device-side command handler format."""

    @patch.object(iot_client, "publish_command")
    def test_drive_forward_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("drive_forward", {"speed": 50, "duration": 2.0})
        mock_publish.assert_called_once_with({
            "action": "forward", "speed": 50, "duration": 2.0
        })

    @patch.object(iot_client, "publish_command")
    def test_turn_left_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("turn_left", {"angle": 45})
        mock_publish.assert_called_once_with({"action": "turn_left", "angle": 45})

    @patch.object(iot_client, "publish_command")
    def test_emergency_stop_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("emergency_stop", {})
        mock_publish.assert_called_once_with({"action": "stop"})

    @patch.object(iot_client, "publish_command")
    def test_move_centimeters_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 15.0})
        mock_publish.assert_called_once_with({
            "action": "move_centimeters", "distance": 15.0
        })

    @patch.object(iot_client, "publish_command")
    def test_move_centimeters_with_angle_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command(
            "move_centimeters", {"distance": 10.0, "angle": 90}
        )
        mock_publish.assert_called_once_with({
            "action": "move_centimeters", "distance": 10.0, "angle": 90
        })

    @patch.object(iot_client, "publish_command")
    def test_play_note_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("play_note", {"note": 25, "duration_ms": 500})
        mock_publish.assert_called_once_with({
            "action": "play_note", "note": 25, "duration_ms": 500
        })

    @patch.object(iot_client, "publish_command")
    def test_display_text_payload(self, mock_publish):
        mock_publish.return_value = {}
        iot_client.send_tool_command("display_text", {"message": "Hello!"})
        mock_publish.assert_called_once_with({"action": "say", "message": "Hello!"})
