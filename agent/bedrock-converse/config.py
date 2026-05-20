"""Configuration for the Zumi Chatbot."""
import os

# AWS Bedrock
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

# AWS IoT Core
IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "a3zsx6a5du4px-ats.iot.us-east-1.amazonaws.com")
IOT_REGION = os.environ.get("IOT_REGION", "us-east-1")
IOT_THING_NAME = os.environ.get("IOT_THING_NAME", "robolink-zumi")

# XGO2 IoT (falls back to Zumi values when not set)
XGO2_IOT_ENDPOINT = os.environ.get("XGO2_IOT_ENDPOINT", IOT_ENDPOINT)
XGO2_IOT_REGION = os.environ.get("XGO2_IOT_REGION", IOT_REGION)
XGO2_THING_NAME = os.environ.get("XGO2_THING_NAME", "xgo-robodog")

# Default robot
DEFAULT_ROBOT = os.environ.get("DEFAULT_ROBOT", "zumi")

# S3 — photo uploads
S3_BUCKET = os.environ.get("S3_BUCKET", "zumi-chatbot-photos")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_PRESIGN_EXPIRY = int(os.environ.get("S3_PRESIGN_EXPIRY", "300"))

# OTA
OTA_S3_PREFIX = os.environ.get("OTA_S3_PREFIX", "ota")
OTA_PRESIGN_EXPIRY = int(os.environ.get("OTA_PRESIGN_EXPIRY", "3600"))
OTA_SIGNING_PROFILE = os.environ.get("OTA_SIGNING_PROFILE", "")

# Topics
COMMAND_TOPIC = f"zumi/{IOT_THING_NAME}/command"
TELEMETRY_TOPIC = f"zumi/{IOT_THING_NAME}/telemetry"
PHOTO_ACK_TOPIC = f"zumi/{IOT_THING_NAME}/photo_ack"

# Per-layer agent model configuration (defaults handled in layer_config.py)
PERCEPTION_MODEL_ID = os.environ.get("PERCEPTION_MODEL_ID")
PERCEPTION_TEMPERATURE = os.environ.get("PERCEPTION_TEMPERATURE")
PERCEPTION_MAX_TOKENS = os.environ.get("PERCEPTION_MAX_TOKENS")

REASONING_MODEL_ID = os.environ.get("REASONING_MODEL_ID")
REASONING_TEMPERATURE = os.environ.get("REASONING_TEMPERATURE")
REASONING_MAX_TOKENS = os.environ.get("REASONING_MAX_TOKENS")

ACT_MODEL_ID = os.environ.get("ACT_MODEL_ID")
ACT_TEMPERATURE = os.environ.get("ACT_TEMPERATURE")
ACT_MAX_TOKENS = os.environ.get("ACT_MAX_TOKENS")

GOVERNANCE_MODEL_ID = os.environ.get("GOVERNANCE_MODEL_ID")
GOVERNANCE_TEMPERATURE = os.environ.get("GOVERNANCE_TEMPERATURE")
GOVERNANCE_MAX_TOKENS = os.environ.get("GOVERNANCE_MAX_TOKENS")

# SageMaker Neo
NEO_ROLE_ARN = os.environ.get("NEO_ROLE_ARN", "")
NEO_S3_OUTPUT = os.environ.get("NEO_S3_OUTPUT", "s3://zumi-chatbot-photos/neo-output/")
NEO_TARGET_DEVICE = os.environ.get("NEO_TARGET_DEVICE", "rasp3b")
NEO_FRAMEWORK = os.environ.get("NEO_FRAMEWORK", "tflite")
NEO_FRAMEWORK_VERSION = os.environ.get("NEO_FRAMEWORK_VERSION", "1.15")
NEO_INPUT_SHAPE = os.environ.get("NEO_INPUT_SHAPE", '{"input": [1, 128, 128, 3]}')
NEO_MAX_RUNTIME = int(os.environ.get("NEO_MAX_RUNTIME", "900"))
