"""Integration tests for the OTA update pipeline.

Tests end-to-end OTA flow with mocked AWS services and mocked device,
rollback on bad update scenario, and offline device catch-up scenario.

Requirements: 1.1-1.6, 2.1-2.5, 3.1-3.5, 4.1-4.6, 5.1-5.3, 6.1-6.5, 7.1-7.3
"""

import sys
import os
import json
import hashlib
import shutil
import tempfile

# Add scripts directory to path so we can import ota_agent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

# Mock awscrt and awsiot before importing ota_agent
from unittest.mock import MagicMock, patch, call

mock_awscrt = MagicMock()
mock_awsiot = MagicMock()
sys.modules['awscrt'] = mock_awscrt
sys.modules['awscrt.mqtt'] = mock_awscrt.mqtt
sys.modules['awscrt.io'] = mock_awscrt.io
sys.modules['awsiot'] = mock_awsiot
sys.modules['awsiot.mqtt_connection_builder'] = mock_awsiot.mqtt_connection_builder

# Set up QoS enum mock so subscribe/publish calls work
mock_awscrt.mqtt.QoS.AT_LEAST_ONCE = 1

import pytest
from ota_agent import OTAAgent, RollbackManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(thing_name="integration-zumi", staging_dir=None, backup_dir=None):
    """Create an OTAAgent with a mocked MQTT connection and temp directories."""
    mock_conn = MagicMock()
    mock_future = MagicMock()
    mock_future.result.return_value = None
    mock_conn.subscribe.return_value = (mock_future, 1)
    mock_conn.unsubscribe.return_value = (mock_future, 1)

    config = {
        "ota_staging_dir": staging_dir or "/tmp/ota-staging",
        "ota_backup_dir": backup_dir or "/tmp/ota-backup",
        "ota_health_check_timeout": 60,
        "ota_download_retries": 3,
    }
    agent = OTAAgent(mock_conn, thing_name, config)
    return agent, mock_conn


def _build_notification_payload(job_id, job_document):
    """Build a notify-next MQTT payload wrapping a job document."""
    return json.dumps({
        "execution": {
            "jobId": job_id,
            "jobDocument": job_document,
        }
    }).encode("utf-8")


def _compute_sha256(data):
    """Compute SHA-256 hex digest of bytes data."""
    return hashlib.sha256(data).hexdigest()


def _collect_publishes(mock_conn):
    """Extract all published payloads from the mock MQTT connection.

    Returns a list of (topic, parsed_payload_dict) tuples.
    """
    results = []
    for c in mock_conn.publish.call_args_list:
        topic = c[1].get("topic", c[0][0] if c[0] else "")
        raw_payload = c[1].get("payload", c[0][1] if len(c[0]) > 1 else "")
        try:
            payload = json.loads(raw_payload)
        except (ValueError, TypeError):
            payload = raw_payload
        results.append((topic, payload))
    return results


# ---------------------------------------------------------------------------
# Test 1: End-to-end OTA happy path
# Validates: Requirements 1.1-1.6, 2.1-2.5, 3.1-3.5, 5.1-5.3, 6.1-6.5, 7.1-7.3
# ---------------------------------------------------------------------------

class TestEndToEndOTAFlow:
    """Full happy-path integration test for the OTA pipeline."""

    def test_end_to_end_ota_flow(self, tmp_path):
        """End-to-end: notification -> download -> verify -> backup -> apply -> health check -> SUCCEEDED.

        Steps:
        1. Create a temp "target" file (simulating current zumi_iot.py on device)
        2. Create a temp "artifact" file (the new version)
        3. Create an OTAAgent with mocked MQTT connection
        4. Build a valid job notification payload with correct SHA-256 and file size
        5. Mock _download_artifact to copy the artifact to staging
        6. Mock _restart_and_health_check to return True
        7. Mock subprocess.call for systemctl
        8. Send the notification to the agent
        9. Verify: IN_PROGRESS was reported, file was updated, SUCCEEDED was reported
        """
        # Step 1: Create the "current" target file on the device
        target_dir = tmp_path / "device"
        target_dir.mkdir()
        target_file = target_dir / "config_module.py"  # non-self-update name
        original_content = "# Original version v1.0\nprint('hello')\n"
        target_file.write_text(original_content)
        os.chmod(str(target_file), 0o644)

        # Step 2: Create the new artifact content
        new_content = b"# Updated version v2.0\nprint('hello updated')\n"
        artifact_sha256 = _compute_sha256(new_content)
        artifact_size = len(new_content)

        # Step 3: Create agent with temp directories
        staging_dir = str(tmp_path / "staging")
        backup_dir = str(tmp_path / "backup") + "/"
        agent, mock_conn = _make_agent(
            staging_dir=staging_dir,
            backup_dir=backup_dir,
        )

        # Step 4: Build the job notification payload
        job_id = "ota-integration-test-001"
        job_document = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [
                {
                    "url": "https://s3.example.com/ota/integration-zumi/artifact.py?sig=abc",
                    "target_path": str(target_file),
                    "file_size": artifact_size,
                    "sha256": artifact_sha256,
                }
            ],
            "post_action": "restart_service",
        }
        payload = _build_notification_payload(job_id, job_document)

        # Step 5: Mock _download_artifact to copy artifact content to staging
        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(new_content)

        # Steps 6-8: Send the notification with mocks in place
        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch.object(agent, '_restart_and_health_check', return_value=True), \
             patch("ota_agent.subprocess.call"):
            agent._on_job_notification(
                topic="$aws/things/integration-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )

        # Step 9: Verify results
        publishes = _collect_publishes(mock_conn)

        # Should have at least 2 publishes: IN_PROGRESS and SUCCEEDED
        assert len(publishes) >= 2, (
            "Expected at least 2 publishes (IN_PROGRESS + SUCCEEDED), got %d"
            % len(publishes)
        )

        # First publish should be IN_PROGRESS
        in_progress_topic, in_progress_payload = publishes[0]
        assert "update" in in_progress_topic
        assert in_progress_payload["status"] == "IN_PROGRESS"

        # Last publish should be SUCCEEDED
        succeeded_topic, succeeded_payload = publishes[-1]
        assert "update" in succeeded_topic
        assert succeeded_payload["status"] == "SUCCEEDED"

        # SUCCEEDED detail should contain files_updated and artifact_sha256
        details = succeeded_payload.get("statusDetails", {})
        assert str(target_file) in details.get("files_updated", [])
        assert details.get("artifact_sha256") == artifact_sha256
        assert "timestamp" in details

        # Target file should now contain the new content
        with open(str(target_file), "rb") as f:
            assert f.read() == new_content

        # Backup should exist with manifest
        manifest_path = os.path.join(backup_dir, "manifest.json")
        assert os.path.isfile(manifest_path)


# ---------------------------------------------------------------------------
# Test 2: Rollback on bad update (hash mismatch)
# Validates: Requirements 3.2, 4.1-4.6, 7.2, 10.6, 10.7
# ---------------------------------------------------------------------------

class TestRollbackOnBadUpdate:
    """Test that a bad update (wrong SHA-256) triggers failure and preserves original file."""

    def test_rollback_on_bad_update(self, tmp_path):
        """Bad update with wrong SHA-256 hash: FAILED reported, original file unchanged.

        Steps:
        1. Create a temp target file with known content
        2. Build a job notification with WRONG SHA-256 hash
        3. Mock _download_artifact to write a file with different content
        4. Send the notification
        5. Verify: FAILED was reported with "verify_hash" step
        6. Verify: original file content is unchanged (staged file was discarded)
        """
        # Step 1: Create the target file
        target_dir = tmp_path / "device"
        target_dir.mkdir()
        target_file = target_dir / "config_module.py"
        original_content = b"# Original safe version\nprint('safe')\n"
        with open(str(target_file), "wb") as f:
            f.write(original_content)
        os.chmod(str(target_file), 0o644)

        # Step 2: Build payload with WRONG hash
        bad_artifact_content = b"# Corrupted artifact\nprint('bad')\n"
        wrong_sha256 = "0" * 64  # deliberately wrong hash

        staging_dir = str(tmp_path / "staging")
        backup_dir = str(tmp_path / "backup") + "/"
        agent, mock_conn = _make_agent(
            staging_dir=staging_dir,
            backup_dir=backup_dir,
        )

        job_id = "ota-bad-update-001"
        job_document = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [
                {
                    "url": "https://s3.example.com/ota/bad-artifact.py?sig=xyz",
                    "target_path": str(target_file),
                    "file_size": len(bad_artifact_content),
                    "sha256": wrong_sha256,
                }
            ],
            "post_action": "restart_service",
        }
        payload = _build_notification_payload(job_id, job_document)

        # Step 3: Mock download to write the bad artifact
        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(bad_artifact_content)

        # Step 4: Send the notification
        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch("ota_agent.subprocess.call"):
            agent._on_job_notification(
                topic="$aws/things/integration-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )

        # Step 5: Verify FAILED was reported with verify_hash step
        publishes = _collect_publishes(mock_conn)

        # Should have IN_PROGRESS and FAILED
        assert len(publishes) >= 2

        # Find the FAILED publish
        failed_publishes = [
            (t, p) for t, p in publishes if isinstance(p, dict) and p.get("status") == "FAILED"
        ]
        assert len(failed_publishes) == 1, (
            "Expected exactly 1 FAILED publish, got %d" % len(failed_publishes)
        )

        failed_topic, failed_payload = failed_publishes[0]
        details = failed_payload.get("statusDetails", {})
        assert details.get("step") == "verify_hash"
        assert "hash mismatch" in details.get("reason", "").lower()

        # Step 6: Original file should be unchanged
        with open(str(target_file), "rb") as f:
            assert f.read() == original_content


# ---------------------------------------------------------------------------
# Test 3: Offline device catch-up
# Validates: Requirements 2.1, 2.5
# ---------------------------------------------------------------------------

class TestOfflineDeviceCatchUp:
    """Test that a device reconnecting picks up pending jobs via notify-next.

    The notify-next topic automatically delivers pending jobs when the
    device reconnects. This test documents that behavior by:
    1. Creating an OTAAgent and calling start()
    2. Simulating receiving a job notification (as if the device just reconnected)
    3. Verifying the job is processed normally
    """

    def test_offline_device_catch_up(self, tmp_path):
        """Offline catch-up: start() subscribes, then pending job is processed on reconnect.

        This is functionally the same as the happy-path test, but documents
        the reconnection behavior: the notify-next topic delivers pending
        jobs automatically when the device reconnects to MQTT (Req 2.5).
        """
        # Create target file
        target_dir = tmp_path / "device"
        target_dir.mkdir()
        target_file = target_dir / "config_module.py"
        original_content = b"# Pre-offline version\nprint('old')\n"
        with open(str(target_file), "wb") as f:
            f.write(original_content)
        os.chmod(str(target_file), 0o644)

        # New artifact that was queued while device was offline
        new_content = b"# Post-offline version\nprint('new')\n"
        artifact_sha256 = _compute_sha256(new_content)

        staging_dir = str(tmp_path / "staging")
        backup_dir = str(tmp_path / "backup") + "/"
        agent, mock_conn = _make_agent(
            staging_dir=staging_dir,
            backup_dir=backup_dir,
        )

        # Step 1: Call start() — this subscribes to notify-next (Req 2.1)
        agent.start()

        # Verify subscription happened
        mock_conn.subscribe.assert_called_once()
        subscribe_call = mock_conn.subscribe.call_args
        assert subscribe_call[1]["topic"] == "$aws/things/integration-zumi/jobs/notify-next"

        # Step 2: Capture the callback that was registered
        registered_callback = subscribe_call[1]["callback"]

        # Step 3: Build the pending job notification (queued while offline)
        job_id = "ota-offline-catchup-001"
        job_document = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [
                {
                    "url": "https://s3.example.com/ota/offline-artifact.py?sig=def",
                    "target_path": str(target_file),
                    "file_size": len(new_content),
                    "sha256": artifact_sha256,
                }
            ],
            "post_action": "restart_service",
        }
        payload = _build_notification_payload(job_id, job_document)

        def fake_download(url, staging_path):
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "wb") as f:
                f.write(new_content)

        # Step 4: Simulate the reconnection — IoT Core delivers the pending job
        # by calling the registered callback (same as notify-next delivery)
        with patch.object(agent, '_download_artifact', side_effect=fake_download), \
             patch.object(agent, '_restart_and_health_check', return_value=True), \
             patch("ota_agent.subprocess.call"):
            registered_callback(
                topic="$aws/things/integration-zumi/jobs/notify-next",
                payload=payload,
                dup=False, qos=1, retain=False,
            )

        # Step 5: Verify the job was processed normally
        publishes = _collect_publishes(mock_conn)

        # Should have IN_PROGRESS and SUCCEEDED
        assert len(publishes) >= 2

        statuses = [p.get("status") for _, p in publishes if isinstance(p, dict)]
        assert "IN_PROGRESS" in statuses
        assert "SUCCEEDED" in statuses

        # Target file should be updated
        with open(str(target_file), "rb") as f:
            assert f.read() == new_content
