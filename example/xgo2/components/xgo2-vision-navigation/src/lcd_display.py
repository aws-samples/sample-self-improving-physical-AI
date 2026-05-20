"""
LCD display feedback for XGO2 robodog.

Device-side module. Python 3.9 compatible.
Renders camera feed with detection overlays, Bedrock responses,
navigation status, grip calibration overlays, and standby screen
on the 320x240 SPI LCD.

Follows the show_camera.py pattern: BGR->RGB, horizontal flip,
PIL.Image, display.ShowImage().

Requirements: 8.1-8.6, 10.1-10.6
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# LCD dimensions (native resolution)
LCD_WIDTH = 320
LCD_HEIGHT = 240

# Rendering colours (BGR for OpenCV drawing)
BOX_COLOR_BGR = (0, 255, 0)       # Green bounding boxes
TEXT_COLOR_BGR = (255, 255, 255)   # White text
STATUS_COLOR_BGR = (0, 255, 255)  # Yellow status text
OVERLAY_ALPHA = 0.6               # Semi-transparent overlay opacity

# Grip overlay colours (RGB — drawn after BGR->RGB conversion)
CROSSHAIR_COLOR = (255, 0, 0)     # Red crosshair at target position
GRIP_TEXT_COLOR = (0, 255, 255)   # Cyan for error/convergence text
GRIP_BOX_COLOR = (0, 255, 0)     # Green ball bounding box
GRIP_STATUS_BG = (0, 0, 0)       # Black background for status screen
GRIP_STATUS_FG = (255, 255, 255) # White text for status screen

# Crosshair dimensions
CROSSHAIR_SIZE = 15               # Half-length of crosshair arms in pixels
CROSSHAIR_THICKNESS = 2

# Depth thumbnail defaults
DEPTH_THUMB_WIDTH = 80
DEPTH_THUMB_HEIGHT = 60


class LCDDisplay:
    """Visual feedback on the XGO2's 320x240 SPI LCD.

    Renders camera frames with detection bounding boxes, navigation
    status text, Bedrock response overlays, grip calibration overlays,
    and a standby screen.

    All rendering errors are caught and logged — they never propagate
    to the caller so that navigation/grip continues uninterrupted.
    """

    def __init__(self):
        # type: () -> None
        """Initialize the LCD_2inch SPI display.

        If initialization fails the display is set to None and all
        rendering methods become silent no-ops.
        """
        self._display = None  # type: Any
        self._bedrock_text = None  # type: Optional[str]
        self._bedrock_expire = 0.0  # type: float
        self._lock = threading.Lock()

        try:
            import sys
            sys.path.append("/home/pi/cm4-main")
            import LCD_2inch  # type: ignore[import-untyped]

            display = LCD_2inch.LCD_2inch()
            display.Init()
            display.clear()
            self._display = display
            logger.info("LCD display initialized (%dx%d)", LCD_WIDTH, LCD_HEIGHT)
        except Exception as exc:
            logger.error(
                "Failed to initialize LCD display: %s. "
                "Visual feedback will be disabled.",
                exc,
            )
            self._display = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_frame_with_detections(
        self,
        frame,          # type: np.ndarray
        detections,     # type: List[Any]
        status="",      # type: str
    ):
        # type: (...) -> None
        """Render a camera frame with bounding boxes and status text.

        Draws green bounding boxes around each detection with the class
        label and confidence score.  Shows navigation status text in the
        top-left corner.  If a Bedrock response is active (not yet
        expired), draws a semi-transparent overlay at the bottom.

        Follows the show_camera.py pipeline:
        1. Draw overlays on the BGR frame with OpenCV.
        2. Convert BGR -> RGB.
        3. Flip horizontally.
        4. Convert to PIL.Image.
        5. Resize to 320x240.
        6. Push to LCD via display.ShowImage().

        Args:
            frame: BGR numpy array from OpenCV (any resolution).
            detections: List of DetectionResult objects (or dicts with
                ``class_label``, ``confidence``, ``bounding_box``).
            status: Navigation status string shown in the top-left
                corner (e.g. "Searching", "Tracking cup", "Reached!").
        """
        if self._display is None:
            return

        try:
            import cv2  # type: ignore[import-untyped]
            from PIL import Image  # type: ignore[import-untyped]

            # --- Flip FIRST, then draw overlays so text reads correctly ---
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            render = cv2.flip(rgb, 1)
            h, w = render.shape[:2]

            # --- Draw bounding boxes (mirrored coordinates) ---
            for det in detections:
                self._draw_detection(render, det, h, w, mirrored=True)

            # --- Draw status text in top-left corner ---
            if status:
                cv2.putText(
                    render,
                    status,
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    STATUS_COLOR_BGR,
                    2,
                    cv2.LINE_AA,
                )

            # --- Draw Bedrock overlay if active ---
            with self._lock:
                if (
                    self._bedrock_text is not None
                    and time.monotonic() < self._bedrock_expire
                ):
                    self._draw_bedrock_overlay(render, self._bedrock_text)
                else:
                    self._bedrock_text = None

            # --- Convert to PIL and push to LCD ---
            img = Image.fromarray(render)
            img = img.resize((LCD_WIDTH, LCD_HEIGHT))
            self._display.ShowImage(img)

        except Exception:
            logger.warning("Failed to render frame with detections")

    def show_bedrock_response(self, text, duration=5.0):
        # type: (str, float) -> None
        """Schedule a Bedrock response overlay at the bottom of the screen.

        The overlay is drawn on subsequent ``show_frame_with_detections``
        calls until *duration* seconds have elapsed.

        Args:
            text: Bedrock response text to display.
            duration: How long (seconds) to keep the overlay visible.
        """
        with self._lock:
            self._bedrock_text = text
            self._bedrock_expire = time.monotonic() + duration
        logger.debug(
            "Bedrock overlay scheduled for %.1fs: %s",
            duration,
            text[:60],
        )

    def show_standby(self, thing_name, battery):
        # type: (str, int) -> None
        """Show a standby screen with the thing name and battery level.

        Displays white text centered on a black background (Req 8.6).

        Args:
            thing_name: AWS IoT thing name (e.g. "xgo-robodog").
            battery: Battery percentage (0-100).
        """
        if self._display is None:
            return

        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]

            img = Image.new("RGB", (LCD_WIDTH, LCD_HEIGHT), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Use default font (always available)
            try:
                font_large = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
                )
                font_small = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16
                )
            except Exception:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()

            # Thing name — centered
            name_text = thing_name
            name_bbox = draw.textbbox((0, 0), name_text, font=font_large)
            name_w = name_bbox[2] - name_bbox[0]
            name_x = (LCD_WIDTH - name_w) // 2
            name_y = LCD_HEIGHT // 2 - 30
            draw.text(
                (name_x, name_y), name_text, fill=(255, 255, 255),
                font=font_large,
            )

            # Battery level — centered below thing name
            batt_text = "Battery: {}%".format(battery)
            batt_bbox = draw.textbbox((0, 0), batt_text, font=font_small)
            batt_w = batt_bbox[2] - batt_bbox[0]
            batt_x = (LCD_WIDTH - batt_w) // 2
            batt_y = name_y + 40

            # Colour-code battery: green >= 50, yellow >= 20, red < 20
            if battery >= 50:
                batt_color = (0, 255, 0)
            elif battery >= 20:
                batt_color = (255, 255, 0)
            else:
                batt_color = (255, 0, 0)

            draw.text(
                (batt_x, batt_y), batt_text, fill=batt_color,
                font=font_small,
            )

            # "Standby" label at top
            standby_text = "Standby"
            sb_bbox = draw.textbbox((0, 0), standby_text, font=font_small)
            sb_w = sb_bbox[2] - sb_bbox[0]
            sb_x = (LCD_WIDTH - sb_w) // 2
            draw.text(
                (sb_x, 20), standby_text, fill=(128, 128, 128),
                font=font_small,
            )

            self._display.ShowImage(img)

        except Exception:
            logger.warning("Failed to render standby screen")

    def show_grip_frame(
        self,
        frame,                # type: np.ndarray
        detections,           # type: List[Any]
        target_position,      # type: Tuple[float, float]
        error_magnitude,      # type: float
        convergence_state,    # type: str
        depth_thumbnail=None, # type: Optional[np.ndarray]
    ):
        # type: (...) -> None
        """Render a camera frame with grip calibration overlays.

        Draws the camera feed with ball bounding box, a crosshair at
        the target grip position, error magnitude and convergence state
        text, and an optional depth map thumbnail in the bottom-right
        corner.

        Follows the same BGR->RGB->flip->PIL->LCD pipeline as
        ``show_frame_with_detections``.

        Args:
            frame: BGR numpy array from OpenCV (any resolution).
            detections: List of DetectionResult objects (or dicts with
                ``class_label``, ``confidence``, ``bounding_box``).
            target_position: Normalised (x, y) target grip position in
                the camera frame, each in [0.0, 1.0].
            error_magnitude: Current servoing error magnitude (pixels).
            convergence_state: Current state string, e.g. "seeking",
                "converging", "confirmed", "lost".
            depth_thumbnail: Optional 2D numpy depth map array to render
                as a small thumbnail in the bottom-right corner.  Values
                should be in [0.0, 1.0].  Pass None to skip.
        """
        if self._display is None:
            return

        try:
            import cv2  # type: ignore[import-untyped]
            from PIL import Image  # type: ignore[import-untyped]

            # --- BGR -> RGB, then flip horizontally ---
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            render = cv2.flip(rgb, 1)
            h, w = render.shape[:2]

            # --- Draw ball bounding boxes (mirrored) ---
            for det in detections:
                self._draw_detection(render, det, h, w, mirrored=True)

            # --- Draw crosshair at target position ---
            target_x_norm, target_y_norm = target_position
            # Mirror the x coordinate since the frame is flipped
            tx = int((1.0 - target_x_norm) * w)
            ty = int(target_y_norm * h)
            self._draw_crosshair(render, tx, ty)

            # --- Draw error magnitude and convergence state text ---
            error_text = "Err: %.1f" % error_magnitude
            state_text = convergence_state
            cv2.putText(
                render, error_text, (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, GRIP_TEXT_COLOR, 2, cv2.LINE_AA,
            )
            cv2.putText(
                render, state_text, (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, GRIP_TEXT_COLOR, 2, cv2.LINE_AA,
            )

            # --- Draw optional depth thumbnail in bottom-right corner ---
            if depth_thumbnail is not None:
                self._draw_depth_thumbnail(render, depth_thumbnail)

            # --- Convert to PIL and push to LCD ---
            img = Image.fromarray(render)
            img = img.resize((LCD_WIDTH, LCD_HEIGHT))
            self._display.ShowImage(img)

        except Exception:
            logger.warning("Failed to render grip frame")

    def show_grip_status(self, status_text, duration=3.0):
        # type: (str, float) -> None
        """Show a grip status message on a black background.

        Displays the termination reason (e.g. "Grip Success", "Ball
        Lost", "Timeout") or a "GRIPPING" indicator centered on the
        screen for the specified duration.

        Args:
            status_text: Status message to display (e.g. "Grip Success",
                "GRIPPING", "Ball Lost", "Timeout").
            duration: How long (seconds) to keep the message visible.
        """
        if self._display is None:
            return

        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]

            img = Image.new("RGB", (LCD_WIDTH, LCD_HEIGHT), GRIP_STATUS_BG)
            draw = ImageDraw.Draw(img)

            # Load font — fall back to default if DejaVu is unavailable
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
                )
            except Exception:
                font = ImageFont.load_default()

            # Center the status text
            text_bbox = draw.textbbox((0, 0), status_text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            text_x = (LCD_WIDTH - text_w) // 2
            text_y = (LCD_HEIGHT - text_h) // 2

            # Choose colour based on status
            if "success" in status_text.lower():
                text_color = (0, 255, 0)    # Green for success
            elif "gripping" in status_text.lower():
                text_color = (255, 255, 0)  # Yellow for in-progress
            else:
                text_color = (255, 80, 80)  # Red-ish for failure/other

            draw.text(
                (text_x, text_y), status_text, fill=text_color, font=font,
            )

            self._display.ShowImage(img)

            # Hold the status on screen for the requested duration
            time.sleep(duration)

        except Exception:
            logger.warning("Failed to render grip status: %s", status_text)

    def clear(self):
        # type: () -> None
        """Clear the LCD display."""
        if self._display is None:
            return

        try:
            self._display.clear()
            logger.debug("LCD display cleared")
        except Exception:
            logger.warning("Failed to clear LCD display")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_detection(render, det, frame_h, frame_w, mirrored=False):
        # type: (np.ndarray, Any, int, int, bool) -> None
        """Draw a single detection bounding box and label on the frame.

        Args:
            render: RGB numpy array to draw on (modified in place).
            det: DetectionResult object or dict with class_label,
                confidence, bounding_box.
            frame_h: Frame height in pixels.
            frame_w: Frame width in pixels.
            mirrored: If True, mirror the bounding box left/right
                coordinates (frame was horizontally flipped).
        """
        import cv2  # type: ignore[import-untyped]

        # Extract fields — support both objects and dicts
        if hasattr(det, "class_label"):
            label = det.class_label
            confidence = det.confidence
            bbox = det.bounding_box
        else:
            label = det.get("class_label", "unknown")
            confidence = det.get("confidence", 0.0)
            bbox = det.get("bounding_box", {})

        # Convert normalised coordinates to pixel coordinates
        top = int(bbox.get("top", 0.0) * frame_h)
        left = int(bbox.get("left", 0.0) * frame_w)
        bottom = int(bbox.get("bottom", 1.0) * frame_h)
        right = int(bbox.get("right", 1.0) * frame_w)

        # Mirror horizontally if the frame was flipped
        if mirrored:
            left_px = frame_w - right
            right_px = frame_w - left
            left = left_px
            right = right_px

        # Draw bounding box rectangle (use RGB color since frame is already RGB)
        cv2.rectangle(render, (left, top), (right, bottom), BOX_COLOR_BGR, 2)

        # Draw label + confidence above the box
        text = "{} {:.0%}".format(label, confidence)
        text_y = max(top - 8, 15)
        cv2.putText(
            render,
            text,
            (left, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            TEXT_COLOR_BGR,
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _draw_bedrock_overlay(render, text):
        # type: (np.ndarray, str) -> None
        """Draw a semi-transparent black bar at the bottom with white text.

        Args:
            render: BGR numpy array to draw on (modified in place).
            text: Bedrock response text to display.
        """
        import cv2  # type: ignore[import-untyped]

        h, w = render.shape[:2]
        bar_height = 60
        bar_top = h - bar_height

        # Semi-transparent black overlay
        overlay = render.copy()
        cv2.rectangle(overlay, (0, bar_top), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, OVERLAY_ALPHA, render, 1.0 - OVERLAY_ALPHA, 0, render)

        # Wrap text to fit the bar width (rough character limit)
        max_chars = w // 8  # ~8 pixels per character at scale 0.4
        lines = []  # type: List[str]
        remaining = text
        while remaining:
            if len(remaining) <= max_chars:
                lines.append(remaining)
                break
            # Find a space to break at
            split_pos = remaining[:max_chars].rfind(" ")
            if split_pos <= 0:
                split_pos = max_chars
            lines.append(remaining[:split_pos])
            remaining = remaining[split_pos:].lstrip()
            if len(lines) >= 3:
                # Truncate to 3 lines max
                if remaining:
                    lines[-1] = lines[-1][:max_chars - 3] + "..."
                break

        # Draw text lines
        y = bar_top + 18
        for line in lines:
            cv2.putText(
                render,
                line,
                (8, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                TEXT_COLOR_BGR,
                1,
                cv2.LINE_AA,
            )
            y += 18


    @staticmethod
    def _draw_crosshair(render, cx, cy):
        # type: (np.ndarray, int, int) -> None
        """Draw a crosshair marker at the given pixel position.

        Args:
            render: RGB numpy array to draw on (modified in place).
            cx: X pixel coordinate of the crosshair center.
            cy: Y pixel coordinate of the crosshair center.
        """
        import cv2  # type: ignore[import-untyped]

        h, w = render.shape[:2]
        # Clamp to frame bounds
        cx = max(0, min(cx, w - 1))
        cy = max(0, min(cy, h - 1))

        # Horizontal arm
        x1 = max(0, cx - CROSSHAIR_SIZE)
        x2 = min(w - 1, cx + CROSSHAIR_SIZE)
        cv2.line(render, (x1, cy), (x2, cy), CROSSHAIR_COLOR, CROSSHAIR_THICKNESS)

        # Vertical arm
        y1 = max(0, cy - CROSSHAIR_SIZE)
        y2 = min(h - 1, cy + CROSSHAIR_SIZE)
        cv2.line(render, (cx, y1), (cx, y2), CROSSHAIR_COLOR, CROSSHAIR_THICKNESS)

    @staticmethod
    def _draw_depth_thumbnail(render, depth_map):
        # type: (np.ndarray, np.ndarray) -> None
        """Draw a small depth map thumbnail in the bottom-right corner.

        The depth map is colourised (closer = warmer) and composited
        onto the render frame.

        Args:
            render: RGB numpy array to draw on (modified in place).
            depth_map: 2D numpy array with values in [0.0, 1.0].
        """
        import cv2  # type: ignore[import-untyped]

        h, w = render.shape[:2]
        thumb_w = min(DEPTH_THUMB_WIDTH, w // 4)
        thumb_h = min(DEPTH_THUMB_HEIGHT, h // 4)

        # Resize depth map to thumbnail size
        depth_resized = cv2.resize(depth_map.astype(np.float32), (thumb_w, thumb_h))

        # Convert to uint8 and apply a colour map (COLORMAP_JET: blue=far, red=close)
        depth_uint8 = (np.clip(depth_resized, 0.0, 1.0) * 255).astype(np.uint8)
        depth_color = cv2.applyColorMap(depth_uint8, cv2.COLORMAP_JET)
        # applyColorMap returns BGR; convert to RGB to match render
        depth_rgb = cv2.cvtColor(depth_color, cv2.COLOR_BGR2RGB)

        # Place in bottom-right corner with a 4-pixel margin
        margin = 4
        y_start = h - thumb_h - margin
        x_start = w - thumb_w - margin

        if y_start >= 0 and x_start >= 0:
            render[y_start:y_start + thumb_h, x_start:x_start + thumb_w] = depth_rgb
