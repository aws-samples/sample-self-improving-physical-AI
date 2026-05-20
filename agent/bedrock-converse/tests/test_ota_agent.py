"""Unit tests for ota_agent.py — device-side OTA Agent core and notification handler.

Tests the OTAAgent class (start, notification handling) and the device-side
parse_job_document() function.

Requirements: 2.1, 2.2, 2.3, 2.4, 10.4, 10.5, 11.3
"""

import sys
import os
import json
import subprocess

# Add scripts directory to path so we can import ota_agent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from urllib.error import HTTPError, URLError

# Mock awscrt and awsiot before importing ota_agent
from unittest.mock import MagicMock, patch, call

mock_awscrt = MagicMock()
mock_awsiot = MagicMock()
sys.modules['awscrt'] = mock_awscrt
sys.modules['awscrt.mqtt'] = mock_awscrt.mqtt
sys.modules['awscrt.io'] = mock_awscrt.io
sys.modules['awsiot'] = mock_awsiot
sys.modules['awsiot.mqtt_connection_builder'] = mock_awsiot.mqtt_connection_builder

# Set up QoS enum mock so subscribe calls work
mock_awscrt.mqtt.QoS.AT_LEAST_ONCE = 1

import pytest
from ota_agent import parse_job_document, OTAAgent, SUPPORTED_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_doc():
    """Return a minimal valid job document dict."""
    return {
        "version": "1.0",
        "operation": "update_files",
        "artifacts": [
            {
                "url": "https://s3.example.com/ota/thing/ts/file.py?sig=abc",
                "target_path": "/home/pi/zumi-iot/zumi_iot.py",
                "file_size": 15234,
                "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
            }
        ],
        "post_action": "restart_service",
    }


def _make_valid_json():
    """Return a valid job document as a JSON string."""
    return json.dumps(_make_valid_doc())


def _make_agent(thing_name="test-zumi"):
    """Create an OTAAgent with a mocked MQTT connection."""
    mock_conn = MagicMock()
    # subscribe returns (future, packet_id)
    mock_future = MagicMock()
    mock_future.result.return_value = None
    mock_conn.subscribe.return_value = (mock_future, 1)
    config = {
        "ota_staging_dir": "/tmp/ota-staging",
        "ota_backup_dir": "/tmp/ota-backup",
        "ota_health_check_timeout": 60,
        "ota_download_retries": 3,
    }
    agent = OTAAgent(mock_conn, thing_name, config)
    return agent, mock_conn


# ---------------------------------------------------------------------------
# TestParseJobDocument — device-side parse_job_document()
# Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 11.3
# ---------------------------------------------------------------------------

class TestParseJobDocument:
    """Test the standalone device-side parse_job_document() function."""

    def test_valid_document_accepted(self):
        """Valid JSON string with all required fields is accepted."""
        raw = _make_valid_json()
        doc = parse_job_document(raw)
        assert doc["version"] == SUPPORTED_SCHEMA_VERSION
        assert doc["operation"] == "update_files"
        assert len(doc["artifacts"]) == 1
        assert doc["artifacts"][0]["sha256"] == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

    def test_valid_document_with_codesign(self):
        """Valid document with optional codesign object is accepted."""
        doc_dict = _make_valid_doc()
        doc_dict["artifacts"][0]["codesign"] = {
            "signature": "c2lnbmF0dXJl",
            "signing_profile": "zumi-ota-signer",
            "algorithm": "RSA-SHA256",
        }
        raw = json.dumps(doc_dict)
        doc = parse_job_document(raw)
        assert "codesign" in doc["artifacts"][0]

    def test_bytes_input_accepted(self):
        """Bytes input is decoded and parsed correctly."""
        raw = _make_valid_json().encode("utf-8")
        doc = parse_job_document(raw)
        assert doc["version"] == SUPPORTED_SCHEMA_VERSION

    def test_invalid_json_raises_valueerror(self):
        """Invalid JSON string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_job_document("{not valid json")

    def test_unsupported_version_raises_valueerror(self):
        """Unsupported schema version raises ValueError."""
        doc_dict = _make_valid_doc()
        doc_dict["version"] = "99.0"
        raw = json.dumps(doc_dict)
        with pytest.raises(ValueError, match="Unsupported job document version.*99.0"):
            parse_job_document(raw)

    def test_missing_top_level_fields_raises_valueerror(self):
        """Missing top-level required fields raises ValueError listing them."""
        raw = json.dumps({"version": "1.0"})
        with pytest.raises(ValueError, match="missing required fields") as exc_info:
            parse_job_document(raw)
        msg = str(exc_info.value)
        for field in ("operation", "artifacts", "post_action"):
            assert field in msg

    def test_missing_single_top_level_field(self):
        """Missing a single top-level field is reported."""
        doc_dict = _make_valid_doc()
        del doc_dict["post_action"]
        raw = json.dumps(doc_dict)
        with pytest.raises(ValueError, match="post_action"):
            parse_job_document(raw)

    def test_missing_artifact_fields_raises_valueerror(self):
        """Missing artifact descriptor fields raises ValueError listing them."""
        doc_dict = _make_valid_doc()
        doc_dict["artifacts"] = [{"url": "https://example.com/file.py"}]
        raw = json.dumps(doc_dict)
        with pytest.raises(ValueError, match="missing required fields") as exc_info:
            parse_job_document(raw)
        msg = str(exc_info.value)
        for field in ("target_path", "file_size", "sha256"):
            assert field in msg

    def test_empty_artifacts_list_raises_valueerror(self):
        """Empty artifacts list raises ValueError."""
        doc_dict = _make_valid_doc()
        doc_dict["artifacts"] = []
        raw = json.dumps(doc_dict)
        with pytest.raises(ValueError, match="must not be empty"):
            parse_job_document(raw)

    def test_non_dict_document_raises_valueerror(self):
        """Non-dict JSON (e.g. a list) raises ValueError."""
        raw = json.dumps([1, 2, 3])
        with pytest.raises(ValueError, match="must be a JSON object"):
            parse_job_document(raw)


# ---------------------------------------------------------------------------
# TestOTAAgentStart — OTAAgent.start()
# Validates: Requirement 2.1
# ---------------------------------------------------------------------------

class TestOTAAgentStart:
    """Test that start() subscribes to the correct IoT Jobs topic."""

    def test_subscribes_to_notify_next_topic(self):
        """start() subscribes to $aws/things/{thing_name}/jobs/notify-next."""
        agent, mock_conn = _make_agent("my-zumi")
        agent.start()

        mock_conn.subscribe.assert_called_once()
        subscribe_call = mock_conn.subscribe.call_args
        topic = subscribe_call[1]["topic"]
        assert topic == "$aws/things/my-zumi/jobs/notify-next"

    def test_subscribe_uses_at_least_once_qos(self):
        """start() subscribes with QoS AT_LEAST_ONCE."""
        agent, mock_conn = _make_agent()
        agent.start()

        subscribe_call = mock_conn.subscribe.call_args
        qos = subscribe_call[1]["qos"]
        assert qos == mock_awscrt.mqtt.QoS.AT_LEAST_ONCE

    def test_start_sets_running_flag(self):
        """start() sets the _running flag to True."""
        agent, _ = _make_agent()
        assert not agent._running
        agent.start()
        assert agent._running

    def test_start_when_already_running_does_not_resubscribe(self):
        """Calling start() twice does not subscribe again."""
        agent, mock_conn = _make_agent()
        agent.start()
        agent.start()
        assert mock_conn.subscribe.call_count == 1


# ---------------------------------------------------------------------------
# TestOTAAgentNotification — notification handler
# Validates: Requirements 2.2, 2.3, 2.4, 10.4, 10.5
# ---------------------------------------------------------------------------

class TestOTAAgentNotification:
    """Test the _on_job_notification callback."""

    def _make_payload(self, job_document, job_id="test-job-001"):
        """Build a notify-next payload with the given job document."""
        return json.dumps({
            "execution": {
                "jobId": job_id,
                "jobDocument": job_document,
            }
        }).encode("utf-8")

    def test_valid_notification_triggers_in_progress(self):
        """Valid job notification calls _report_in_progress (Req 2.3)."""
        agent, _ = _make_agent()
        doc = _make_valid_doc()
        payload = self._make_payload(doc)

        with patch.object(agent, '_report_in_progress') as mock_progress, \
             patch.object(agent, '_process_job') as mock_process:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_progress.assert_called_once_with("test-job-001")
            mock_process.assert_called_once()

    def test_valid_notification_with_string_job_document(self):
        """Job document as JSON string (not pre-parsed dict) is handled."""
        agent, _ = _make_agent()
        payload = json.dumps({
            "execution": {
                "jobId": "test-job-002",
                "jobDocument": _make_valid_json(),
            }
        }).encode("utf-8")

        with patch.object(agent, '_report_in_progress') as mock_progress, \
             patch.object(agent, '_process_job'):
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_progress.assert_called_once_with("test-job-002")

    def test_invalid_json_payload_triggers_failure(self):
        """Invalid JSON in the outer payload triggers _report_failure with parse_error (Req 2.4)."""
        agent, _ = _make_agent()
        # Set a current job id so failure can be reported
        agent._current_job_id = "fallback-job"

        with patch.object(agent, '_report_failure') as mock_failure:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=b"{not valid json",
                dup=False, qos=1, retain=False,
            )
            mock_failure.assert_called_once()
            args = mock_failure.call_args[0]
            assert args[1] == "parse_error"

    def test_unsupported_version_triggers_failure(self):
        """Unsupported schema version triggers _report_failure with unsupported_version (Req 10.4)."""
        agent, _ = _make_agent()
        doc = _make_valid_doc()
        doc["version"] = "99.0"
        payload = self._make_payload(doc)

        with patch.object(agent, '_report_failure') as mock_failure, \
             patch.object(agent, '_report_in_progress') as mock_progress:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_failure.assert_called_once()
            args = mock_failure.call_args[0]
            assert args[1] == "unsupported_version"
            mock_progress.assert_not_called()

    def test_missing_fields_triggers_failure(self):
        """Missing required fields triggers _report_failure with missing_fields (Req 10.5)."""
        agent, _ = _make_agent()
        doc = {"version": "1.0"}  # missing operation, artifacts, post_action
        payload = self._make_payload(doc)

        with patch.object(agent, '_report_failure') as mock_failure, \
             patch.object(agent, '_report_in_progress') as mock_progress:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_failure.assert_called_once()
            args = mock_failure.call_args[0]
            assert args[1] == "missing_fields"
            # Verify the error message lists the missing fields
            assert "operation" in args[2]
            assert "artifacts" in args[2]
            assert "post_action" in args[2]
            mock_progress.assert_not_called()

    def test_no_execution_in_payload_no_failure(self):
        """Payload with no 'execution' key is a normal case — no failure reported."""
        agent, _ = _make_agent()
        payload = json.dumps({}).encode("utf-8")

        with patch.object(agent, '_report_failure') as mock_failure, \
             patch.object(agent, '_report_in_progress') as mock_progress:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_failure.assert_not_called()
            mock_progress.assert_not_called()

    def test_missing_job_document_triggers_failure(self):
        """Execution without jobDocument triggers _report_failure."""
        agent, _ = _make_agent()
        payload = json.dumps({
            "execution": {
                "jobId": "test-job-003",
                # no jobDocument key
            }
        }).encode("utf-8")

        with patch.object(agent, '_report_failure') as mock_failure:
            agent._on_job_notification(
                topic="$aws/things/test-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )
            mock_failure.assert_called_once()
            args = mock_failure.call_args[0]
            assert args[0] == "test-job-003"
            assert "missing_fields" in args[1] or "jobDocument" in args[2]


# ---------------------------------------------------------------------------
# Task 6.4 — Download and verification unit tests
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 10.6, 10.7, 12.5, 12.7, 12.8, 12.9
# ---------------------------------------------------------------------------

import hashlib
import tempfile
import base64
import io

from unittest.mock import PropertyMock

# We use the `cryptography` library (cloud-side test env, Python 3.11+)
# to generate real RSA key pairs for signature verification tests.
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

from ota_agent import _pkcs1_v15_verify_rsa_sha256


def _generate_rsa_keypair():
    """Generate a 2048-bit RSA key pair and return (private_key, public_pem_bytes)."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


def _sign_data(private_key, data):
    """Sign data with RSA-SHA256 PKCS#1 v1.5 and return raw signature bytes."""
    return private_key.sign(
        data,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


# ---------------------------------------------------------------------------
# TestDownloadArtifact — _download_artifact()
# Validates: Requirements 3.1, 3.3, 3.4, 3.5
# ---------------------------------------------------------------------------

class TestDownloadArtifact:
    """Test OTAAgent._download_artifact() download and retry logic."""

    def test_happy_path_downloads_and_writes_file(self, tmp_path):
        """Happy path: urlopen returns data, file is written to staging path (Req 3.1, 3.5)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "staging" / "file.py")
        test_data = b"print('hello world')\n"

        mock_response = MagicMock()
        mock_response.read.return_value = test_data

        with patch("ota_agent.urlopen", return_value=mock_response) as mock_urlopen, \
             patch("ota_agent.time.sleep"):
            agent._download_artifact(
                "https://s3.example.com/ota/file.py?sig=abc",
                staging_path,
            )

        assert os.path.isfile(staging_path)
        with open(staging_path, "rb") as f:
            assert f.read() == test_data
        mock_urlopen.assert_called_once()

    def test_retry_one_failure_then_success(self, tmp_path):
        """1 network failure then success — file is written (Req 3.4)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "staging" / "file.py")
        test_data = b"data after retry"

        mock_response = MagicMock()
        mock_response.read.return_value = test_data

        # First call raises URLError, second succeeds
        with patch("ota_agent.urlopen") as mock_urlopen, \
             patch("ota_agent.time.sleep") as mock_sleep:
            mock_urlopen.side_effect = [
                URLError("connection reset"),
                mock_response,
            ]
            agent._download_artifact(
                "https://s3.example.com/ota/file.py",
                staging_path,
            )

        assert os.path.isfile(staging_path)
        with open(staging_path, "rb") as f:
            assert f.read() == test_data
        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once_with(2)  # 2^1 = 2s backoff

    def test_retry_two_failures_then_success(self, tmp_path):
        """2 network failures then success — file is written (Req 3.4)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "staging" / "file.py")
        test_data = b"data after two retries"

        mock_response = MagicMock()
        mock_response.read.return_value = test_data

        with patch("ota_agent.urlopen") as mock_urlopen, \
             patch("ota_agent.time.sleep") as mock_sleep:
            mock_urlopen.side_effect = [
                URLError("timeout"),
                URLError("connection reset"),
                mock_response,
            ]
            agent._download_artifact(
                "https://s3.example.com/ota/file.py",
                staging_path,
            )

        assert os.path.isfile(staging_path)
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)   # 2^1 = 2s
        mock_sleep.assert_any_call(4)   # 2^2 = 4s

    def test_three_failures_raises_ioerror(self, tmp_path):
        """3 consecutive failures raises IOError (Req 3.4)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "staging" / "file.py")

        with patch("ota_agent.urlopen") as mock_urlopen, \
             patch("ota_agent.time.sleep") as mock_sleep:
            mock_urlopen.side_effect = [
                URLError("fail 1"),
                URLError("fail 2"),
                URLError("fail 3"),
            ]
            with pytest.raises(IOError, match="Download failed after 3 attempts"):
                agent._download_artifact(
                    "https://s3.example.com/ota/file.py",
                    staging_path,
                )

        assert mock_urlopen.call_count == 3
        # Backoff sleeps happen between attempts 1→2 and 2→3, not after the last
        assert mock_sleep.call_count == 2

    def test_http_403_raises_valueerror_immediately(self, tmp_path):
        """HTTP 403 (expired URL) raises ValueError without retrying (Req 3.3)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "staging" / "file.py")

        http_error = HTTPError(
            url="https://s3.example.com/ota/file.py",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(b""),
        )

        with patch("ota_agent.urlopen") as mock_urlopen, \
             patch("ota_agent.time.sleep") as mock_sleep:
            mock_urlopen.side_effect = http_error
            with pytest.raises(ValueError, match="403"):
                agent._download_artifact(
                    "https://s3.example.com/ota/file.py",
                    staging_path,
                )

        # No retry on 403
        mock_urlopen.assert_called_once()
        mock_sleep.assert_not_called()

    def test_staging_directory_created_if_missing(self, tmp_path):
        """Staging directory is created if it doesn't exist (Req 3.5)."""
        agent, _ = _make_agent()
        staging_path = str(tmp_path / "new_dir" / "sub_dir" / "file.py")

        mock_response = MagicMock()
        mock_response.read.return_value = b"content"

        with patch("ota_agent.urlopen", return_value=mock_response), \
             patch("ota_agent.time.sleep"):
            agent._download_artifact(
                "https://s3.example.com/ota/file.py",
                staging_path,
            )

        assert os.path.isdir(str(tmp_path / "new_dir" / "sub_dir"))


# ---------------------------------------------------------------------------
# TestVerifyFileSize — _verify_file_size()
# Validates: Requirements 3.2, 10.7
# ---------------------------------------------------------------------------

class TestVerifyFileSize:
    """Test OTAAgent._verify_file_size() size verification."""

    def test_matching_size_returns_true(self, tmp_path):
        """File with matching size returns True (Req 3.2)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        content = b"hello world"
        with open(file_path, "wb") as f:
            f.write(content)

        assert agent._verify_file_size(file_path, len(content)) is True

    def test_mismatching_size_returns_false(self, tmp_path):
        """File with mismatching size returns False (Req 10.7)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        content = b"hello world"
        with open(file_path, "wb") as f:
            f.write(content)

        assert agent._verify_file_size(file_path, len(content) + 100) is False


# ---------------------------------------------------------------------------
# TestVerifyHash — _verify_hash()
# Validates: Requirements 3.2, 10.6, 10.7
# ---------------------------------------------------------------------------

class TestVerifyHash:
    """Test OTAAgent._verify_hash() SHA-256 verification."""

    def test_correct_hash_returns_true(self, tmp_path):
        """Correct SHA-256 hash returns True (Req 10.6)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        content = b"print('hello OTA')\n"
        with open(file_path, "wb") as f:
            f.write(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        assert agent._verify_hash(file_path, expected_hash) is True

    def test_incorrect_hash_returns_false(self, tmp_path):
        """Incorrect SHA-256 hash returns False (Req 10.7)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        content = b"print('hello OTA')\n"
        with open(file_path, "wb") as f:
            f.write(content)

        wrong_hash = "0" * 64
        assert agent._verify_hash(file_path, wrong_hash) is False

    def test_hash_comparison_is_case_insensitive(self, tmp_path):
        """Hash comparison works with uppercase hex digest (Req 10.6)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        content = b"case insensitive test"
        with open(file_path, "wb") as f:
            f.write(content)

        expected_hash = hashlib.sha256(content).hexdigest().upper()
        assert agent._verify_hash(file_path, expected_hash) is True


# ---------------------------------------------------------------------------
# TestVerifySignature — _verify_signature()
# Validates: Requirements 12.5, 12.7, 12.8, 12.9
# ---------------------------------------------------------------------------

class TestVerifySignature:
    """Test OTAAgent._verify_signature() code signature verification."""

    def test_no_codesign_returns_true(self, tmp_path):
        """No codesign (None) skips verification and returns True (Req 12.8)."""
        agent, _ = _make_agent()
        file_path = str(tmp_path / "artifact.py")
        with open(file_path, "wb") as f:
            f.write(b"content")

        assert agent._verify_signature(file_path, None) is True

    def test_missing_public_key_returns_false(self, tmp_path):
        """Missing public key file returns False (Req 12.5)."""
        agent, _ = _make_agent()
        agent._config["ota_codesign_pubkey"] = str(tmp_path / "nonexistent.pem")

        file_path = str(tmp_path / "artifact.py")
        with open(file_path, "wb") as f:
            f.write(b"content")

        codesign = {
            "signature": base64.b64encode(b"fake-sig").decode(),
            "algorithm": "RSA-SHA256",
        }
        assert agent._verify_signature(file_path, codesign) is False

    def test_valid_signature_returns_true(self, tmp_path):
        """Valid RSA-SHA256 signature returns True (Req 12.5)."""
        private_key, public_pem = _generate_rsa_keypair()

        # Write public key to a temp file
        pubkey_path = str(tmp_path / "code-signing.pem")
        with open(pubkey_path, "wb") as f:
            f.write(public_pem)

        # Write artifact content
        file_path = str(tmp_path / "artifact.py")
        content = b"print('signed artifact')\n"
        with open(file_path, "wb") as f:
            f.write(content)

        # Sign the content
        signature = _sign_data(private_key, content)
        signature_b64 = base64.b64encode(signature).decode()

        agent, _ = _make_agent()
        agent._config["ota_codesign_pubkey"] = pubkey_path

        codesign = {
            "signature": signature_b64,
            "algorithm": "RSA-SHA256",
        }
        assert agent._verify_signature(file_path, codesign) is True

    def test_invalid_signature_returns_false(self, tmp_path):
        """Invalid signature (wrong key) returns False (Req 12.7)."""
        # Generate two different key pairs
        private_key_1, _ = _generate_rsa_keypair()
        _, public_pem_2 = _generate_rsa_keypair()

        # Write the WRONG public key
        pubkey_path = str(tmp_path / "code-signing.pem")
        with open(pubkey_path, "wb") as f:
            f.write(public_pem_2)

        # Write artifact content
        file_path = str(tmp_path / "artifact.py")
        content = b"print('signed artifact')\n"
        with open(file_path, "wb") as f:
            f.write(content)

        # Sign with key 1, but verify with key 2's public key
        signature = _sign_data(private_key_1, content)
        signature_b64 = base64.b64encode(signature).decode()

        agent, _ = _make_agent()
        agent._config["ota_codesign_pubkey"] = pubkey_path

        codesign = {
            "signature": signature_b64,
            "algorithm": "RSA-SHA256",
        }
        assert agent._verify_signature(file_path, codesign) is False

    def test_tampered_content_returns_false(self, tmp_path):
        """Signature on tampered content returns False (Req 12.7)."""
        private_key, public_pem = _generate_rsa_keypair()

        pubkey_path = str(tmp_path / "code-signing.pem")
        with open(pubkey_path, "wb") as f:
            f.write(public_pem)

        # Sign original content
        original_content = b"print('original')\n"
        signature = _sign_data(private_key, original_content)
        signature_b64 = base64.b64encode(signature).decode()

        # Write TAMPERED content to the file
        file_path = str(tmp_path / "artifact.py")
        with open(file_path, "wb") as f:
            f.write(b"print('tampered')\n")

        agent, _ = _make_agent()
        agent._config["ota_codesign_pubkey"] = pubkey_path

        codesign = {
            "signature": signature_b64,
            "algorithm": "RSA-SHA256",
        }
        assert agent._verify_signature(file_path, codesign) is False


# ---------------------------------------------------------------------------
# TestProcessJobPipeline — _process_job() integration
# Validates: Requirements 10.6, 10.7, 12.9
# ---------------------------------------------------------------------------

class TestProcessJobPipeline:
    """Test _process_job() pipeline ordering and integration."""

    def test_hash_before_signature_ordering(self, tmp_path):
        """When both hash and signature fail, error reports verify_hash not verify_signature (Req 12.9).

        The pipeline checks hash BEFORE signature. If the hash fails,
        the failure step must be 'verify_hash', proving signature
        verification was never reached.
        """
        agent, _ = _make_agent()
        agent._staging_dir = str(tmp_path / "staging")

        # Create a file that will be "downloaded"
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir(parents=True)
        file_path = staging_dir / "zumi_iot.py"
        content = b"print('test content')\n"
        file_path.write_bytes(content)

        # Build a job doc with WRONG hash and a codesign that would also fail
        wrong_hash = "0" * 64
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [
                {
                    "url": "https://s3.example.com/ota/file.py",
                    "target_path": "/home/pi/zumi-iot/zumi_iot.py",
                    "file_size": len(content),
                    "sha256": wrong_hash,
                    "codesign": {
                        "signature": base64.b64encode(b"bad-sig").decode(),
                        "algorithm": "RSA-SHA256",
                    },
                }
            ],
            "post_action": "restart_service",
        }

        # Mock _download_artifact to write the file (simulating successful download)
        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(content)

        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch.object(agent, '_report_failure') as mock_failure, \
             patch.object(agent, '_discard_staged_file'):
            agent._process_job("test-job-hash-order", doc)

        # The failure must be at verify_hash, NOT verify_signature
        mock_failure.assert_called_once()
        failure_args = mock_failure.call_args[0]
        assert failure_args[0] == "test-job-hash-order"
        assert failure_args[1] == "verify_hash"
        assert "hash mismatch" in failure_args[2].lower()

    def test_download_failure_reports_download_step(self, tmp_path):
        """Download failure reports step='download' (Req 3.4)."""
        agent, _ = _make_agent()
        agent._staging_dir = str(tmp_path / "staging")

        doc = _make_valid_doc()

        with patch.object(agent, '_download_artifact', side_effect=IOError("network error")), \
             patch.object(agent, '_report_failure') as mock_failure:
            agent._process_job("test-job-dl-fail", doc)

        mock_failure.assert_called_once()
        failure_args = mock_failure.call_args[0]
        assert failure_args[1] == "download"

    def test_http_403_reports_download_step(self, tmp_path):
        """HTTP 403 (expired URL) reports step='download' (Req 3.3)."""
        agent, _ = _make_agent()
        agent._staging_dir = str(tmp_path / "staging")

        doc = _make_valid_doc()

        with patch.object(agent, '_download_artifact', side_effect=ValueError("HTTP 403")), \
             patch.object(agent, '_report_failure') as mock_failure:
            agent._process_job("test-job-403", doc)

        mock_failure.assert_called_once()
        failure_args = mock_failure.call_args[0]
        assert failure_args[1] == "download"

    def test_size_mismatch_reports_verify_size_step(self, tmp_path):
        """File size mismatch reports step='verify_size' (Req 3.2)."""
        agent, _ = _make_agent()
        agent._staging_dir = str(tmp_path / "staging")

        content = b"small"
        doc = _make_valid_doc()
        doc["artifacts"][0]["file_size"] = 99999  # wrong size

        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(content)

        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch.object(agent, '_report_failure') as mock_failure, \
             patch.object(agent, '_discard_staged_file'):
            agent._process_job("test-job-size", doc)

        mock_failure.assert_called_once()
        failure_args = mock_failure.call_args[0]
        assert failure_args[1] == "verify_size"


# ---------------------------------------------------------------------------
# TestRollbackManager — RollbackManager backup, rollback, cleanup
# Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
# ---------------------------------------------------------------------------

import stat

from ota_agent import RollbackManager


class TestRollbackManager:
    """Test the RollbackManager backup, rollback, and cleanup logic."""

    def test_backup_creates_copies(self, tmp_path):
        """backup() copies each target file into the backup directory (Req 4.1)."""
        # Create source files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_b = src_dir / "b.py"
        file_a.write_text("content_a")
        file_b.write_text("content_b")

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a), str(file_b)])

        assert os.path.isfile(os.path.join(backup_dir, "a.py"))
        assert os.path.isfile(os.path.join(backup_dir, "b.py"))
        with open(os.path.join(backup_dir, "a.py")) as f:
            assert f.read() == "content_a"
        with open(os.path.join(backup_dir, "b.py")) as f:
            assert f.read() == "content_b"

    def test_backup_writes_manifest(self, tmp_path):
        """backup() writes manifest.json with correct structure (Req 4.2)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_a.write_text("hello")

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a)])

        manifest_path = os.path.join(backup_dir, "manifest.json")
        assert os.path.isfile(manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert "timestamp" in manifest
        assert "files" in manifest
        assert len(manifest["files"]) == 1

        entry = manifest["files"][0]
        assert entry["original_path"] == str(file_a)
        assert entry["backup_path"] == os.path.join(backup_dir, "a.py")
        assert "permissions" in entry

    def test_backup_records_permissions(self, tmp_path):
        """backup() records correct octal permissions in manifest (Req 4.2)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_a.write_text("hello")
        os.chmod(str(file_a), 0o755)

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a)])

        manifest_path = os.path.join(backup_dir, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)

        entry = manifest["files"][0]
        assert entry["permissions"] == "0o755"

    def test_rollback_restores_files(self, tmp_path):
        """rollback() restores original file content from backup (Req 4.3)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_a.write_text("original_content")

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a)])

        # Modify the original file (simulating a bad update)
        file_a.write_text("corrupted_content")
        assert file_a.read_text() == "corrupted_content"

        # Rollback should restore original
        with patch("ota_agent.subprocess.call"):
            rm.rollback()

        assert file_a.read_text() == "original_content"

    def test_rollback_restarts_service(self, tmp_path):
        """rollback() calls systemctl restart zumi-iot (Req 4.4)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_a.write_text("content")

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a)])

        with patch("ota_agent.subprocess.call") as mock_call:
            rm.rollback()

        mock_call.assert_called_once_with(
            ["sudo", "systemctl", "restart", "zumi-iot"]
        )

    def test_rollback_missing_backup_file(self, tmp_path):
        """rollback() logs warning and continues when a backup file is missing (Req 4.3)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_a = src_dir / "a.py"
        file_b = src_dir / "b.py"
        file_a.write_text("content_a")
        file_b.write_text("content_b")

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_a), str(file_b)])

        # Modify originals
        file_a.write_text("corrupted_a")
        file_b.write_text("corrupted_b")

        # Delete one backup file to simulate missing backup
        os.remove(os.path.join(backup_dir, "a.py"))

        # Rollback should still restore b.py and not raise
        with patch("ota_agent.subprocess.call"):
            rm.rollback()

        # b.py should be restored, a.py stays corrupted
        assert file_b.read_text() == "content_b"
        assert file_a.read_text() == "corrupted_a"

    def test_rollback_no_manifest_raises(self, tmp_path):
        """rollback() raises IOError when no manifest.json exists (Req 4.3)."""
        backup_dir = str(tmp_path / "empty_backup") + "/"
        os.makedirs(backup_dir, exist_ok=True)
        rm = RollbackManager(backup_dir=backup_dir)

        with pytest.raises(IOError, match="No backup manifest found"):
            rm.rollback()

    def test_cleanup_retains_only_most_recent(self, tmp_path):
        """cleanup_old_backups() removes old files not in current manifest (Req 4.6)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        backup_dir = str(tmp_path / "backup") + "/"
        rm = RollbackManager(backup_dir=backup_dir)

        # First backup: file_old.py
        file_old = src_dir / "old.py"
        file_old.write_text("old_content")
        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_old)])

        # Verify old.py is in backup
        assert os.path.isfile(os.path.join(backup_dir, "old.py"))

        # Second backup: file_new.py (different file set)
        file_new = src_dir / "new.py"
        file_new.write_text("new_content")
        with patch("ota_agent.subprocess.call"):
            rm.backup([str(file_new)])

        # After second backup, old.py should be cleaned up
        assert not os.path.isfile(os.path.join(backup_dir, "old.py"))
        # new.py and manifest.json should remain
        assert os.path.isfile(os.path.join(backup_dir, "new.py"))
        assert os.path.isfile(os.path.join(backup_dir, "manifest.json"))


# ---------------------------------------------------------------------------
# Task 9.4 — Update application, health check, and self-update tests
# Validates: Requirements 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5
# ---------------------------------------------------------------------------


class TestApplyUpdate:
    """Test OTAAgent._apply_update() file copy and permission preservation."""

    def test_apply_copies_file_and_preserves_permissions(self, tmp_path):
        """apply copies staged file to target and preserves original permissions (Req 5.1, 5.2)."""
        # Create the "original" target file with specific permissions
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        target_file = target_dir / "zumi_iot.py"
        target_file.write_text("original content")
        os.chmod(str(target_file), 0o755)

        # Create the staged artifact with different content
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        staged_file = staging_dir / "zumi_iot.py"
        staged_file.write_text("updated content v2")

        agent, _ = _make_agent()
        result = agent._apply_update(str(staged_file), str(target_file))

        assert result is True
        # Content should be updated
        assert target_file.read_text() == "updated content v2"
        # Permissions should match the original (0o755)
        actual_mode = os.stat(str(target_file)).st_mode & 0o777
        assert actual_mode == 0o755

    def test_apply_failure_returns_false(self, tmp_path):
        """File copy failure (IOError) returns False (Req 5.3)."""
        agent, _ = _make_agent()

        # Create a target file so os.stat works
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        target_file = target_dir / "zumi_iot.py"
        target_file.write_text("original")

        staging_path = str(tmp_path / "staging" / "nonexistent.py")

        with patch("ota_agent.shutil.copy2", side_effect=IOError("disk full")):
            result = agent._apply_update(staging_path, str(target_file))

        assert result is False


# ---------------------------------------------------------------------------
# TestRestartAndHealthCheck — service restart and health check
# Validates: Requirements 6.1, 6.2, 6.3, 6.4
# ---------------------------------------------------------------------------

class TestRestartAndHealthCheck:
    """Test OTAAgent._restart_and_health_check() service restart and polling."""

    def test_health_check_passes(self):
        """Health check passes when systemctl reports 'active' (Req 6.1, 6.2, 6.3)."""
        agent, _ = _make_agent()

        with patch("ota_agent.subprocess.call") as mock_call, \
             patch("ota_agent.subprocess.check_output", return_value=b"active\n"), \
             patch("ota_agent.time.sleep"):
            result = agent._restart_and_health_check()

        assert result is True
        # Verify systemctl restart was called
        mock_call.assert_called_once_with(
            ["sudo", "systemctl", "restart", "zumi-iot"]
        )

    def test_health_check_timeout(self):
        """Health check returns False after timeout when service never becomes active (Req 6.4)."""
        agent, _ = _make_agent()
        # Use a short timeout for the test
        agent._health_check_timeout = 6

        with patch("ota_agent.subprocess.call"), \
             patch("ota_agent.subprocess.check_output",
                   side_effect=subprocess.CalledProcessError(3, "systemctl")), \
             patch("ota_agent.time.sleep"):
            result = agent._restart_and_health_check()

        assert result is False


# ---------------------------------------------------------------------------
# TestSelfUpdateDetection — self-update detection and watchdog delegation
# Validates: Requirement 6.5
# ---------------------------------------------------------------------------

class TestSelfUpdateDetection:
    """Test OTAAgent._is_self_update() and _delegate_to_watchdog()."""

    def test_detects_ota_agent(self):
        """_is_self_update returns True when ota_agent.py is in target paths (Req 6.5)."""
        agent, _ = _make_agent()
        result = agent._is_self_update([
            "/home/pi/zumi-iot/ota_agent.py",
        ])
        assert result is True

    def test_detects_zumi_iot(self):
        """_is_self_update returns True when zumi_iot.py is in target paths (Req 6.5)."""
        agent, _ = _make_agent()
        result = agent._is_self_update([
            "/home/pi/zumi-iot/zumi_iot.py",
        ])
        assert result is True

    def test_no_self_update(self):
        """_is_self_update returns False for non-self files (Req 6.5)."""
        agent, _ = _make_agent()
        result = agent._is_self_update([
            "/home/pi/zumi-iot/config.json",
            "/home/pi/zumi-iot/some_module.py",
        ])
        assert result is False

    def test_watchdog_delegation(self):
        """_delegate_to_watchdog calls subprocess.Popen with correct args (Req 6.5)."""
        agent, _ = _make_agent()

        with patch("ota_agent.subprocess.Popen") as mock_popen:
            agent._delegate_to_watchdog("job-123", "test-zumi")

        mock_popen.assert_called_once_with(
            ["bash", "/home/pi/zumi-iot/ota_watchdog.sh", "job-123", "test-zumi"]
        )


# ---------------------------------------------------------------------------
# TestProcessJobSucceeded — SUCCEEDED status detail
# Validates: Requirements 6.3, 7.2, 7.3
# ---------------------------------------------------------------------------

class TestProcessJobSucceeded:
    """Test that _process_job reports SUCCEEDED with correct fields."""

    def test_succeeded_status_detail(self, tmp_path):
        """SUCCEEDED status detail contains files_updated and artifact_sha256 (Req 7.3)."""
        agent, _ = _make_agent()
        agent._staging_dir = str(tmp_path / "staging")
        agent._backup_dir = str(tmp_path / "backup") + "/"

        # Create target file that will be "updated"
        # Use a non-self-update filename to avoid watchdog delegation
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        target_file = target_dir / "config_module.py"
        target_file.write_text("original content")
        os.chmod(str(target_file), 0o644)

        content = b"updated content"
        correct_hash = hashlib.sha256(content).hexdigest()

        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [
                {
                    "url": "https://s3.example.com/ota/file.py",
                    "target_path": str(target_file),
                    "file_size": len(content),
                    "sha256": correct_hash,
                }
            ],
            "post_action": "restart_service",
        }

        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(content)

        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch.object(agent, '_restart_and_health_check', return_value=True), \
             patch.object(agent, '_report_success') as mock_success, \
             patch("ota_agent.subprocess.call"):
            agent._process_job("test-job-success", doc)

        mock_success.assert_called_once()
        args = mock_success.call_args[0]
        assert args[0] == "test-job-success"
        # files_updated should contain the target path
        assert str(target_file) in args[1]
        # artifact_sha256 should be the correct hash
        assert args[2] == correct_hash
