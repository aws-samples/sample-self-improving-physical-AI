"""
Zumi AWS IoT Core App
~~~~~~~~~~~~~~~~~~~~~
Connects a Robolink Zumi robot to AWS IoT Core over MQTT.

- Publishes sensor telemetry on a periodic interval.
- Subscribes to a command topic so Zumi can be driven remotely.

Usage:
    python3 zumi_iot.py              # uses config.json in same directory
    python3 zumi_iot.py --config /path/to/config.json
"""

import json
import os
import sys
import time
import signal
import logging
import argparse
from datetime import datetime, timezone
from threading import Event

# ---------------------------------------------------------------------------
# AWS IoT Device SDK v2
# ---------------------------------------------------------------------------
from awscrt import io, mqtt
from awsiot import mqtt_connection_builder

# ---------------------------------------------------------------------------
# Zumi libraries (available on the Zumi hardware)
# ---------------------------------------------------------------------------
from zumi.zumi import Zumi
from zumi.util.screen import Screen

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("zumi-iot")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
shutdown_event = Event()


# ── Configuration ─────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    """Load and validate the JSON config file."""
    with open(path) as f:
        cfg = json.load(f)
    required = ["endpoint", "thing_name", "cert_dir"]
    for key in required:
        if key not in cfg:
            raise ValueError("Missing required config key: %s" % key)
    # Resolve cert paths relative to the config file directory
    base = os.path.dirname(os.path.abspath(path))
    cert_dir = os.path.join(base, cfg["cert_dir"])
    cfg["_cert_path"] = os.path.join(cert_dir, cfg.get("cert_file", "device-certificate.pem.crt"))
    cfg["_key_path"] = os.path.join(cert_dir, cfg.get("key_file", "private.pem.key"))
    cfg["_ca_path"] = os.path.join(cert_dir, cfg.get("root_ca_file", "AmazonRootCA1.pem"))
    return cfg


# ── MQTT helpers ──────────────────────────────────────────────────────────

def build_connection(cfg: dict) -> mqtt.Connection:
    """Create an MQTT connection to AWS IoT Core using mutual TLS."""
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    connection = mqtt_connection_builder.mtls_from_path(
        endpoint=cfg["endpoint"],
        cert_filepath=cfg["_cert_path"],
        pri_key_filepath=cfg["_key_path"],
        ca_filepath=cfg["_ca_path"],
        client_bootstrap=client_bootstrap,
        client_id=cfg["thing_name"],
        clean_session=False,
        keep_alive_secs=30,
    )
    return connection


# ── Telemetry ─────────────────────────────────────────────────────────────

def collect_telemetry(zumi: Zumi, thing_name: str) -> dict:
    """Read all available Zumi sensors and package as a dict."""
    angles = zumi.update_angles()
    ir = zumi.get_all_IR_data()
    battery = zumi.get_battery_voltage()
    orientation = zumi.get_orientation_message()

    return {
        "thing_name": thing_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "battery_voltage": round(battery, 3),
        "orientation": orientation,
        "gyro": {
            "x": round(angles[0], 2),
            "y": round(angles[1], 2),
            "z": round(angles[2], 2),
        },
        "ir_sensors": {
            "front_right": ir[0],
            "bottom_right": ir[1],
            "back_right": ir[2],
            "bottom_left": ir[3],
            "back_left": ir[4],
            "front_left": ir[5],
        },
    }


# ── Command handler ───────────────────────────────────────────────────────

def handle_command(zumi, screen, connection, cfg, payload, nav_controller=None):
    """Execute a command received from IoT Core.

    For sensor-read commands, publishes the result back on the telemetry topic.
    """
    action = payload.get("action", "").lower()
    thing_name = cfg["thing_name"]
    telemetry_topic = "zumi/%s/telemetry" % thing_name
    log.info("Command received: %s", action)

    try:
        # ── Sensor reads (publish result back) ────────────────────────
        if action == "read_sensors":
            ir = zumi.get_all_IR_data()
            result = {
                "type": "sensor_response",
                "action": action,
                "ir_sensors": {
                    "front_right": ir[0], "bottom_right": ir[1],
                    "back_right": ir[2], "bottom_left": ir[3],
                    "back_left": ir[4], "front_left": ir[5],
                },
            }
            connection.publish(topic=telemetry_topic, payload=json.dumps(result), qos=mqtt.QoS.AT_LEAST_ONCE)

        elif action == "read_battery":
            voltage = zumi.get_battery_voltage()
            result = {
                "type": "sensor_response",
                "action": action,
                "battery_voltage": round(voltage, 3),
            }
            connection.publish(topic=telemetry_topic, payload=json.dumps(result), qos=mqtt.QoS.AT_LEAST_ONCE)

        elif action == "read_orientation":
            orientation = zumi.get_orientation_message()
            result = {
                "type": "sensor_response",
                "action": action,
                "orientation": orientation,
            }
            connection.publish(topic=telemetry_topic, payload=json.dumps(result), qos=mqtt.QoS.AT_LEAST_ONCE)

        elif action == "read_angles":
            angles = zumi.update_angles()
            result = {
                "type": "sensor_response",
                "action": action,
                "gyro": {
                    "x": round(angles[0], 2),
                    "y": round(angles[1], 2),
                    "z": round(angles[2], 2),
                },
            }
            connection.publish(topic=telemetry_topic, payload=json.dumps(result), qos=mqtt.QoS.AT_LEAST_ONCE)

        # ── Drive commands ────────────────────────────────────────────
        elif action == "forward":
            speed = payload.get("speed", 40)
            duration = payload.get("duration", 1.0)
            zumi.forward(speed=speed, duration=duration)

        elif action == "reverse":
            speed = payload.get("speed", 40)
            duration = payload.get("duration", 1.0)
            zumi.reverse(speed=speed, duration=duration)

        elif action == "turn_left":
            angle = payload.get("angle", 90)
            zumi.turn_left(desired_angle=angle)

        elif action == "turn_right":
            angle = payload.get("angle", 90)
            zumi.turn_right(desired_angle=angle)

        elif action == "stop":
            if nav_controller is not None and nav_controller.is_active():
                nav_controller.stop_navigation()
            zumi.stop()

        # ── Advanced Movement ─────────────────────────────────────────
        elif action == "circle_left":
            speed = payload.get("speed", 30)
            step = payload.get("step", 2)
            zumi.circle_left(speed=speed, step=step)

        elif action == "circle_right":
            speed = payload.get("speed", 30)
            step = payload.get("step", 2)
            zumi.circle_right(speed=speed, step=step)

        elif action == "square_left":
            speed = payload.get("speed", 40)
            seconds = payload.get("seconds", 1.0)
            zumi.square_left(speed=speed, seconds=seconds)

        elif action == "square_right":
            speed = payload.get("speed", 40)
            seconds = payload.get("seconds", 1.0)
            zumi.square_right(speed=speed, seconds=seconds)

        elif action == "figure_8":
            speed = payload.get("speed", 30)
            step = payload.get("step", 3)
            zumi.figure_8(speed=speed, step=step)

        elif action == "parallel_park":
            speed = payload.get("speed", 15)
            zumi.parallel_park(speed=speed)

        elif action == "j_turn":
            speed = payload.get("speed", 80)
            zumi.j_turn(speed=speed)

        # ── Distance Drive ────────────────────────────────────────────
        elif action == "move_inches":
            distance = payload.get("distance", 5.0)
            angle = payload.get("angle", None)
            if angle is not None:
                zumi.move_inches(distance, angle)
            else:
                zumi.move_inches(distance)

        elif action == "move_centimeters":
            distance = payload.get("distance", 10.0)
            angle = payload.get("angle", None)
            if angle is not None:
                zumi.move_centimeters(distance, angle)
            else:
                zumi.move_centimeters(distance)

        # ── LEDs ──────────────────────────────────────────────────────
        elif action == "headlights_on":
            zumi.headlights_on()

        elif action == "headlights_off":
            zumi.headlights_off()

        elif action == "all_lights_on":
            zumi.all_lights_on()

        elif action == "all_lights_off":
            zumi.all_lights_off()

        elif action == "hazard_lights_on":
            zumi.hazard_lights_on()

        elif action == "hazard_lights_off":
            zumi.hazard_lights_off()

        elif action == "signal_left_on":
            zumi.signal_left_on()

        elif action == "signal_left_off":
            zumi.signal_left_off()

        elif action == "signal_right_on":
            zumi.signal_right_on()

        elif action == "signal_right_off":
            zumi.signal_right_off()

        elif action == "brake_lights_on":
            zumi.brake_lights_on()

        elif action == "brake_lights_off":
            zumi.brake_lights_off()

        # ── Buzzer ────────────────────────────────────────────────────
        elif action == "play_note":
            note = payload.get("note", 30)
            dur = payload.get("duration_ms", 500)
            zumi.play_note(note, dur)

        # ── Screen ────────────────────────────────────────────────────
        elif action == "say":
            message = str(payload.get("message", ""))
            screen.draw_text_center(message)

        elif action == "happy":
            screen.happy()

        elif action == "sad":
            screen.sad()

        elif action == "angry":
            screen.angry()

        elif action == "hello":
            screen.hello()

        elif action == "sleeping":
            screen.sleeping()

        elif action == "blink":
            screen.blink()

        elif action == "glimmer":
            screen.glimmer()

        elif action == "look_around":
            screen.look_around_open()

        elif action == "clear_screen":
            screen.clear_display()

        # ── Camera ────────────────────────────────────────────────────
        elif action == "take_photo":
            _take_and_ack(screen, connection, telemetry_topic, payload)

        # ── Calibration ───────────────────────────────────────────────
        elif action == "calibrate_gyro":
            zumi.calibrate_gyro()

        elif action == "calibrate_mpu":
            count = payload.get("count", 100)
            zumi.mpu.calibrate_MPU(count=count)

        elif action == "speed_calibration":
            speed = payload.get("speed", 40)
            ir_threshold = payload.get("ir_threshold", 100)
            time_out = payload.get("time_out", 3.0)
            cm_per_brick = payload.get("cm_per_brick", 2.0)
            zumi.speed_calibration(speed=speed, ir_threshold=ir_threshold, time_out=time_out, cm_per_brick=cm_per_brick)

        elif action == "reset_drive":
            zumi.reset_drive()

        elif action == "reset_gyro":
            zumi.reset_gyro()

        elif action == "reset_pid":
            zumi.reset_PID()

        # ── Vision Navigation ─────────────────────────────────────────
        elif action == "navigate_to_target":
            target_label = payload.get("target_label", "")
            if not target_label:
                log.warning("navigate_to_target: missing target_label")
                return

            if nav_controller is None:
                log.warning("Navigation controller not available")
                return

            max_steps = payload.get("max_steps", 50)
            speed = payload.get("speed", 30)
            obstacle_threshold = payload.get("obstacle_threshold", 100)
            confidence_threshold = payload.get("confidence_threshold", 0.5)

            # start_navigation stops any active session internally
            nav_controller.start_navigation(
                target_label=target_label,
                max_steps=max_steps,
                speed=speed,
                obstacle_threshold=obstacle_threshold,
                confidence_threshold=confidence_threshold,
            )

            # Publish acknowledgment
            ack = {
                "type": "navigation_status",
                "status": "started",
                "target_label": target_label,
            }
            connection.publish(
                topic=telemetry_topic,
                payload=json.dumps(ack),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )

        else:
            log.warning("Unknown action: %s", action)

    except Exception as e:
        log.error("Error executing command '%s': %s", action, e)


# ── Camera singleton (lazy-init on first photo) ──────────────────────────
_camera = None


def _get_camera():
    """Return a ready Camera instance, initialising on first call.

    Cold start takes ~60 s on the Pi Zero (PiCamera GPU init).
    Subsequent calls return the cached instance instantly.
    If the cached camera is stale it is closed and re-created.
    """
    global _camera
    if _camera is not None:
        return _camera

    from zumi.util.camera import Camera
    log.info("Camera cold start (first photo — takes a while on Pi Zero)...")
    cam = Camera(320, 240)
    cam.start_camera()
    time.sleep(2)  # sensor warmup — required or first capture returns no data
    _camera = cam
    log.info("Camera ready")
    return _camera


def _reset_camera():
    """Close the current camera and clear the singleton so the next
    call to _get_camera() does a fresh init."""
    global _camera
    if _camera is not None:
        try:
            _camera.close()
        except Exception:
            pass
        _camera = None


def _take_and_ack(screen, connection, telemetry_topic, payload):
    """Take a photo and upload it to S3 via presigned URL.

    Lazy-inits the camera on the first call.  If capture fails, resets
    the camera and retries once.  Falls back to a test image if the
    camera is completely unavailable.
    """
    upload_url = payload.get("upload_url", "")
    if not upload_url:
        log.error("take_photo: no upload_url in payload")
        return

    # ── Capture (with one retry) ──────────────────────────────────
    frame = None
    for attempt in range(2):
        try:
            camera = _get_camera()
            screen.draw_text_center("Cheese!")
            frame = camera.capture()
            _reset_camera()
            break
        except Exception as e:
            log.warning("Camera capture attempt %d failed: %s", attempt + 1, e)
            _reset_camera()
            if attempt == 0:
                log.info("Retrying with fresh camera init...")

    if frame is None:
        import cv2
        import numpy
        frame = numpy.zeros((240, 320, 3), dtype=numpy.uint8)
        frame[:, :, 0] = 80
        frame[:, :, 1] = 60
        cv2.putText(frame, "Zumi Cam", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        cv2.putText(frame, "No camera", (55, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 200, 255), 2)
        screen.draw_text_center("Test img")

    # ── Encode + Upload ───────────────────────────────────────────
    try:
        import cv2
        # Camera returns BGR; convert to RGB so the JPEG has correct colours
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ok, jpeg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            log.error("take_photo: cv2.imencode failed")
            screen.draw_text_center("Encode err")
            return
        jpeg_bytes = jpeg_buf.tobytes()
        log.info("Photo captured: %d bytes", len(jpeg_bytes))

        try:
            from urllib.request import Request, urlopen
        except ImportError:
            from urllib2 import Request, urlopen

        screen.draw_text_center("Uploading...")
        req = Request(upload_url, data=jpeg_bytes, method="PUT")
        req.add_header("Content-Type", "image/jpeg")
        req.add_header("Content-Length", str(len(jpeg_bytes)))
        resp = urlopen(req, timeout=30)
        log.info("S3 upload status: %s", resp.getcode())
        screen.draw_text_center("Uploaded!")

    except Exception as e:
        log.error("Upload error: %s", e)
        screen.draw_text_center("Upload err")


def on_message(topic, payload, dup, qos, retain, **kwargs):
    """MQTT message callback — dispatches to handle_command."""
    try:
        # awsiotsdk delivers payload as bytes; Python 3.5 json.loads needs str
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        data = json.loads(payload)
    except (ValueError, TypeError) as e:
        log.error("Invalid JSON on topic %s: %s", topic, e)
        return
    handle_command(
        on_message._zumi, on_message._screen,
        on_message._connection, on_message._cfg, data,
        on_message._nav_controller,
    )


# ── Watchdog result check ─────────────────────────────────────────────────

_DEFAULT_WATCHDOG_RESULT_PATH = "/home/pi/zumi-iot/.ota-watchdog-result.json"


def _check_watchdog_result(cfg):
    """Check for a watchdog result file left by ota_watchdog.sh.

    After a self-update, the watchdog script writes a JSON result file
    indicating whether the service restart and health check succeeded
    or failed. This function reads and logs that result on startup,
    then deletes the file so it is not processed again.

    Args:
        cfg: The loaded config dict. Uses 'ota_watchdog_result_path'
            if present, otherwise falls back to the default path.
    """
    result_path = cfg.get(
        "ota_watchdog_result_path", _DEFAULT_WATCHDOG_RESULT_PATH
    )

    if not os.path.isfile(result_path):
        return

    log.info("Found watchdog result file: %s", result_path)
    try:
        with open(result_path, "r") as f:
            result = json.load(f)

        status = result.get("status", "UNKNOWN")
        job_id = result.get("job_id", "unknown")
        timestamp = result.get("timestamp", "")

        if status == "SUCCEEDED":
            log.info(
                "Watchdog result: job %s SUCCEEDED at %s",
                job_id, timestamp
            )
        elif status == "FAILED":
            reason = result.get("reason", "unknown")
            rollback = result.get("rollback_performed", False)
            log.warning(
                "Watchdog result: job %s FAILED — reason: %s, "
                "rollback_performed: %s, timestamp: %s",
                job_id, reason, rollback, timestamp
            )
        else:
            log.warning(
                "Watchdog result: job %s status=%s at %s",
                job_id, status, timestamp
            )
    except (ValueError, TypeError, IOError, OSError) as e:
        log.error("Failed to read watchdog result file: %s", e)

    # Delete the result file so it is not processed again
    try:
        os.remove(result_path)
        log.info("Removed watchdog result file: %s", result_path)
    except OSError as e:
        log.warning("Could not remove watchdog result file: %s", e)


# ── Main loop ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Zumi AWS IoT Core bridge")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.json"),
        help="Path to config.json",
    )
    args = parser.parse_args()

    # --- Load config ---
    cfg = load_config(args.config)
    thing_name = cfg["thing_name"]
    telemetry_interval = cfg.get("telemetry_interval_sec", 5)

    telemetry_topic = "zumi/%s/telemetry" % thing_name
    command_topic = "zumi/%s/command" % thing_name

    # --- Check for watchdog result from a previous self-update ---
    _check_watchdog_result(cfg)

    # --- Initialise Zumi hardware ---
    # The Zumi library blocks forever if GPIO 4 is HIGH (board I2C busy).
    # Some boards hold GPIO 4 high permanently.  Monkey-patch GPIO.input
    # to return 0 for pin 4 after a timeout so the library can proceed.
    log.info("Checking Zumi board I2C ready (GPIO 4)...")
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(4, GPIO.IN)
        deadline = time.time() + 15
        while GPIO.input(4) == 1:
            if time.time() > deadline:
                log.warning("GPIO 4 still busy after 15s — patching to bypass")
                _orig_gpio_input = GPIO.input
                def _patched_input(pin):
                    if pin == 4:
                        return 0
                    return _orig_gpio_input(pin)
                GPIO.input = _patched_input
                break
            time.sleep(0.5)
        else:
            log.info("GPIO 4 ready")
    except Exception as e:
        log.warning("GPIO check skipped: %s", e)

    log.info("Initialising Zumi hardware...")
    zumi = Zumi()
    screen = Screen()
    screen.draw_text_center("IoT Init...")

    # --- Connect to AWS IoT Core ---
    log.info("Connecting to AWS IoT Core at %s ...", cfg["endpoint"])
    connection = build_connection(cfg)
    connect_future = connection.connect()
    connect_future.result()  # blocks until connected
    log.info("Connected to AWS IoT Core.")
    screen.draw_text_center("IoT OK")

    # --- Initialize Navigation Controller (lazy inference engine) ---
    nav_controller = None
    try:
        from vision_inference import InferenceEngine
        model_dir = cfg.get("model_dir", "/home/pi/models")
        if os.path.isdir(model_dir):
            inference_engine = InferenceEngine(model_dir)
            from nav_controller import NavigationController
            nav_controller = NavigationController(
                zumi, screen, inference_engine, connection, thing_name, cfg
            )
            log.info(
                "Navigation controller initialized (backend: %s)",
                inference_engine.get_backend_name(),
            )
        else:
            log.info(
                "Model directory %s not found, navigation disabled",
                model_dir,
            )
    except Exception as e:
        log.warning(
            "Navigation controller init failed: %s. Navigation disabled.", e
        )

    # --- Subscribe to command topic ---
    on_message._zumi = zumi
    on_message._screen = screen
    on_message._connection = connection
    on_message._cfg = cfg
    on_message._nav_controller = nav_controller

    subscribe_future, _ = connection.subscribe(
        topic=command_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message,
    )
    subscribe_future.result()
    log.info("Subscribed to %s", command_topic)

    # --- Start OTA Agent ---
    ota = None
    try:
        from ota_agent import OTAAgent
        ota = OTAAgent(connection, thing_name, cfg)
        ota.start()
        log.info("OTA Agent started")
    except Exception as e:
        log.error("OTA Agent failed to start: %s", e)
        log.info("Continuing without OTA support")

    # --- Graceful shutdown ---
    def _shutdown(signum, frame):
        log.info("Shutdown signal received.")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # --- Telemetry publish loop ---
    log.info(
        "Publishing telemetry every %ds on %s", telemetry_interval, telemetry_topic
    )
    screen.draw_text_center("Running")

    while not shutdown_event.is_set():
        try:
            telemetry = collect_telemetry(zumi, thing_name)
            payload = json.dumps(telemetry)
            connection.publish(
                topic=telemetry_topic,
                payload=payload,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            log.info(
                "Published telemetry — battery=%.2fV orientation=%s",
                telemetry["battery_voltage"],
                telemetry["orientation"],
            )
        except Exception as e:
            log.error("Telemetry publish error: %s", e)

        shutdown_event.wait(timeout=telemetry_interval)

    # --- Cleanup ---
    log.info("Disconnecting...")
    screen.draw_text_center("Bye!")
    if nav_controller is not None:
        try:
            nav_controller.stop_navigation()
            log.info("Navigation controller stopped")
        except Exception as e:
            log.error("Navigation controller stop error: %s", e)
    if ota is not None:
        try:
            ota.stop()
            log.info("OTA Agent stopped")
        except Exception as e:
            log.error("OTA Agent stop error: %s", e)
    _reset_camera()
    zumi.all_lights_off()
    zumi.stop()
    disconnect_future = connection.disconnect()
    disconnect_future.result()
    log.info("Disconnected. Goodbye.")


if __name__ == "__main__":
    main()
