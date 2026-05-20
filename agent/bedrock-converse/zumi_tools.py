"""
Zumi tool definitions for Bedrock Converse API.

Each tool maps to a command the Zumi IoT app understands.
Includes sensors, LEDs, buzzer, screen, camera, and basic drive controls.
"""

ZUMI_TOOLS = [
    {
        "toolSpec": {
            "name": "read_sensors",
            "description": "Read all IR sensor values from Zumi. Returns 6 IR readings (front left/right, bottom left/right, back left/right) with values 0-255.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "read_battery",
            "description": "Read Zumi's battery voltage. Normal range is 3.0-4.2V. Returns ~0.07V when USB-powered.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "read_orientation",
            "description": "Get Zumi's current orientation: upright, upside down, face up, face down, left/right side down, etc.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "read_angles",
            "description": "Read Zumi's gyroscope angles (x, y, z) in degrees.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "headlights_on",
            "description": "Turn on Zumi's front headlight LEDs.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "headlights_off",
            "description": "Turn off Zumi's front headlight LEDs.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "all_lights_on",
            "description": "Turn on all of Zumi's LEDs (front headlights and rear brake lights).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "all_lights_off",
            "description": "Turn off all of Zumi's LEDs.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "hazard_lights_on",
            "description": "Turn on Zumi's hazard lights (flashing front and back LEDs).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "hazard_lights_off",
            "description": "Turn off Zumi's hazard lights.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "signal_left_on",
            "description": "Turn on Zumi's left turn signal (flashing left LEDs).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "signal_left_off",
            "description": "Turn off Zumi's left turn signal.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "signal_right_on",
            "description": "Turn on Zumi's right turn signal (flashing right LEDs).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "signal_right_off",
            "description": "Turn off Zumi's right turn signal.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "brake_lights_on",
            "description": "Turn on Zumi's rear brake lights.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "brake_lights_off",
            "description": "Turn off Zumi's rear brake lights.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "play_note",
            "description": "Play a musical note on Zumi's buzzer. Notes range from C2 (1) to B6 (60). Common notes: C4=25, D4=27, E4=29, F4=30, G4=32, A4=34, B4=36.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "note": {
                            "type": "integer",
                            "description": "Note number 1-60 (C2=1, C4=25, A4=34, B6=60)",
                            "minimum": 0,
                            "maximum": 60
                        },
                        "duration_ms": {
                            "type": "integer",
                            "description": "Duration in milliseconds (100-2500, in 100ms increments). Default 500.",
                            "minimum": 100,
                            "maximum": 2500
                        }
                    },
                    "required": ["note"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "display_text",
            "description": "Display a text message on Zumi's OLED screen (128x64 pixels). Keep messages short.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Text to display on Zumi's screen"
                        }
                    },
                    "required": ["message"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "show_emotion",
            "description": "Show an emotion/expression on Zumi's OLED screen using animated eyes.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "emotion": {
                            "type": "string",
                            "description": "The emotion to display",
                            "enum": ["happy", "sad", "angry", "hello", "sleeping", "blink", "glimmer", "look_around"]
                        }
                    },
                    "required": ["emotion"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "take_photo",
            "description": "Take a photo with Zumi's camera. The photo is uploaded to S3 and a viewable URL is returned. Use this when the user wants to see what Zumi sees.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    # ── Basic Drive Tools ─────────────────────────────────────────
    {
        "toolSpec": {
            "name": "drive_forward",
            "description": "Drive Zumi forward. The robot will physically move — make sure it is on a flat surface with clearance ahead. Default speed 40, duration 1 second.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-80). Default 40.",
                            "minimum": 1,
                            "maximum": 80
                        },
                        "duration": {
                            "type": "number",
                            "description": "Duration in seconds (0.1-5.0). Default 1.0.",
                            "minimum": 0.1,
                            "maximum": 5.0
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "drive_reverse",
            "description": "Drive Zumi in reverse. The robot will physically move backward — make sure it is on a flat surface with clearance behind. Default speed 40, duration 1 second.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-80). Default 40.",
                            "minimum": 1,
                            "maximum": 80
                        },
                        "duration": {
                            "type": "number",
                            "description": "Duration in seconds (0.1-5.0). Default 1.0.",
                            "minimum": 0.1,
                            "maximum": 5.0
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "turn_left",
            "description": "Turn Zumi left by a specified angle. Default 90 degrees.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "angle": {
                            "type": "integer",
                            "description": "Turn angle in degrees (1-360). Default 90.",
                            "minimum": 1,
                            "maximum": 360
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "turn_right",
            "description": "Turn Zumi right by a specified angle. Default 90 degrees.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "angle": {
                            "type": "integer",
                            "description": "Turn angle in degrees (1-360). Default 90.",
                            "minimum": 1,
                            "maximum": 360
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "emergency_stop",
            "description": "Immediately stop all motor activity on Zumi. Use this if the robot needs to stop urgently.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    # ── Advanced Movement Tools ───────────────────────────────────
    {
        "toolSpec": {
            "name": "drive_circle",
            "description": "Drive Zumi in a circle. Requires open floor space — the circle is roughly 30cm in diameter at default settings.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "description": "Circle direction",
                            "enum": ["left", "right"]
                        },
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-80). Default 30.",
                            "minimum": 1,
                            "maximum": 80
                        },
                        "step": {
                            "type": "integer",
                            "description": "Angle step size (1-10). Smaller = wider circle. Default 2.",
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["direction"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "drive_square",
            "description": "Drive Zumi in a square pattern. Requires open floor space.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "description": "Square direction",
                            "enum": ["left", "right"]
                        },
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-80). Default 40.",
                            "minimum": 1,
                            "maximum": 80
                        },
                        "seconds": {
                            "type": "number",
                            "description": "Duration per side in seconds (0.5-3.0). Default 1.0.",
                            "minimum": 0.5,
                            "maximum": 3.0
                        }
                    },
                    "required": ["direction"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "drive_figure_8",
            "description": "Drive Zumi in a figure-8 pattern. Requires open floor space — the pattern is roughly 60cm long.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-50). Default 30.",
                            "minimum": 1,
                            "maximum": 50
                        },
                        "step": {
                            "type": "integer",
                            "description": "Angle step size (1-10). Default 3.",
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "parallel_park",
            "description": "Perform a parallel parking maneuver. Requires open floor space. Default speed 15.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-30). Default 15.",
                            "minimum": 1,
                            "maximum": 30
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "j_turn",
            "description": "Perform a J-turn (reverse 180-degree turn). Requires open floor space. Default speed 80.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed (1-80). Default 80.",
                            "minimum": 1,
                            "maximum": 80
                        }
                    },
                    "required": []
                }
            }
        }
    },
    # ── Distance Drive Tools ──────────────────────────────────────
    {
        "toolSpec": {
            "name": "move_inches",
            "description": "Drive Zumi a precise distance in inches using PID-controlled movement. More accurate than timed driving. The robot will physically move.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "distance": {
                            "type": "number",
                            "description": "Distance in inches (0.5-24.0).",
                            "minimum": 0.5,
                            "maximum": 24.0
                        },
                        "angle": {
                            "type": "integer",
                            "description": "Heading angle in degrees (0-360). Default is current heading.",
                            "minimum": 0,
                            "maximum": 360
                        }
                    },
                    "required": ["distance"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "move_centimeters",
            "description": "Drive Zumi a precise distance in centimeters using PID-controlled movement. More accurate than timed driving. The robot will physically move.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "distance": {
                            "type": "number",
                            "description": "Distance in centimeters (1.0-60.0).",
                            "minimum": 1.0,
                            "maximum": 60.0
                        },
                        "angle": {
                            "type": "integer",
                            "description": "Heading angle in degrees (0-360). Default is current heading.",
                            "minimum": 0,
                            "maximum": 360
                        }
                    },
                    "required": ["distance"]
                }
            }
        }
    },
    # ── Vision Analysis Tool ──────────────────────────────────────
    {
        "toolSpec": {
            "name": "analyze_photo",
            "description": "Analyze a photo taken by Zumi's camera to detect a target object and estimate its distance. Use after take_photo to get the image_url. Returns detection results including position and estimated distance.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "image_url": {"type": "string", "description": "Presigned S3 GET URL from a prior take_photo call."},
                        "target_description": {"type": "string", "description": "Natural language description of the object to find, e.g. 'red ball', 'blue cup'."}
                    },
                    "required": ["image_url", "target_description"]
                }
            }
        }
    },
    # ── Vision Navigation Tools ──────────────────────────────────
    {
        "toolSpec": {
            "name": "navigate_to_target",
            "description": "Start vision-guided navigation toward a target object. "
                           "Zumi will use its camera and local ML model to find and "
                           "drive toward the specified object while avoiding obstacles.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "target_label": {
                            "type": "string",
                            "description": "Object class label to navigate toward (e.g. 'person', 'cup', 'bottle')"
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": "Maximum navigation steps before timeout (default 50)",
                            "minimum": 1,
                            "maximum": 200
                        },
                        "speed": {
                            "type": "integer",
                            "description": "Navigation speed (1-40, default 30)",
                            "minimum": 1,
                            "maximum": 40
                        }
                    },
                    "required": ["target_label"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "check_navigation_status",
            "description": "Check the status of an active navigation session.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    # ── Calibration Tools ─────────────────────────────────────────
    {
        "toolSpec": {
            "name": "calibrate_gyro",
            "description": "Calibrate Zumi's gyroscope by reading from a previous MPU offsets file or creating one by averaging multiple sensor readings. Zumi must be stationary on a flat surface during calibration. Run this if Zumi is drifting or turning inaccurately.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "calibrate_mpu",
            "description": "Calibrate Zumi's MPU (gyroscope + accelerometer) by averaging multiple sensor readings to create an offsets file. Zumi must be stationary on a flat surface during calibration. Higher count improves accuracy but takes longer.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of sensor samples to average (50-1000). Default 100. Higher = more accurate but slower.",
                            "minimum": 50,
                            "maximum": 1000
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "speed_calibration",
            "description": "Calibrate Zumi's speed prediction by driving over a calibration sheet with 5 horizontal white lines (2cm wide). Required for accurate move_inches and move_centimeters commands. Zumi must be placed on the black portion of the calibration sheet before starting.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "speed": {
                            "type": "integer",
                            "description": "Driving speed for calibration (1-80). Default 40. Lower = more accurate.",
                            "minimum": 1,
                            "maximum": 80
                        },
                        "ir_threshold": {
                            "type": "integer",
                            "description": "IR sensor threshold for detecting white lines (0-255). Default 100.",
                            "minimum": 0,
                            "maximum": 255
                        },
                        "time_out": {
                            "type": "number",
                            "description": "Timeout in seconds (1.0-10.0). Default 3.0.",
                            "minimum": 1.0,
                            "maximum": 10.0
                        },
                        "cm_per_brick": {
                            "type": "number",
                            "description": "Width of each road marker in centimeters (0.5-5.0). Default 2.0.",
                            "minimum": 0.5,
                            "maximum": 5.0
                        }
                    },
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "reset_drive",
            "description": "Reset both PID error accumulators and gyro angle values to zero. Use before sequences of precise turns or straight-line driving to improve accuracy.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "reset_gyro",
            "description": "Reset all gyro angle values to zero. Use before driving straight or turning accurately to establish a fresh reference point.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "reset_pid",
            "description": "Reset the gyro error sum and PID error sum to zero without resetting the P, I, and D tuning values. Use to clear accumulated error before precise driving.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
]
