"""Unit tests for basic drive command dispatch in iot_client.py (Task 1.3)."""

import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock boto3 and config before importing iot_client
sys.modules["boto3"] = MagicMock()
sys.modules["config"] = MagicMock()

import iot_client


class TestDriveForward(unittest.TestCase):
    """Tests for drive_forward dispatch."""

    @patch.object(iot_client, "publish_command")
    def test_default_params(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 40, "duration": 1.0})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "forward")
        self.assertNotIn("clamped", result)

    @patch.object(iot_client, "publish_command")
    def test_custom_params(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {"speed": 60, "duration": 2.5})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 60, "duration": 2.5})
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("clamped", result)

    @patch.object(iot_client, "publish_command")
    def test_speed_clamped_high(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {"speed": 150})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 80, "duration": 1.0})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["speed"]["original"], 150)
        self.assertEqual(result["clamped"]["speed"]["clamped"], 80)

    @patch.object(iot_client, "publish_command")
    def test_speed_clamped_low(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {"speed": -5})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 1, "duration": 1.0})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["speed"]["original"], -5)
        self.assertEqual(result["clamped"]["speed"]["clamped"], 1)

    @patch.object(iot_client, "publish_command")
    def test_duration_clamped_high(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {"duration": 10.0})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 40, "duration": 5.0})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["duration"]["original"], 10.0)
        self.assertEqual(result["clamped"]["duration"]["clamped"], 5.0)

    @patch.object(iot_client, "publish_command")
    def test_both_clamped(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_forward", {"speed": 200, "duration": 99.0})
        mock_pub.assert_called_once_with({"action": "forward", "speed": 80, "duration": 5.0})
        self.assertIn("clamped", result)
        self.assertIn("speed", result["clamped"])
        self.assertIn("duration", result["clamped"])


class TestDriveReverse(unittest.TestCase):
    """Tests for drive_reverse dispatch."""

    @patch.object(iot_client, "publish_command")
    def test_default_params(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_reverse", {})
        mock_pub.assert_called_once_with({"action": "reverse", "speed": 40, "duration": 1.0})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "reverse")

    @patch.object(iot_client, "publish_command")
    def test_speed_clamped(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_reverse", {"speed": 100})
        mock_pub.assert_called_once_with({"action": "reverse", "speed": 80, "duration": 1.0})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["speed"]["original"], 100)


class TestTurnLeft(unittest.TestCase):
    """Tests for turn_left dispatch."""

    @patch.object(iot_client, "publish_command")
    def test_default_angle(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_left", {})
        mock_pub.assert_called_once_with({"action": "turn_left", "angle": 90})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "turn_left")
        self.assertNotIn("clamped", result)

    @patch.object(iot_client, "publish_command")
    def test_custom_angle(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_left", {"angle": 45})
        mock_pub.assert_called_once_with({"action": "turn_left", "angle": 45})
        self.assertNotIn("clamped", result)

    @patch.object(iot_client, "publish_command")
    def test_angle_clamped_high(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_left", {"angle": 500})
        mock_pub.assert_called_once_with({"action": "turn_left", "angle": 360})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["angle"]["original"], 500)
        self.assertEqual(result["clamped"]["angle"]["clamped"], 360)

    @patch.object(iot_client, "publish_command")
    def test_angle_clamped_low(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_left", {"angle": 0})
        mock_pub.assert_called_once_with({"action": "turn_left", "angle": 1})
        self.assertIn("clamped", result)
        self.assertEqual(result["clamped"]["angle"]["original"], 0)
        self.assertEqual(result["clamped"]["angle"]["clamped"], 1)


class TestTurnRight(unittest.TestCase):
    """Tests for turn_right dispatch."""

    @patch.object(iot_client, "publish_command")
    def test_default_angle(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_right", {})
        mock_pub.assert_called_once_with({"action": "turn_right", "angle": 90})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "turn_right")

    @patch.object(iot_client, "publish_command")
    def test_angle_clamped(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("turn_right", {"angle": 999})
        mock_pub.assert_called_once_with({"action": "turn_right", "angle": 360})
        self.assertIn("clamped", result)


class TestEmergencyStop(unittest.TestCase):
    """Tests for emergency_stop dispatch."""

    @patch.object(iot_client, "publish_command")
    def test_stop(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("emergency_stop", {})
        mock_pub.assert_called_once_with({"action": "stop"})
        self.assertEqual(result, {"status": "ok", "action": "stop"})


if __name__ == "__main__":
    unittest.main()
