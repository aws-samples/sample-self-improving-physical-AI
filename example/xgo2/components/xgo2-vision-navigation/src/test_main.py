"""
Unit tests for main.py — CommandHandler grip dispatch and mutual exclusion.

Tests cover:
- Grip command dispatch (start_grip, stop_grip)
- Mutual exclusion between navigation and grip sessions (Req 12.6)
- Existing navigation dispatch still works
- subscribe_to_grip_commands function

Requirements: 12.4-12.6
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, call

import sys
import os

# Ensure the src directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from main import CommandHandler, subscribe_to_grip_commands, GRIP_COMMAND_TOPIC


class TestCommandHandlerGripDispatch(unittest.TestCase):
    """Test that CommandHandler dispatches start_grip and stop_grip commands."""

    def setUp(self):
        # type: () -> None
        self.nav = MagicMock()
        self.nav.is_active.return_value = False
        self.lcd = MagicMock()
        self.dog = MagicMock()
        self.dog.read_battery.return_value = 80
        self.grip = MagicMock()
        self.grip.is_active.return_value = False
        self.handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )

    def test_start_grip_dispatches_to_controller(self):
        """start_grip action calls grip_controller.start_grip()."""
        self.handler.handle({"action": "start_grip"})
        self.grip.start_grip.assert_called_once_with()

    def test_start_grip_with_params(self):
        """start_grip passes optional parameters to grip_controller."""
        self.handler.handle({
            "action": "start_grip",
            "max_iterations": 30,
            "convergence_tolerance": 10,
            "arm_step_limit": 5,
        })
        self.grip.start_grip.assert_called_once_with(
            max_iterations=30,
            convergence_tolerance=10,
            arm_step_limit=5,
        )

    def test_start_grip_partial_params(self):
        """start_grip passes only provided parameters."""
        self.handler.handle({
            "action": "start_grip",
            "max_iterations": 25,
        })
        self.grip.start_grip.assert_called_once_with(max_iterations=25)

    def test_stop_grip_dispatches_to_controller(self):
        """stop_grip action calls grip_controller.stop_grip()."""
        self.handler.handle({"action": "stop_grip"})
        self.grip.stop_grip.assert_called_once()

    def test_stop_grip_shows_standby(self):
        """stop_grip shows the standby screen after stopping."""
        self.handler.handle({"action": "stop_grip"})
        self.grip.stop_grip.assert_called_once()
        self.lcd.show_standby.assert_called_once()

    def test_start_grip_no_controller(self):
        """start_grip is a no-op when grip controller is None."""
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=None,
        )
        # Should not raise
        handler.handle({"action": "start_grip"})

    def test_stop_grip_no_controller(self):
        """stop_grip is a no-op when grip controller is None."""
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=None,
        )
        # Should not raise
        handler.handle({"action": "stop_grip"})


class TestCommandHandlerMutualExclusion(unittest.TestCase):
    """Test mutual exclusion between navigation and grip sessions (Req 12.6)."""

    def setUp(self):
        # type: () -> None
        self.nav = MagicMock()
        self.lcd = MagicMock()
        self.dog = MagicMock()
        self.dog.read_battery.return_value = 80
        self.grip = MagicMock()

    def test_start_grip_rejected_when_navigation_active(self):
        """start_grip is rejected when a navigation session is active."""
        self.nav.is_active.return_value = True
        self.grip.is_active.return_value = False
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({"action": "start_grip"})
        self.grip.start_grip.assert_not_called()

    def test_navigate_rejected_when_grip_active(self):
        """navigate_to_target is rejected when a grip session is active."""
        self.nav.is_active.return_value = False
        self.grip.is_active.return_value = True
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({
            "action": "navigate_to_target",
            "target_label": "red_ball",
        })
        self.nav.start_navigation.assert_not_called()

    def test_start_grip_allowed_when_navigation_inactive(self):
        """start_grip proceeds when navigation is not active."""
        self.nav.is_active.return_value = False
        self.grip.is_active.return_value = False
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({"action": "start_grip"})
        self.grip.start_grip.assert_called_once()

    def test_navigate_allowed_when_grip_inactive(self):
        """navigate_to_target proceeds when grip is not active."""
        self.nav.is_active.return_value = False
        self.grip.is_active.return_value = False
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({
            "action": "navigate_to_target",
            "target_label": "red_ball",
        })
        self.nav.start_navigation.assert_called_once_with("red_ball")

    def test_navigate_allowed_when_grip_controller_is_none(self):
        """navigate_to_target proceeds when grip controller is None."""
        self.nav.is_active.return_value = False
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=None,
        )
        handler.handle({
            "action": "navigate_to_target",
            "target_label": "red_ball",
        })
        self.nav.start_navigation.assert_called_once_with("red_ball")

    def test_stop_grip_always_allowed(self):
        """stop_grip is always allowed regardless of navigation state."""
        self.nav.is_active.return_value = True
        self.grip.is_active.return_value = True
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({"action": "stop_grip"})
        self.grip.stop_grip.assert_called_once()

    def test_stop_navigation_always_allowed(self):
        """stop is always allowed regardless of grip state."""
        self.nav.is_active.return_value = False
        self.grip.is_active.return_value = True
        handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )
        handler.handle({"action": "stop"})
        self.nav.stop_navigation.assert_called_once()


class TestCommandHandlerExistingActions(unittest.TestCase):
    """Verify existing command actions still work with the updated handler."""

    def setUp(self):
        # type: () -> None
        self.nav = MagicMock()
        self.nav.is_active.return_value = False
        self.nav._config = {"camera": MagicMock()}
        self.lcd = MagicMock()
        self.dog = MagicMock()
        self.dog.read_battery.return_value = 80
        self.grip = MagicMock()
        self.grip.is_active.return_value = False
        self.handler = CommandHandler(
            nav_controller=self.nav,
            lcd_display=self.lcd,
            dog=self.dog,
            grip_controller=self.grip,
        )

    def test_navigate_to_target(self):
        """navigate_to_target still dispatches correctly."""
        self.handler.handle({
            "action": "navigate_to_target",
            "target_label": "person",
        })
        self.nav.start_navigation.assert_called_once_with("person")

    def test_stop_navigation(self):
        """stop action still dispatches correctly."""
        self.handler.handle({"action": "stop"})
        self.nav.stop_navigation.assert_called_once()

    def test_arm_command(self):
        """arm action still dispatches correctly."""
        self.handler.handle({"action": "arm", "arm_x": 50, "arm_z": 30})
        self.dog.arm.assert_called_once_with(50, 30)

    def test_claw_command(self):
        """claw action still dispatches correctly."""
        self.handler.handle({"action": "claw", "pos": 128})
        self.dog.claw.assert_called_once_with(128)

    def test_xgo_action_command(self):
        """xgo_action still dispatches correctly."""
        self.handler.handle({"action": "xgo_action", "action_id": 5})
        self.dog.action.assert_called_once_with(5)

    def test_unknown_action(self):
        """Unknown actions are logged but don't raise."""
        # Should not raise
        self.handler.handle({"action": "unknown_action"})

    def test_navigate_missing_target_label(self):
        """navigate_to_target without target_label is ignored."""
        self.handler.handle({"action": "navigate_to_target"})
        self.nav.start_navigation.assert_not_called()


class TestSubscribeToGripCommands(unittest.TestCase):
    """Test the subscribe_to_grip_commands function."""

    def test_subscribes_to_grip_topic(self):
        """subscribe_to_grip_commands subscribes to the grip command topic."""
        ipc_client = MagicMock()
        callback = MagicMock()

        subscribe_to_grip_commands(ipc_client, callback)

        ipc_client.subscribe_to_iot_core.assert_called_once()
        call_kwargs = ipc_client.subscribe_to_iot_core.call_args
        # Check topic name
        assert call_kwargs[1]["topic_name"] == GRIP_COMMAND_TOPIC
        assert call_kwargs[1]["qos"] == "1"

    def test_subscribe_failure_raises(self):
        """subscribe_to_grip_commands raises on IPC failure."""
        ipc_client = MagicMock()
        ipc_client.subscribe_to_iot_core.side_effect = RuntimeError("IPC error")
        callback = MagicMock()

        with self.assertRaises(RuntimeError):
            subscribe_to_grip_commands(ipc_client, callback)


class TestCommandHandlerBackwardCompatibility(unittest.TestCase):
    """Test that CommandHandler works without grip_controller (backward compat)."""

    def test_init_without_grip_controller(self):
        """CommandHandler can be created without grip_controller arg."""
        nav = MagicMock()
        lcd = MagicMock()
        dog = MagicMock()
        dog.read_battery.return_value = 80
        handler = CommandHandler(
            nav_controller=nav,
            lcd_display=lcd,
            dog=dog,
        )
        assert handler._grip is None

    def test_handle_all_actions_without_grip(self):
        """All non-grip actions work when grip_controller is None."""
        nav = MagicMock()
        nav.is_active.return_value = False
        lcd = MagicMock()
        dog = MagicMock()
        dog.read_battery.return_value = 80
        handler = CommandHandler(
            nav_controller=nav,
            lcd_display=lcd,
            dog=dog,
        )
        # These should all work without raising
        handler.handle({"action": "stop"})
        handler.handle({"action": "arm", "arm_x": 0, "arm_z": 0})
        handler.handle({"action": "claw", "pos": 128})
        handler.handle({"action": "xgo_action", "action_id": 1})


if __name__ == "__main__":
    unittest.main()
