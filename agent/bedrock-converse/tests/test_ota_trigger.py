"""Unit tests for ota_trigger.py — job document builder, parser, and OTATriggerError."""

import pytest

from ota_trigger import (
    JOB_DOCUMENT_VERSION,
    OTATriggerError,
    build_job_document,
    parse_job_document,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_artifact(**overrides):
    """Return a minimal valid artifact descriptor, with optional overrides."""
    base = {
        "url": "https://s3.amazonaws.com/bucket/ota/thing/ts-hash/file.py?X-Amz-Sig=abc",
        "target_path": "/home/pi/zumi-iot/zumi_iot.py",
        "file_size": 15234,
        "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    }
    base.update(overrides)
    return base


def _make_codesign(**overrides):
    """Return a minimal valid codesign object."""
    base = {
        "signature": "c2lnbmF0dXJl",
        "signing_profile": "zumi-ota-signer",
        "algorithm": "RSA-SHA256",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# OTATriggerError
# ---------------------------------------------------------------------------

class TestOTATriggerError:
    def test_is_exception(self):
        assert issubclass(OTATriggerError, Exception)

    def test_message(self):
        err = OTATriggerError("S3 upload failed")
        assert str(err) == "S3 upload failed"


# ---------------------------------------------------------------------------
# build_job_document
# ---------------------------------------------------------------------------

class TestBuildJobDocument:
    def test_minimal_artifact(self):
        art = _make_artifact()
        doc = build_job_document([art])
        assert doc["version"] == JOB_DOCUMENT_VERSION
        assert doc["operation"] == "update_files"
        assert doc["post_action"] == "restart_service"
        assert len(doc["artifacts"]) == 1
        assert doc["artifacts"][0]["url"] == art["url"]
        assert doc["artifacts"][0]["sha256"] == art["sha256"]

    def test_custom_post_action(self):
        doc = build_job_document([_make_artifact()], post_action="reboot")
        assert doc["post_action"] == "reboot"

    def test_multiple_artifacts(self):
        arts = [_make_artifact(target_path=f"/home/pi/file{i}.py") for i in range(3)]
        doc = build_job_document(arts)
        assert len(doc["artifacts"]) == 3

    def test_artifact_with_codesign(self):
        art = _make_artifact(codesign=_make_codesign())
        doc = build_job_document([art])
        cs = doc["artifacts"][0]["codesign"]
        assert cs["signature"] == "c2lnbmF0dXJl"
        assert cs["signing_profile"] == "zumi-ota-signer"
        assert cs["algorithm"] == "RSA-SHA256"

    def test_artifact_without_codesign_omits_key(self):
        doc = build_job_document([_make_artifact()])
        assert "codesign" not in doc["artifacts"][0]

    def test_empty_artifacts_raises(self):
        with pytest.raises(ValueError, match="artifacts list must not be empty"):
            build_job_document([])

    def test_missing_artifact_field_raises(self):
        art = _make_artifact()
        del art["sha256"]
        with pytest.raises(ValueError, match="sha256"):
            build_job_document([art])

    def test_missing_multiple_artifact_fields_raises(self):
        art = {"url": "https://example.com/file.py"}
        with pytest.raises(ValueError, match="artifact\\[0\\] is missing required fields"):
            build_job_document([art])


# ---------------------------------------------------------------------------
# parse_job_document
# ---------------------------------------------------------------------------

class TestParseJobDocument:
    def test_valid_document(self):
        doc = build_job_document([_make_artifact()])
        result = parse_job_document(doc)
        assert result["version"] == JOB_DOCUMENT_VERSION
        assert result["operation"] == "update_files"
        assert len(result["artifacts"]) == 1

    def test_round_trip(self):
        """build → parse produces equivalent document."""
        art = _make_artifact(codesign=_make_codesign())
        doc = build_job_document([art], post_action="restart_service")
        parsed = parse_job_document(doc)
        assert parsed == doc

    def test_not_a_dict_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            parse_job_document("not a dict")

    def test_unsupported_version_raises(self):
        doc = build_job_document([_make_artifact()])
        doc["version"] = "99.0"
        with pytest.raises(ValueError, match="unsupported job document version.*99.0"):
            parse_job_document(doc)

    def test_missing_top_level_field_raises(self):
        doc = build_job_document([_make_artifact()])
        del doc["post_action"]
        with pytest.raises(ValueError, match="post_action"):
            parse_job_document(doc)

    def test_missing_multiple_top_level_fields(self):
        doc = {"version": "1.0"}
        with pytest.raises(ValueError, match="missing required fields"):
            parse_job_document(doc)

    def test_artifacts_not_a_list_raises(self):
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": "not-a-list",
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError, match="'artifacts' must be a list"):
            parse_job_document(doc)

    def test_empty_artifacts_raises(self):
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [],
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError, match="must not be empty"):
            parse_job_document(doc)

    def test_artifact_not_a_dict_raises(self):
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": ["not-a-dict"],
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError, match="artifact\\[0\\] must be a dict"):
            parse_job_document(doc)

    def test_artifact_missing_field_raises(self):
        art = _make_artifact()
        del art["file_size"]
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [art],
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError, match="file_size"):
            parse_job_document(doc)

    def test_codesign_present_and_valid(self):
        art = _make_artifact(codesign=_make_codesign())
        doc = build_job_document([art])
        result = parse_job_document(doc)
        assert "codesign" in result["artifacts"][0]

    def test_codesign_not_a_dict_raises(self):
        art = _make_artifact(codesign="bad")
        doc = build_job_document([art])
        # build_job_document passes codesign through; parse should catch it
        with pytest.raises(ValueError, match="codesign must be a dict"):
            parse_job_document(doc)

    def test_codesign_missing_field_raises(self):
        cs = _make_codesign()
        del cs["algorithm"]
        art = _make_artifact(codesign=cs)
        doc = build_job_document([art])
        with pytest.raises(ValueError, match="algorithm"):
            parse_job_document(doc)

    def test_multiple_artifacts_second_invalid(self):
        good = _make_artifact()
        bad = {"url": "https://example.com/file.py"}
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [good, bad],
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError, match="artifact\\[1\\]"):
            parse_job_document(doc)

    def test_error_message_lists_all_missing_fields(self):
        """Verify the error message includes every missing field name."""
        doc = {
            "version": "1.0",
            "operation": "update_files",
            "artifacts": [{"url": "https://example.com"}],
            "post_action": "restart_service",
        }
        with pytest.raises(ValueError) as exc_info:
            parse_job_document(doc)
        msg = str(exc_info.value)
        for field in ("file_size", "sha256", "target_path"):
            assert field in msg


import json
import os
import tempfile
import hashlib
from unittest.mock import patch, MagicMock

from botocore.exceptions import ClientError

from ota_trigger import trigger_ota, _compute_sha256


# ---------------------------------------------------------------------------
# _compute_sha256
# ---------------------------------------------------------------------------

class TestComputeSha256:
    def test_known_content(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert _compute_sha256(str(f)) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert _compute_sha256(str(f)) == expected


# ---------------------------------------------------------------------------
# trigger_ota
# ---------------------------------------------------------------------------

class TestTriggerOta:
    """Tests for the trigger_ota function with mocked AWS services."""

    def _make_temp_file(self, tmp_path, content=b"print('hello')"):
        """Create a temp file and return its path."""
        f = tmp_path / "zumi_iot.py"
        f.write_bytes(content)
        return str(f)

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_happy_path(self, mock_boto3, mock_account, tmp_path):
        """Upload + create_job succeeds and returns job_id and job_arn."""
        file_path = self._make_temp_file(tmp_path)

        # Mock S3 client
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"

        # Mock IoT client
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        result = trigger_ota(file_path, "test-thing")

        assert "job_id" in result
        assert "job_arn" in result
        assert result["job_arn"] == "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345"

        # Verify S3 upload was called
        mock_s3.upload_file.assert_called_once()
        # Verify presigned URL was generated
        mock_s3.generate_presigned_url.assert_called_once()
        # Verify job document was uploaded
        mock_s3.put_object.assert_called_once()
        # Verify create_job was called
        mock_iot.create_job.assert_called_once()

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_artifact_s3_key_format(self, mock_boto3, mock_account, tmp_path):
        """Artifact is uploaded to the correct S3 key pattern."""
        content = b"test content"
        file_path = self._make_temp_file(tmp_path, content)
        expected_hash = hashlib.sha256(content).hexdigest()
        hash_prefix = expected_hash[:8]

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(file_path, "test-thing")

        # Check the S3 key used for upload
        upload_call = mock_s3.upload_file.call_args
        s3_key = upload_call[0][2]  # third positional arg is the key
        assert s3_key.startswith("ota/test-thing/")
        assert hash_prefix in s3_key
        assert s3_key.endswith("/zumi_iot.py")

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_job_document_uploaded_to_s3(self, mock_boto3, mock_account, tmp_path):
        """Job document JSON is uploaded to S3 with correct content."""
        content = b"test content"
        file_path = self._make_temp_file(tmp_path, content)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(file_path, "test-thing")

        # Verify job document was uploaded
        put_call = mock_s3.put_object.call_args
        body = put_call[1]["Body"]
        doc = json.loads(body)
        assert doc["version"] == "1.0"
        assert doc["operation"] == "update_files"
        assert doc["post_action"] == "restart_service"
        assert len(doc["artifacts"]) == 1
        assert doc["artifacts"][0]["sha256"] == hashlib.sha256(content).hexdigest()
        assert doc["artifacts"][0]["target_path"] == "/home/pi/zumi-iot/zumi_iot.py"

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_create_job_targets_correct_thing(self, mock_boto3, mock_account, tmp_path):
        """create_job is called with the correct thing ARN target."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-my-zumi-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-my-zumi-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(file_path, "my-zumi")

        create_call = mock_iot.create_job.call_args
        targets = create_call[1]["targets"]
        assert len(targets) == 1
        assert "thing/my-zumi" in targets[0]

    def test_file_not_found_raises(self):
        """Raises FileNotFoundError when the artifact file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Artifact file not found"):
            trigger_ota("/nonexistent/path/file.py", "test-thing")

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_s3_upload_failure_raises_ota_error(self, mock_boto3, mock_account, tmp_path):
        """Raises OTATriggerError when S3 artifact upload fails."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "The specified bucket does not exist"}},
            "PutObject",
        )

        mock_boto3.client.side_effect = lambda service, **kw: mock_s3 if service == "s3" else MagicMock()

        with pytest.raises(OTATriggerError, match="Failed to upload artifact to S3"):
            trigger_ota(file_path, "test-thing")

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_job_doc_upload_failure_raises_ota_error(self, mock_boto3, mock_account, tmp_path):
        """Raises OTATriggerError when S3 job document upload fails."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "PutObject",
        )

        mock_boto3.client.side_effect = lambda service, **kw: mock_s3 if service == "s3" else MagicMock()

        with pytest.raises(OTATriggerError, match="Failed to upload job document to S3"):
            trigger_ota(file_path, "test-thing")

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_create_job_failure_raises_ota_error(self, mock_boto3, mock_account, tmp_path):
        """Raises OTATriggerError when create_job API call fails."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Thing not found"}},
            "CreateJob",
        )

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        with pytest.raises(OTATriggerError, match="Failed to create IoT Job"):
            trigger_ota(file_path, "test-thing")

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_custom_target_path_and_post_action(self, mock_boto3, mock_account, tmp_path):
        """Custom target_path and post_action are passed through to the job document."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(
            file_path,
            "test-thing",
            target_path="/home/pi/custom/path.py",
            post_action="reboot",
        )

        put_call = mock_s3.put_object.call_args
        doc = json.loads(put_call[1]["Body"])
        assert doc["artifacts"][0]["target_path"] == "/home/pi/custom/path.py"
        assert doc["post_action"] == "reboot"

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_presigned_url_expiry_from_config(self, mock_boto3, mock_account, tmp_path):
        """Presigned URL uses the expiry from config.OTA_PRESIGN_EXPIRY."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(file_path, "test-thing")

        presign_call = mock_s3.generate_presigned_url.call_args
        assert presign_call[1]["ExpiresIn"] == 3600  # default OTA_PRESIGN_EXPIRY

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_job_id_format(self, mock_boto3, mock_account, tmp_path):
        """Job ID follows the pattern ota-{thing_name}-{timestamp}."""
        file_path = self._make_temp_file(tmp_path)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-my-zumi-99999",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-my-zumi-99999",
        }

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        trigger_ota(file_path, "my-zumi")

        create_call = mock_iot.create_job.call_args
        job_id = create_call[1]["jobId"]
        assert job_id.startswith("ota-my-zumi-")


from ota_trigger import get_job_status
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    """Tests for the get_job_status function with mocked AWS IoT client."""

    @patch("ota_trigger.boto3")
    def test_happy_path_full_response(self, mock_boto3):
        """describe_job_execution returns a full response with status, details, and timestamps."""
        started = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        updated = datetime(2025, 1, 15, 10, 35, 0, tzinfo=timezone.utc)
        queued = datetime(2025, 1, 15, 10, 29, 0, tzinfo=timezone.utc)

        mock_iot = MagicMock()
        mock_iot.describe_job_execution.return_value = {
            "execution": {
                "status": "SUCCEEDED",
                "statusDetails": {
                    "version": "1.0",
                    "files_updated": '["/home/pi/zumi-iot/zumi_iot.py"]',
                    "artifact_sha256": "a1b2c3d4",
                },
                "startedAt": started,
                "lastUpdatedAt": updated,
                "queuedAt": queued,
            }
        }
        mock_boto3.client.return_value = mock_iot

        result = get_job_status("ota-test-thing-12345", "test-thing")

        assert result["status"] == "SUCCEEDED"
        # "1.0" is valid JSON → parsed to float 1.0
        assert result["status_detail"]["version"] == 1.0
        # JSON string values should be parsed
        assert result["status_detail"]["files_updated"] == ["/home/pi/zumi-iot/zumi_iot.py"]
        assert result["status_detail"]["artifact_sha256"] == "a1b2c3d4"
        assert result["started_at"] == started.isoformat()
        assert result["last_updated_at"] == updated.isoformat()
        assert result["queued_at"] == queued.isoformat()

        mock_iot.describe_job_execution.assert_called_once_with(
            jobId="ota-test-thing-12345",
            thingName="test-thing",
        )

    @patch("ota_trigger.boto3")
    def test_api_failure_raises_ota_error(self, mock_boto3):
        """describe_job_execution raises ClientError → should raise OTATriggerError."""
        mock_iot = MagicMock()
        mock_iot.describe_job_execution.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Job not found"}},
            "DescribeJobExecution",
        )
        mock_boto3.client.return_value = mock_iot

        with pytest.raises(OTATriggerError, match="Failed to describe job execution"):
            get_job_status("nonexistent-job", "test-thing")

    @patch("ota_trigger.boto3")
    def test_missing_optional_fields(self, mock_boto3):
        """Response without statusDetails or timestamps returns None/empty dict."""
        mock_iot = MagicMock()
        mock_iot.describe_job_execution.return_value = {
            "execution": {
                "status": "QUEUED",
            }
        }
        mock_boto3.client.return_value = mock_iot

        result = get_job_status("ota-test-thing-12345", "test-thing")

        assert result["status"] == "QUEUED"
        assert result["status_detail"] == {}
        assert result["started_at"] is None
        assert result["last_updated_at"] is None
        assert result["queued_at"] is None

    @patch("ota_trigger.boto3")
    def test_status_detail_json_parsing(self, mock_boto3):
        """statusDetails values that are JSON strings should be parsed."""
        mock_iot = MagicMock()
        mock_iot.describe_job_execution.return_value = {
            "execution": {
                "status": "FAILED",
                "statusDetails": {
                    "reason": "SHA-256 hash mismatch",
                    "step": "verify_hash",
                    "rollback_performed": "true",
                    "nested_data": '{"key": "value", "count": 42}',
                },
                "startedAt": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
                "lastUpdatedAt": datetime(2025, 1, 15, 10, 33, 0, tzinfo=timezone.utc),
            }
        }
        mock_boto3.client.return_value = mock_iot

        result = get_job_status("ota-test-thing-12345", "test-thing")

        assert result["status"] == "FAILED"
        # Plain strings that aren't valid JSON stay as strings
        assert result["status_detail"]["reason"] == "SHA-256 hash mismatch"
        assert result["status_detail"]["step"] == "verify_hash"
        # "true" is valid JSON → parsed to Python bool
        assert result["status_detail"]["rollback_performed"] is True
        # JSON object string → parsed to dict
        assert result["status_detail"]["nested_data"] == {"key": "value", "count": 42}

    @patch("ota_trigger.boto3")
    def test_empty_execution_object(self, mock_boto3):
        """Response with empty execution object returns defaults."""
        mock_iot = MagicMock()
        mock_iot.describe_job_execution.return_value = {
            "execution": {}
        }
        mock_boto3.client.return_value = mock_iot

        result = get_job_status("ota-test-thing-12345", "test-thing")

        assert result["status"] == "UNKNOWN"
        assert result["status_detail"] == {}
        assert result["started_at"] is None
        assert result["last_updated_at"] is None
        assert result["queued_at"] is None

    @patch("ota_trigger.boto3")
    def test_no_execution_key_in_response(self, mock_boto3):
        """Response without 'execution' key returns defaults."""
        mock_iot = MagicMock()
        mock_iot.describe_job_execution.return_value = {}
        mock_boto3.client.return_value = mock_iot

        result = get_job_status("ota-test-thing-12345", "test-thing")

        assert result["status"] == "UNKNOWN"
        assert result["status_detail"] == {}
        assert result["started_at"] is None


# ---------------------------------------------------------------------------
# Code Signing — Requirements 12.1, 12.2, 12.3, 12.4
# ---------------------------------------------------------------------------

class TestCodeSigning:
    """Tests for code signing integration in trigger_ota()."""

    def _make_temp_file(self, tmp_path, content=b"print('hello')"):
        """Create a temp file and return its path."""
        f = tmp_path / "zumi_iot.py"
        f.write_bytes(content)
        return str(f)

    def _make_mock_s3(self):
        """Return a mock S3 client with standard happy-path behaviour."""
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
        # get_object for reading the signed artifact (signature retrieval)
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake-signature-bytes")),
        }
        return mock_s3

    def _make_mock_iot(self):
        """Return a mock IoT client with standard happy-path behaviour."""
        mock_iot = MagicMock()
        mock_iot.create_job.return_value = {
            "jobId": "ota-test-thing-12345",
            "jobArn": "arn:aws:iot:us-east-1:123456789012:job/ota-test-thing-12345",
        }
        return mock_iot

    def _make_mock_signer(self, status="Succeeded", signature_b64="", signed_key="signed/artifact.py"):
        """Return a mock Signer client.

        Args:
            status: The signing job status returned by describe_signing_job.
            signature_b64: If non-empty, returned as the top-level 'signature' field.
            signed_key: The S3 key of the signed object.
        """
        mock_signer = MagicMock()
        mock_signer.start_signing_job.return_value = {"jobId": "signer-job-001"}
        mock_signer.describe_signing_job.return_value = {
            "status": status,
            "signature": signature_b64,
            "signedObject": {"s3": {"key": signed_key}},
            "statusReason": "Signing failed" if status == "Failed" else "",
        }
        return mock_signer

    def _client_factory(self, mock_s3, mock_iot, mock_signer):
        """Return a boto3.client side_effect that dispatches by service name."""
        def factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            elif service == "signer":
                return mock_signer
            elif service == "sts":
                mock_sts = MagicMock()
                mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
                return mock_sts
            return MagicMock()
        return factory

    @patch("ota_trigger.time.sleep", return_value=None)
    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_signing_happy_path(self, mock_boto3, mock_account, mock_sleep, tmp_path):
        """When signing_profile is provided, trigger_ota signs the artifact and
        includes a codesign object with signature, signing_profile, and algorithm
        in the job document uploaded to S3.

        Validates: Requirements 12.1, 12.2
        """
        file_path = self._make_temp_file(tmp_path)
        mock_s3 = self._make_mock_s3()
        mock_iot = self._make_mock_iot()
        mock_signer = self._make_mock_signer()
        mock_boto3.client.side_effect = self._client_factory(mock_s3, mock_iot, mock_signer)

        result = trigger_ota(file_path, "test-thing", signing_profile="zumi-ota-signer")

        # Signing job was started with the correct S3 source
        mock_signer.start_signing_job.assert_called_once()
        start_call = mock_signer.start_signing_job.call_args
        source_s3 = start_call[1]["source"]["s3"]
        assert source_s3["bucketName"] == "zumi-chatbot-photos"
        assert source_s3["key"].startswith("ota/test-thing/")
        assert start_call[1]["profileName"] == "zumi-ota-signer"

        # Signing job was polled
        mock_signer.describe_signing_job.assert_called_once_with(jobId="signer-job-001")

        # Job document includes codesign object
        put_call = mock_s3.put_object.call_args
        doc = json.loads(put_call[1]["Body"])
        codesign = doc["artifacts"][0]["codesign"]
        assert "signature" in codesign
        assert codesign["signature"]  # non-empty
        assert codesign["signing_profile"] == "zumi-ota-signer"
        assert codesign["algorithm"] == "RSA-SHA256"

        # Job was created successfully
        assert "job_id" in result
        assert "job_arn" in result

    @patch("ota_trigger.time.sleep", return_value=None)
    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_signing_failure_raises_ota_error(self, mock_boto3, mock_account, mock_sleep, tmp_path):
        """When the signing job fails (status 'Failed'), trigger_ota raises
        OTATriggerError without creating an IoT Job.

        Validates: Requirements 12.4
        """
        file_path = self._make_temp_file(tmp_path)
        mock_s3 = self._make_mock_s3()
        mock_iot = self._make_mock_iot()
        mock_signer = self._make_mock_signer(status="Failed")
        mock_boto3.client.side_effect = self._client_factory(mock_s3, mock_iot, mock_signer)

        with pytest.raises(OTATriggerError, match="Signing job .* failed"):
            trigger_ota(file_path, "test-thing", signing_profile="zumi-ota-signer")

        # IoT Job should NOT have been created
        mock_iot.create_job.assert_not_called()

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_no_codesign_when_signing_profile_none(self, mock_boto3, mock_account, tmp_path):
        """When signing_profile is None and config.OTA_SIGNING_PROFILE is empty,
        no codesign object should be in the job document.

        Validates: Requirements 12.3
        """
        file_path = self._make_temp_file(tmp_path)
        mock_s3 = self._make_mock_s3()
        mock_iot = self._make_mock_iot()

        def factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            elif service == "iot":
                return mock_iot
            return MagicMock()

        mock_boto3.client.side_effect = factory

        # config.OTA_SIGNING_PROFILE defaults to "" — no signing
        with patch("ota_trigger.config") as mock_config:
            mock_config.OTA_S3_PREFIX = "ota"
            mock_config.OTA_PRESIGN_EXPIRY = 3600
            mock_config.OTA_SIGNING_PROFILE = ""
            mock_config.S3_BUCKET = "zumi-chatbot-photos"
            mock_config.S3_REGION = "us-east-1"
            mock_config.IOT_REGION = "us-east-1"

            trigger_ota(file_path, "test-thing", signing_profile=None)

        # Job document should NOT contain a codesign object
        put_call = mock_s3.put_object.call_args
        doc = json.loads(put_call[1]["Body"])
        assert "codesign" not in doc["artifacts"][0]

        # No signer client should have been created — verify by checking
        # that no 'signer' service was requested
        for call in mock_boto3.client.call_args_list:
            service_arg = call[0][0] if call[0] else call[1].get("service", "")
            assert service_arg != "signer", "Signer client should not be created when signing is skipped"

    @patch("ota_trigger.time.sleep", return_value=None)
    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_signing_from_config_default(self, mock_boto3, mock_account, mock_sleep, tmp_path):
        """When signing_profile is None but config.OTA_SIGNING_PROFILE is set
        to a non-empty string, signing should be performed using the config value.

        Validates: Requirements 12.3
        """
        file_path = self._make_temp_file(tmp_path)
        mock_s3 = self._make_mock_s3()
        mock_iot = self._make_mock_iot()
        mock_signer = self._make_mock_signer()
        mock_boto3.client.side_effect = self._client_factory(mock_s3, mock_iot, mock_signer)

        with patch("ota_trigger.config") as mock_config:
            mock_config.OTA_S3_PREFIX = "ota"
            mock_config.OTA_PRESIGN_EXPIRY = 3600
            mock_config.OTA_SIGNING_PROFILE = "config-default-profile"
            mock_config.S3_BUCKET = "zumi-chatbot-photos"
            mock_config.S3_REGION = "us-east-1"
            mock_config.IOT_REGION = "us-east-1"

            trigger_ota(file_path, "test-thing", signing_profile=None)

        # Signer should have been called with the config profile name
        mock_signer.start_signing_job.assert_called_once()
        start_call = mock_signer.start_signing_job.call_args
        assert start_call[1]["profileName"] == "config-default-profile"

        # Job document should contain codesign with the config profile
        put_call = mock_s3.put_object.call_args
        doc = json.loads(put_call[1]["Body"])
        codesign = doc["artifacts"][0]["codesign"]
        assert codesign["signing_profile"] == "config-default-profile"

    @patch("ota_trigger._get_account_id", return_value="123456789012")
    @patch("ota_trigger.boto3")
    def test_start_signing_job_failure(self, mock_boto3, mock_account, tmp_path):
        """When start_signing_job raises ClientError, trigger_ota raises
        OTATriggerError without creating an IoT Job.

        Validates: Requirements 12.4
        """
        file_path = self._make_temp_file(tmp_path)
        mock_s3 = self._make_mock_s3()
        mock_iot = self._make_mock_iot()
        mock_signer = MagicMock()
        mock_signer.start_signing_job.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Signing profile not found"}},
            "StartSigningJob",
        )
        mock_boto3.client.side_effect = self._client_factory(mock_s3, mock_iot, mock_signer)

        with pytest.raises(OTATriggerError, match="Failed to start signing job"):
            trigger_ota(file_path, "test-thing", signing_profile="nonexistent-profile")

        # IoT Job should NOT have been created
        mock_iot.create_job.assert_not_called()
