"""Unit tests for distance drive dispatch in iot_client.py (Task 5.2)."""

import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock boto3 and config before importing iot_client
sys.modules["boto3"] = MagicMock()
sys.modules["config"] = MagicMock()

import iot_client


class TestMoveInches(unittest.TestCase):
    """Tests for move_inches dispatch — Req 8.3."""

    @patch.object(iot_client, "publish_command")
    def test_default_distance(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_inches", {})
        mock_pub.assert_called_once_with({"action": "move_inches", "distance": 5.0})
        self.assertEqual(result, {"status": "ok", "action": "move_inches"})

    @patch.object(iot_client, "publish_command")
    def test_custom_distance(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_inches", {"distance": 12.0})
        mock_pub.assert_called_once_with({"action": "move_inches", "distance": 12.0})
        self.assertEqual(result, {"status": "ok", "action": "move_inches"})

    @patch.object(iot_client, "publish_command")
    def test_distance_clamped_high(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_inches", {"distance": 50.0})
        mock_pub.assert_called_once_with({"action": "move_inches", "distance": 24.0})

    @patch.object(iot_client, "publish_command")
    def test_distance_clamped_low(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_inches", {"distance": 0.1})
        mock_pub.assert_called_once_with({"action": "move_inches", "distance": 0.5})

    @patch.object(iot_client, "publish_command")
    def test_with_angle(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_inches", {"distance": 6.0, "angle": 90})
        mock_pub.assert_called_once_with({"action": "move_inches", "distance": 6.0, "angle": 90})
        self.assertEqual(result, {"status": "ok", "action": "move_inches"})

    @patch.object(iot_client, "publish_command")
    def test_without_angle_no_angle_in_payload(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_inches", {"distance": 3.0})
        payload = mock_pub.call_args[0][0]
        self.assertNotIn("angle", payload)

    @patch.object(iot_client, "publish_command")
    def test_angle_cast_to_int(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_inches", {"distance": 5.0, "angle": 45.7})
        payload = mock_pub.call_args[0][0]
        self.assertEqual(payload["angle"], 45)

    @patch.object(iot_client, "publish_command")
    def test_distance_cast_to_float(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_inches", {"distance": 10})
        payload = mock_pub.call_args[0][0]
        self.assertIsInstance(payload["distance"], float)
        self.assertEqual(payload["distance"], 10.0)


class TestMoveCentimeters(unittest.TestCase):
    """Tests for move_centimeters dispatch — Req 8.4."""

    @patch.object(iot_client, "publish_command")
    def test_default_distance(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_centimeters", {})
        mock_pub.assert_called_once_with({"action": "move_centimeters", "distance": 10.0})
        self.assertEqual(result, {"status": "ok", "action": "move_centimeters"})

    @patch.object(iot_client, "publish_command")
    def test_custom_distance(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_centimeters", {"distance": 30.0})
        mock_pub.assert_called_once_with({"action": "move_centimeters", "distance": 30.0})
        self.assertEqual(result, {"status": "ok", "action": "move_centimeters"})

    @patch.object(iot_client, "publish_command")
    def test_distance_clamped_high(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 100.0})
        mock_pub.assert_called_once_with({"action": "move_centimeters", "distance": 60.0})

    @patch.object(iot_client, "publish_command")
    def test_distance_clamped_low(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 0.2})
        mock_pub.assert_called_once_with({"action": "move_centimeters", "distance": 1.0})

    @patch.object(iot_client, "publish_command")
    def test_with_angle(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("move_centimeters", {"distance": 20.0, "angle": 180})
        mock_pub.assert_called_once_with({"action": "move_centimeters", "distance": 20.0, "angle": 180})
        self.assertEqual(result, {"status": "ok", "action": "move_centimeters"})

    @patch.object(iot_client, "publish_command")
    def test_without_angle_no_angle_in_payload(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 15.0})
        payload = mock_pub.call_args[0][0]
        self.assertNotIn("angle", payload)

    @patch.object(iot_client, "publish_command")
    def test_angle_cast_to_int(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 10.0, "angle": 270.3})
        payload = mock_pub.call_args[0][0]
        self.assertEqual(payload["angle"], 270)

    @patch.object(iot_client, "publish_command")
    def test_distance_cast_to_float(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("move_centimeters", {"distance": 25})
        payload = mock_pub.call_args[0][0]
        self.assertIsInstance(payload["distance"], float)
        self.assertEqual(payload["distance"], 25.0)


if __name__ == "__main__":
    unittest.main()
