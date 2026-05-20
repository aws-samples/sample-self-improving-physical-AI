"""
Unit tests for lcd_display.py grip overlay methods.

Tests show_grip_frame and show_grip_status by verifying method calls
and parameters — not visual output (no SPI display on test machine).

Feature: xgo2-ball-grip-calibration, Task 10.3
"""
from __future__ import annotations

import os
import sys
import time
from unittest import mock

import numpy as np
import pytest

# Make lcd_display importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lcd_display import (
    CROSSHAIR_COLOR,
    CROSSHAIR_SIZE,
    CROSSHAIR_THICKNESS,
    DEPTH_THUMB_HEIGHT,
    DEPTH_THUMB_WIDTH,
    GRIP_TEXT_COLOR,
    LCD_HEIGHT,
    LCD_WIDTH,
    LCDDisplay,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lcd_with_mock_display():
    """Create an LCDDisplay with a mocked SPI display backend.

    Bypasses the real LCD_2inch hardware init so tests run anywhere.
    Returns (lcd, mock_display).
    """
    lcd = LCDDisplay.__new__(LCDDisplay)
    lcd._display = mock.MagicMock()
    lcd._bedrock_text = None
    lcd._bedrock_expire = 0.0
    import threading
    lcd._lock = threading.Lock()
    return lcd, lcd._display


def _make_frame(width=320, height=240):
    """Create a dummy BGR frame."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _make_detection(top=0.3, left=0.2, bottom=0.7, right=0.6,
                    label="red_ball", confidence=0.95):
    """Create a detection dict matching the DetectionResult interface."""
    return {
        "class_label": label,
        "confidence": confidence,
        "bounding_box": {
            "top": top,
            "left": left,
            "bottom": bottom,
            "right": right,
        },
    }


def _make_mock_cv2():
    """Create a mock cv2 module with the functions used by lcd_display."""
    mock_cv2 = mock.MagicMock()

    # cvtColor: return an RGB array of the same shape
    def _cvtColor(frame, code):
        return frame.copy()
    mock_cv2.cvtColor.side_effect = _cvtColor
    mock_cv2.COLOR_BGR2RGB = 4

    # flip: return the same array (horizontal flip is cosmetic)
    def _flip(frame, code):
        return frame.copy()
    mock_cv2.flip.side_effect = _flip

    # putText: no-op (draws on frame in place)
    mock_cv2.putText = mock.MagicMock()

    # rectangle: no-op
    mock_cv2.rectangle = mock.MagicMock()

    # line: no-op
    mock_cv2.line = mock.MagicMock()

    # addWeighted: no-op
    mock_cv2.addWeighted = mock.MagicMock()

    # resize: return array of requested size
    def _resize(arr, size):
        w, h = size
        if arr.ndim == 2:
            return np.zeros((h, w), dtype=arr.dtype)
        return np.zeros((h, w, arr.shape[2]), dtype=arr.dtype)
    mock_cv2.resize.side_effect = _resize

    # applyColorMap: return a 3-channel BGR array
    def _applyColorMap(img, colormap):
        h, w = img.shape[:2]
        return np.zeros((h, w, 3), dtype=np.uint8)
    mock_cv2.applyColorMap.side_effect = _applyColorMap
    mock_cv2.COLORMAP_JET = 2

    # Font constants
    mock_cv2.FONT_HERSHEY_SIMPLEX = 0
    mock_cv2.LINE_AA = 16

    return mock_cv2


# ---------------------------------------------------------------------------
# Tests: show_grip_frame
# ---------------------------------------------------------------------------


class TestShowGripFrame:
    """Tests for LCDDisplay.show_grip_frame."""

    def test_calls_show_image_on_display(self):
        """show_grip_frame should push an image to the display."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        frame = _make_frame()
        detections = [_make_detection()]

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=frame,
                detections=detections,
                target_position=(0.5, 0.5),
                error_magnitude=12.3,
                convergence_state="seeking",
            )

        mock_disp.ShowImage.assert_called_once()

    def test_no_op_when_display_is_none(self):
        """show_grip_frame should silently return when display is None."""
        lcd, _ = _make_lcd_with_mock_display()
        lcd._display = None

        # Should not raise — no cv2 mock needed since it returns early
        lcd.show_grip_frame(
            frame=_make_frame(),
            detections=[],
            target_position=(0.5, 0.5),
            error_magnitude=0.0,
            convergence_state="seeking",
        )

    def test_renders_with_empty_detections(self):
        """show_grip_frame should work with no detections."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[],
                target_position=(0.5, 0.5),
                error_magnitude=5.0,
                convergence_state="converging",
            )

        mock_disp.ShowImage.assert_called_once()

    def test_renders_with_depth_thumbnail(self):
        """show_grip_frame should render depth thumbnail when provided."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        depth = np.random.rand(64, 64).astype(np.float32)

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[_make_detection()],
                target_position=(0.3, 0.7),
                error_magnitude=8.5,
                convergence_state="seeking",
                depth_thumbnail=depth,
            )

        mock_disp.ShowImage.assert_called_once()

    def test_renders_without_depth_thumbnail(self):
        """show_grip_frame should work when depth_thumbnail is None."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[_make_detection()],
                target_position=(0.5, 0.5),
                error_magnitude=3.0,
                convergence_state="confirmed",
                depth_thumbnail=None,
            )

        mock_disp.ShowImage.assert_called_once()

    def test_pil_image_resized_to_lcd_dimensions(self):
        """The PIL image pushed to the display should be 320x240."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=_make_frame(640, 480),
                detections=[],
                target_position=(0.5, 0.5),
                error_magnitude=0.0,
                convergence_state="seeking",
            )

        call_args = mock_disp.ShowImage.call_args
        pil_img = call_args[0][0]
        assert pil_img.size == (LCD_WIDTH, LCD_HEIGHT)

    def test_exception_in_rendering_does_not_propagate(self):
        """Rendering errors should be caught, not propagated."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        mock_disp.ShowImage.side_effect = RuntimeError("SPI failure")

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            # Should not raise
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[],
                target_position=(0.5, 0.5),
                error_magnitude=0.0,
                convergence_state="seeking",
            )

    def test_target_position_boundary_values(self):
        """show_grip_frame should handle target at frame edges."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            for pos in [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)]:
                lcd.show_grip_frame(
                    frame=_make_frame(),
                    detections=[],
                    target_position=pos,
                    error_magnitude=0.0,
                    convergence_state="seeking",
                )

        assert mock_disp.ShowImage.call_count == 4

    def test_multiple_detections_rendered(self):
        """show_grip_frame should handle multiple detections."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        detections = [
            _make_detection(0.1, 0.1, 0.3, 0.3, "red_ball", 0.9),
            _make_detection(0.5, 0.5, 0.8, 0.8, "red_ball", 0.7),
        ]

        with mock.patch.dict("sys.modules", {"cv2": _make_mock_cv2()}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=detections,
                target_position=(0.5, 0.5),
                error_magnitude=20.0,
                convergence_state="seeking",
            )

        mock_disp.ShowImage.assert_called_once()

    def test_crosshair_drawn_at_target(self):
        """show_grip_frame should call cv2.line for the crosshair."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[],
                target_position=(0.5, 0.5),
                error_magnitude=0.0,
                convergence_state="confirmed",
            )

        # Crosshair draws 2 lines (horizontal + vertical)
        assert mock_cv2.line.call_count == 2

    def test_error_and_state_text_drawn(self):
        """show_grip_frame should draw error magnitude and state text."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            lcd.show_grip_frame(
                frame=_make_frame(),
                detections=[],
                target_position=(0.5, 0.5),
                error_magnitude=12.3,
                convergence_state="seeking",
            )

        # putText called at least twice: error text + state text
        assert mock_cv2.putText.call_count >= 2
        # Verify the error text content
        first_call_text = mock_cv2.putText.call_args_list[0][0][1]
        assert "12.3" in first_call_text
        second_call_text = mock_cv2.putText.call_args_list[1][0][1]
        assert second_call_text == "seeking"


# ---------------------------------------------------------------------------
# Tests: show_grip_status
# ---------------------------------------------------------------------------


class TestShowGripStatus:
    """Tests for LCDDisplay.show_grip_status."""

    def test_calls_show_image_on_display(self):
        """show_grip_status should push an image to the display."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch("time.sleep"):
            lcd.show_grip_status("Grip Success", duration=0.0)

        mock_disp.ShowImage.assert_called_once()

    def test_no_op_when_display_is_none(self):
        """show_grip_status should silently return when display is None."""
        lcd, _ = _make_lcd_with_mock_display()
        lcd._display = None

        # Should not raise
        lcd.show_grip_status("Ball Lost", duration=0.0)

    def test_pil_image_is_lcd_dimensions(self):
        """The PIL image pushed to the display should be 320x240."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        with mock.patch("time.sleep"):
            lcd.show_grip_status("Timeout", duration=0.0)

        call_args = mock_disp.ShowImage.call_args
        pil_img = call_args[0][0]
        assert pil_img.size == (LCD_WIDTH, LCD_HEIGHT)

    def test_exception_in_rendering_does_not_propagate(self):
        """Rendering errors should be caught, not propagated."""
        lcd, mock_disp = _make_lcd_with_mock_display()
        mock_disp.ShowImage.side_effect = RuntimeError("SPI failure")

        # Should not raise
        lcd.show_grip_status("Grip Success", duration=0.0)

    def test_various_status_texts(self):
        """show_grip_status should handle all expected status strings."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        statuses = [
            "Grip Success",
            "GRIPPING",
            "Ball Lost",
            "Timeout",
            "Tilt Detected",
            "Stopped",
        ]
        with mock.patch("time.sleep"):
            for status in statuses:
                lcd.show_grip_status(status, duration=0.0)

        assert mock_disp.ShowImage.call_count == len(statuses)

    @mock.patch("time.sleep")
    def test_sleeps_for_specified_duration(self, mock_sleep):
        """show_grip_status should sleep for the given duration."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        lcd.show_grip_status("Grip Success", duration=3.0)

        mock_sleep.assert_called_once_with(3.0)

    @mock.patch("time.sleep")
    def test_default_duration_is_three_seconds(self, mock_sleep):
        """show_grip_status default duration should be 3.0 seconds."""
        lcd, mock_disp = _make_lcd_with_mock_display()

        lcd.show_grip_status("Ball Lost")

        mock_sleep.assert_called_once_with(3.0)


# ---------------------------------------------------------------------------
# Tests: _draw_crosshair helper
# ---------------------------------------------------------------------------


class TestDrawCrosshair:
    """Tests for the static _draw_crosshair helper."""

    def test_draws_two_lines(self):
        """_draw_crosshair should draw horizontal and vertical lines."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            LCDDisplay._draw_crosshair(render, 160, 120)

        assert mock_cv2.line.call_count == 2

    def test_crosshair_at_origin(self):
        """_draw_crosshair should handle (0, 0) without error."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            LCDDisplay._draw_crosshair(render, 0, 0)

        assert mock_cv2.line.call_count == 2

    def test_crosshair_at_max_corner(self):
        """_draw_crosshair should handle bottom-right corner."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            LCDDisplay._draw_crosshair(render, 319, 239)

        assert mock_cv2.line.call_count == 2

    def test_crosshair_uses_correct_color(self):
        """_draw_crosshair should use CROSSHAIR_COLOR."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            LCDDisplay._draw_crosshair(render, 160, 120)

        # Both line calls should use CROSSHAIR_COLOR
        for call in mock_cv2.line.call_args_list:
            assert call[0][3] == CROSSHAIR_COLOR


# ---------------------------------------------------------------------------
# Tests: _draw_depth_thumbnail helper
# ---------------------------------------------------------------------------


class TestDrawDepthThumbnail:
    """Tests for the static _draw_depth_thumbnail helper."""

    def test_calls_resize_and_colormap(self):
        """_draw_depth_thumbnail should resize and apply colour map."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        depth = np.random.rand(64, 64).astype(np.float32)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            LCDDisplay._draw_depth_thumbnail(render, depth)

        mock_cv2.resize.assert_called_once()
        mock_cv2.applyColorMap.assert_called_once()
        mock_cv2.cvtColor.assert_called_once()

    def test_handles_small_depth_map(self):
        """_draw_depth_thumbnail should handle a tiny depth map."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        depth = np.array([[0.0, 1.0], [0.5, 0.8]], dtype=np.float32)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # Should not raise
            LCDDisplay._draw_depth_thumbnail(render, depth)

        mock_cv2.resize.assert_called_once()

    def test_handles_large_depth_map(self):
        """_draw_depth_thumbnail should resize a large depth map."""
        render = np.zeros((240, 320, 3), dtype=np.uint8)
        depth = np.random.rand(256, 256).astype(np.float32)
        mock_cv2 = _make_mock_cv2()

        with mock.patch.dict("sys.modules", {"cv2": mock_cv2}):
            # Should not raise
            LCDDisplay._draw_depth_thumbnail(render, depth)

        mock_cv2.resize.assert_called_once()
