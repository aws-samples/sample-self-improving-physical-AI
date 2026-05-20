"""Unit tests for advanced movement dispatch in iot_client.py (Task 4.2)."""

import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock boto3 and config before importing iot_client
sys.modules["boto3"] = MagicMock()
sys.modules["config"] = MagicMock()

import iot_client


class TestDriveCircle(unittest.TestCase):
    """Tests for drive_circle dispatch — Req 6.1, 6.2."""

    @patch.object(iot_client, "publish_command")
    def test_circle_left_default(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_circle", {"direction": "left"})
        mock_pub.assert_called_once_with({"action": "circle_left", "speed": 30, "step": 2})
        self.assertEqual(result, {"status": "ok", "action": "circle_left"})

    @patch.object(iot_client, "publish_command")
    def test_circle_right(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_circle", {"direction": "right", "speed": 50, "step": 5})
        mock_pub.assert_called_once_with({"action": "circle_right", "speed": 50, "step": 5})
        self.assertEqual(result, {"status": "ok", "action": "circle_right"})

    @patch.object(iot_client, "publish_command")
    def test_circle_defaults_to_left(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_circle", {})
        mock_pub.assert_called_once_with({"action": "circle_left", "speed": 30, "step": 2})
        self.assertEqual(result["action"], "circle_left")

    @patch.object(iot_client, "publish_command")
    def test_circle_params_cast_to_int(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("drive_circle", {"direction": "right", "speed": 40.7, "step": 3.9})
        mock_pub.assert_called_once_with({"action": "circle_right", "speed": 40, "step": 3})


class TestDriveSquare(unittest.TestCase):
    """Tests for drive_square dispatch — Req 6.3, 6.4."""

    @patch.object(iot_client, "publish_command")
    def test_square_left_default(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_square", {"direction": "left"})
        mock_pub.assert_called_once_with({"action": "square_left", "speed": 40, "seconds": 1.0})
        self.assertEqual(result, {"status": "ok", "action": "square_left"})

    @patch.object(iot_client, "publish_command")
    def test_square_right(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_square", {"direction": "right", "speed": 60, "seconds": 2.5})
        mock_pub.assert_called_once_with({"action": "square_right", "speed": 60, "seconds": 2.5})
        self.assertEqual(result, {"status": "ok", "action": "square_right"})

    @patch.object(iot_client, "publish_command")
    def test_square_seconds_cast_to_float(self, mock_pub):
        mock_pub.return_value = {}
        iot_client.send_tool_command("drive_square", {"direction": "left", "seconds": 2})
        mock_pub.assert_called_once_with({"action": "square_left", "speed": 40, "seconds": 2.0})


class TestDriveFigure8(unittest.TestCase):
    """Tests for drive_figure_8 dispatch — Req 6.5."""

    @patch.object(iot_client, "publish_command")
    def test_figure_8_default(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_figure_8", {})
        mock_pub.assert_called_once_with({"action": "figure_8", "speed": 30, "step": 3})
        self.assertEqual(result, {"status": "ok", "action": "figure_8"})

    @patch.object(iot_client, "publish_command")
    def test_figure_8_custom(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("drive_figure_8", {"speed": 20, "step": 5})
        mock_pub.assert_called_once_with({"action": "figure_8", "speed": 20, "step": 5})
        self.assertEqual(result, {"status": "ok", "action": "figure_8"})


class TestParallelPark(unittest.TestCase):
    """Tests for parallel_park dispatch — Req 6.6."""

    @patch.object(iot_client, "publish_command")
    def test_parallel_park_default(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("parallel_park", {})
        mock_pub.assert_called_once_with({"action": "parallel_park", "speed": 15})
        self.assertEqual(result, {"status": "ok", "action": "parallel_park"})

    @patch.object(iot_client, "publish_command")
    def test_parallel_park_custom_speed(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("parallel_park", {"speed": 25})
        mock_pub.assert_called_once_with({"action": "parallel_park", "speed": 25})
        self.assertEqual(result, {"status": "ok", "action": "parallel_park"})


class TestJTurn(unittest.TestCase):
    """Tests for j_turn dispatch — Req 6.7."""

    @patch.object(iot_client, "publish_command")
    def test_j_turn_default(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("j_turn", {})
        mock_pub.assert_called_once_with({"action": "j_turn", "speed": 80})
        self.assertEqual(result, {"status": "ok", "action": "j_turn"})

    @patch.object(iot_client, "publish_command")
    def test_j_turn_custom_speed(self, mock_pub):
        mock_pub.return_value = {}
        result = iot_client.send_tool_command("j_turn", {"speed": 50})
        mock_pub.assert_called_once_with({"action": "j_turn", "speed": 50})
        self.assertEqual(result, {"status": "ok", "action": "j_turn"})


if __name__ == "__main__":
    unittest.main()
