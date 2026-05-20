"""
Property-based test for P11: Mutual exclusion of grip and navigation sessions.

Feature: xgo2-ball-grip-calibration, Property 11: Mutual exclusion

Generates random sequences of start_grip/stop_grip/start_navigation/stop_navigation
commands, feeds them to the CommandHandler, and verifies that at most one session
(grip or navigation) is active at any point in time.

**Validates: Requirements 12.6**
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import given, settings
from hypothesis import strategies as st

from main import CommandHandler


# ---------------------------------------------------------------------------
# Stateful mock controllers that track active state
# ---------------------------------------------------------------------------

class MockNavigationController:
    """Mock NavigationController whose is_active() reflects start/stop calls."""

    def __init__(self):
        self._active = False
        self._config = {"camera": MagicMock()}

    def is_active(self):
        return self._active

    def start_navigation(self, target_label, **kwargs):
        self._active = True

    def stop_navigation(self):
        self._active = False


class MockGripController:
    """Mock GripCalibrationController whose is_active() reflects start/stop calls."""

    def __init__(self):
        self._active = False

    def is_active(self):
        return self._active

    def start_grip(self, **kwargs):
        self._active = True

    def stop_grip(self):
        self._active = False


# ---------------------------------------------------------------------------
# Command strategy
# ---------------------------------------------------------------------------

command_strategy = st.sampled_from([
    {"action": "start_grip"},
    {"action": "stop_grip"},
    {"action": "navigate_to_target", "target_label": "red_ball"},
    {"action": "stop"},
])


# ---------------------------------------------------------------------------
# P11: Mutual exclusion property test
# ---------------------------------------------------------------------------

# Feature: xgo2-ball-grip-calibration, Property 11: Mutual exclusion
@given(commands=st.lists(command_strategy, min_size=1, max_size=50))
@settings(max_examples=100)
def test_mutual_exclusion_of_grip_and_navigation(commands):
    """**Validates: Requirements 12.6**

    For any sequence of start_grip, stop_grip, navigate_to_target, and stop
    commands issued to the CommandHandler, at most one session (grip or
    navigation) shall be active at any point in time.
    """
    nav = MockNavigationController()
    grip = MockGripController()
    dog = MagicMock()
    dog.read_battery.return_value = 80
    lcd = MagicMock()

    handler = CommandHandler(
        nav_controller=nav,
        lcd_display=lcd,
        dog=dog,
        grip_controller=grip,
    )

    for cmd in commands:
        handler.handle(cmd)

        # After every command, at most one session may be active
        grip_active = grip.is_active()
        nav_active = nav.is_active()

        assert not (grip_active and nav_active), (
            "Mutual exclusion violated: grip_active={}, nav_active={} "
            "after command {}".format(grip_active, nav_active, cmd)
        )


if __name__ == "__main__":
    unittest.main()
