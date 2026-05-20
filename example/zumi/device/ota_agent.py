"""
OTA Agent for Zumi IoT
~~~~~~~~~~~~~~~~~~~~~~
Device-side OTA update agent using AWS IoT Jobs.

Subscribes to IoT Jobs MQTT topics, receives job notifications,
and processes OTA updates (download, verify, apply, rollback).

This module shares the existing MQTT connection from zumi_iot.py
to avoid duplicate TLS connections on the Pi Zero W.

Python 3.5.3 compatible — no f-strings, no dataclasses.
"""

import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time

try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
except ImportError:
    # Python 2 fallback (not expected on Zumi, but safe)
    from urllib2 import urlopen, Request, HTTPError, URLError

from awscrt import mqtt

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("zumi-iot.ota")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Job Document Parser (device-side)
# ---------------------------------------------------------------------------

def parse_job_document(raw_json_str):
    """Parse and validate job document JSON string.

    Returns dict on success.
    Raises ValueError with descriptive message on:
      - Invalid JSON
      - Unsupported version
      - Missing required fields

    Python 3.5.3 compatible — catches (ValueError, TypeError)
    instead of json.JSONDecodeError.
    """
    # Parse JSON
    try:
        if isinstance(raw_json_str, bytes):
            raw_json_str = raw_json_str.decode("utf-8")
        doc = json.loads(raw_json_str)
    except (ValueError, TypeError) as e:
        raise ValueError("Invalid JSON in job document: %s" % str(e))

    if not isinstance(doc, dict):
        raise ValueError("Job document must be a JSON object, got %s" % type(doc).__name__)

    # Validate top-level required fields
    required_top = ["version", "operation", "artifacts", "post_action"]
    missing_top = [f for f in required_top if f not in doc]
    if missing_top:
        raise ValueError("Job document missing required fields: %s" % ", ".join(missing_top))

    # Validate version
    if doc["version"] != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported job document version: %s (expected %s)"
            % (doc["version"], SUPPORTED_SCHEMA_VERSION)
        )

    # Validate artifacts is a list
    if not isinstance(doc["artifacts"], list):
        raise ValueError("Job document 'artifacts' must be a list")

    if len(doc["artifacts"]) == 0:
        raise ValueError("Job document 'artifacts' must not be empty")

    # Validate each artifact descriptor
    required_artifact = ["url", "target_path", "file_size", "sha256"]
    for i, artifact in enumerate(doc["artifacts"]):
        if not isinstance(artifact, dict):
            raise ValueError("Artifact %d must be a JSON object" % i)
        missing_art = [f for f in required_artifact if f not in artifact]
        if missing_art:
            raise ValueError(
                "Artifact %d missing required fields: %s"
                % (i, ", ".join(missing_art))
            )

    return doc


# ---------------------------------------------------------------------------
# Lightweight RSA-SHA256 PKCS#1 v1.5 Signature Verification
# ---------------------------------------------------------------------------
# Python 3.5.3 compatible — uses only base64, hashlib, and standard lib.
# No third-party crypto libraries required.
#
# This implements just enough RSA math to verify a PKCS#1 v1.5 signature
# using a PEM-encoded RSA public key. It is NOT a general-purpose crypto
# library — it is intentionally minimal for the OTA verification use case.
# ---------------------------------------------------------------------------

# ASN.1 DER prefix for SHA-256 DigestInfo (fixed for RSA-SHA256)
_SHA256_DIGEST_INFO_PREFIX = (
    b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01"
    b"\x05\x00\x04\x20"
)


def _decode_pem_public_key(pem_data):
    """Decode a PEM-encoded RSA public key to DER bytes.

    Supports both PKCS#8 (BEGIN PUBLIC KEY) and PKCS#1
    (BEGIN RSA PUBLIC KEY) formats.

    Args:
        pem_data: bytes — PEM file contents.

    Returns:
        bytes — DER-encoded key data.
    """
    pem_str = pem_data.decode("ascii")
    lines = pem_str.strip().splitlines()
    # Strip header/footer lines
    b64_lines = [
        line for line in lines
        if not line.startswith("-----")
    ]
    return base64.b64decode("".join(b64_lines))


def _parse_asn1_length(data, offset):
    """Parse an ASN.1 DER length field.

    Returns (length, new_offset).
    """
    first = data[offset] if isinstance(data[offset], int) else ord(data[offset])
    if first < 0x80:
        return first, offset + 1
    num_bytes = first & 0x7f
    length = 0
    for i in range(num_bytes):
        b = data[offset + 1 + i]
        if not isinstance(b, int):
            b = ord(b)
        length = (length << 8) | b
    return length, offset + 1 + num_bytes


def _parse_asn1_integer(data, offset):
    """Parse an ASN.1 DER INTEGER at the given offset.

    Returns (int_value, new_offset).
    """
    tag = data[offset] if isinstance(data[offset], int) else ord(data[offset])
    if tag != 0x02:
        raise ValueError("Expected ASN.1 INTEGER tag (0x02), got 0x%02x" % tag)
    length, offset = _parse_asn1_length(data, offset + 1)
    int_bytes = data[offset:offset + length]
    # Convert bytes to integer
    value = 0
    for b in int_bytes:
        if not isinstance(b, int):
            b = ord(b)
        value = (value << 8) | b
    return value, offset + length


def _extract_rsa_pubkey_params(der_data):
    """Extract RSA (n, e) from DER-encoded public key.

    Handles both PKCS#8 SubjectPublicKeyInfo and PKCS#1
    RSAPublicKey formats.

    Args:
        der_data: bytes — DER-encoded key.

    Returns:
        (n, e) — RSA modulus and exponent as Python ints.
    """
    # Outer SEQUENCE
    offset = 0
    tag = der_data[offset] if isinstance(der_data[offset], int) else ord(der_data[offset])
    if tag != 0x30:
        raise ValueError("Expected ASN.1 SEQUENCE, got 0x%02x" % tag)
    _, offset = _parse_asn1_length(der_data, offset + 1)

    # Check if this is PKCS#8 (starts with another SEQUENCE for AlgorithmIdentifier)
    inner_tag = der_data[offset] if isinstance(der_data[offset], int) else ord(der_data[offset])

    if inner_tag == 0x30:
        # PKCS#8 SubjectPublicKeyInfo — skip AlgorithmIdentifier SEQUENCE
        _, alg_end = _parse_asn1_length(der_data, offset + 1)
        # Skip the AlgorithmIdentifier content
        alg_length, after_alg_len = _parse_asn1_length(der_data, offset + 1)
        offset = after_alg_len + alg_length

        # Next should be BIT STRING containing the RSA public key
        bit_tag = der_data[offset] if isinstance(der_data[offset], int) else ord(der_data[offset])
        if bit_tag != 0x03:
            raise ValueError("Expected BIT STRING (0x03), got 0x%02x" % bit_tag)
        bit_len, offset = _parse_asn1_length(der_data, offset + 1)
        # Skip the "unused bits" byte
        offset += 1

        # Now we have the inner PKCS#1 RSAPublicKey SEQUENCE
        inner_seq_tag = der_data[offset] if isinstance(der_data[offset], int) else ord(der_data[offset])
        if inner_seq_tag != 0x30:
            raise ValueError("Expected inner SEQUENCE, got 0x%02x" % inner_seq_tag)
        _, offset = _parse_asn1_length(der_data, offset + 1)

    elif inner_tag == 0x02:
        # PKCS#1 RSAPublicKey — already at the INTEGER fields
        pass
    else:
        raise ValueError("Unexpected ASN.1 tag: 0x%02x" % inner_tag)

    # Parse n (modulus) and e (exponent)
    n, offset = _parse_asn1_integer(der_data, offset)
    e, offset = _parse_asn1_integer(der_data, offset)

    return n, e


def _pkcs1_v15_verify_rsa_sha256(pubkey_pem, signature, file_digest):
    """Verify an RSA-SHA256 PKCS#1 v1.5 signature.

    This performs the RSA public-key operation (signature^e mod n)
    and checks that the result matches the expected PKCS#1 v1.5
    padded DigestInfo for SHA-256.

    Args:
        pubkey_pem: bytes — PEM-encoded RSA public key.
        signature: bytes — raw signature bytes (decoded from base64).
        file_digest: bytes — 32-byte SHA-256 digest of the file.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        der_data = _decode_pem_public_key(pubkey_pem)
        n, e = _extract_rsa_pubkey_params(der_data)
    except Exception as exc:
        log.error("Failed to parse RSA public key: %s", exc)
        return False

    # Key size in bytes
    k = (n.bit_length() + 7) // 8

    if len(signature) != k:
        log.error(
            "Signature length %d does not match key size %d",
            len(signature), k
        )
        return False

    # Convert signature bytes to integer
    sig_int = 0
    for b in signature:
        if not isinstance(b, int):
            b = ord(b)
        sig_int = (sig_int << 8) | b

    # RSA public-key operation: m = sig^e mod n
    m = pow(sig_int, e, n)

    # Convert result back to bytes (k bytes, big-endian)
    m_bytes = bytearray(k)
    temp = m
    for i in range(k - 1, -1, -1):
        m_bytes[i] = temp & 0xff
        temp >>= 8

    # Build expected PKCS#1 v1.5 padded message:
    # 0x00 0x01 [0xff padding] 0x00 [DigestInfo]
    digest_info = _SHA256_DIGEST_INFO_PREFIX + file_digest
    pad_len = k - 3 - len(digest_info)
    if pad_len < 8:
        log.error("Key too short for PKCS#1 v1.5 padding")
        return False

    expected = (
        b"\x00\x01"
        + (b"\xff" * pad_len)
        + b"\x00"
        + digest_info
    )

    return bytes(m_bytes) == expected


# ---------------------------------------------------------------------------
# Rollback Manager
# ---------------------------------------------------------------------------

class RollbackManager(object):
    """Manages backup and rollback of files during OTA updates.

    Before an update is applied, the manager copies each target file
    to a backup directory and writes a manifest.json recording the
    original path, backup path, permissions, and timestamp.

    If the update fails, rollback() restores the backed-up files and
    restarts the systemd service.

    Only the most recent backup set is retained to conserve disk space
    on the Pi Zero W (Req 4.6).

    Python 3.5.3 compatible — no f-strings, no dataclasses.
    """

    BACKUP_DIR = "/home/pi/zumi-iot/.ota-backup/"

    def __init__(self, backup_dir=None):
        """Initialize the RollbackManager.

        Args:
            backup_dir: Path to the backup directory. Defaults to
                BACKUP_DIR (/home/pi/zumi-iot/.ota-backup/).
        """
        if backup_dir is not None:
            self._backup_dir = backup_dir
        else:
            self._backup_dir = self.BACKUP_DIR

        # Ensure the backup directory path ends with a separator
        if not self._backup_dir.endswith(os.sep):
            self._backup_dir += os.sep

    def backup(self, target_paths):
        """Backup each target file and write a manifest.

        For each file in target_paths:
          - Copy the file to the backup directory
          - Record original path, backup path, and permissions

        After copying, writes manifest.json with a timestamp and
        the list of backed-up files. Then calls cleanup_old_backups()
        to remove any older backup sets.

        Args:
            target_paths: List of absolute file paths to back up.

        Raises:
            IOError: If a target file cannot be read or copied.
            OSError: If the backup directory cannot be created.
        """
        # Ensure backup directory exists
        if not os.path.isdir(self._backup_dir):
            os.makedirs(self._backup_dir)

        files_manifest = []

        for target_path in target_paths:
            if not os.path.isfile(target_path):
                log.warning(
                    "Backup skipping non-existent file: %s", target_path
                )
                continue

            filename = os.path.basename(target_path)
            backup_path = os.path.join(self._backup_dir, filename)

            # Copy the file preserving metadata
            shutil.copy2(target_path, backup_path)

            # Read the file permissions (octal string)
            mode = os.stat(target_path).st_mode & 0o777
            permissions = "0o%03o" % mode

            files_manifest.append({
                "original_path": target_path,
                "backup_path": backup_path,
                "permissions": permissions,
            })

            log.info(
                "Backed up %s -> %s (permissions: %s)",
                target_path, backup_path, permissions
            )

        # Write manifest.json
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest = {
            "timestamp": timestamp,
            "files": files_manifest,
        }

        manifest_path = os.path.join(self._backup_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=4)

        log.info(
            "Backup manifest written: %s (%d file(s), timestamp: %s)",
            manifest_path, len(files_manifest), timestamp
        )

        # Remove older backup sets, keeping only this one (Req 4.6)
        self.cleanup_old_backups()

    def rollback(self):
        """Restore files from the backup manifest and restart the service.

        Reads manifest.json from the backup directory, copies each
        backed-up file back to its original path, restores permissions,
        and restarts the zumi-iot systemd service (Req 4.4).

        Raises:
            IOError: If manifest.json cannot be read.
            ValueError: If manifest.json contains invalid JSON.
        """
        manifest_path = os.path.join(self._backup_dir, "manifest.json")

        if not os.path.isfile(manifest_path):
            log.error("No backup manifest found at %s", manifest_path)
            raise IOError(
                "No backup manifest found at %s" % manifest_path
            )

        with open(manifest_path, "r") as f:
            try:
                manifest = json.load(f)
            except (ValueError, TypeError) as e:
                log.error("Invalid backup manifest: %s", e)
                raise ValueError(
                    "Invalid backup manifest JSON: %s" % str(e)
                )

        files = manifest.get("files", [])
        restored_count = 0

        for entry in files:
            backup_path = entry.get("backup_path", "")
            original_path = entry.get("original_path", "")
            permissions = entry.get("permissions", "")

            if not os.path.isfile(backup_path):
                log.error(
                    "Backup file missing, cannot restore: %s",
                    backup_path
                )
                continue

            # Ensure the target directory exists
            target_dir = os.path.dirname(original_path)
            if target_dir and not os.path.isdir(target_dir):
                os.makedirs(target_dir)

            # Copy backup file back to original location
            shutil.copy2(backup_path, original_path)

            # Restore permissions if recorded
            if permissions:
                try:
                    mode = int(permissions, 8)
                    os.chmod(original_path, mode)
                except (ValueError, TypeError) as e:
                    log.warning(
                        "Could not restore permissions '%s' for %s: %s",
                        permissions, original_path, e
                    )

            restored_count += 1
            log.info(
                "Restored %s from %s (permissions: %s)",
                original_path, backup_path, permissions
            )

        log.info(
            "Rollback complete: restored %d of %d file(s)",
            restored_count, len(files)
        )

        # Restart the systemd service (Req 4.4)
        log.info("Restarting zumi-iot service after rollback")
        subprocess.call(["sudo", "systemctl", "restart", "zumi-iot"])

    def cleanup_old_backups(self):
        """Remove all but the most recent backup set.

        Reads the current manifest.json to determine which files
        belong to the current backup set. Deletes everything else
        in the backup directory (Req 4.6).

        If no manifest exists, all files in the backup directory
        are removed.
        """
        if not os.path.isdir(self._backup_dir):
            return

        manifest_path = os.path.join(self._backup_dir, "manifest.json")

        # Determine which files to keep (current backup set)
        keep_files = set()
        keep_files.add(os.path.abspath(manifest_path))

        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                for entry in manifest.get("files", []):
                    backup_path = entry.get("backup_path", "")
                    if backup_path:
                        keep_files.add(os.path.abspath(backup_path))
            except (ValueError, TypeError, IOError, OSError) as e:
                log.warning(
                    "Could not read manifest for cleanup: %s", e
                )

        # Walk the backup directory and remove anything not in keep_files
        removed_count = 0
        for item in os.listdir(self._backup_dir):
            item_path = os.path.join(self._backup_dir, item)
            abs_path = os.path.abspath(item_path)

            if abs_path in keep_files:
                continue

            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                removed_count += 1
                log.info("Cleanup removed: %s", item_path)
            except OSError as e:
                log.warning(
                    "Cleanup could not remove %s: %s", item_path, e
                )

        if removed_count > 0:
            log.info(
                "Cleanup complete: removed %d old item(s)", removed_count
            )


# ---------------------------------------------------------------------------
# OTA Agent
# ---------------------------------------------------------------------------

class OTAAgent(object):
    """Device-side OTA update agent using AWS IoT Jobs.

    Shares the existing MQTT connection from zumi_iot.py.
    Subscribes only to IoT Jobs topics — does not interfere
    with existing command/telemetry subscriptions.
    """

    def __init__(self, mqtt_connection, thing_name, config):
        """Initialize with shared MQTT connection from zumi_iot.py.

        Args:
            mqtt_connection: The shared awscrt.mqtt.Connection instance.
            thing_name: AWS IoT thing name (e.g. 'robolink-zumi').
            config: Dict with OTA configuration keys:
                - ota_staging_dir: Path to staging directory
                - ota_backup_dir: Path to backup directory
                - ota_codesign_pubkey: Path to code signing public key
                - ota_health_check_timeout: Seconds to wait for health check
                - ota_download_retries: Number of download retry attempts
        """
        self._connection = mqtt_connection
        self._thing_name = thing_name
        self._config = config
        self._running = False
        self._current_job_id = None
        self._current_version = None
        self._current_execution_number = None

        # Build topic strings
        self._notify_topic = (
            "$aws/things/%s/jobs/notify-next" % self._thing_name
        )

        # Config defaults
        self._staging_dir = config.get(
            "ota_staging_dir", "/home/pi/zumi-iot/.ota-staging"
        )
        self._backup_dir = config.get(
            "ota_backup_dir", "/home/pi/zumi-iot/.ota-backup"
        )
        self._health_check_timeout = int(
            config.get("ota_health_check_timeout", 60)
        )
        self._download_retries = int(
            config.get("ota_download_retries", 3)
        )

        log.info(
            "OTAAgent initialized for thing '%s'", self._thing_name
        )

    def start(self):
        """Subscribe to IoT Jobs topics and begin listening.

        Subscribes to the notify-next topic to receive pending
        job notifications, then publishes a get-next request to
        pick up any jobs that were queued before the agent started.
        """
        if self._running:
            log.warning("OTAAgent already running")
            return

        log.info("OTAAgent starting — subscribing to %s", self._notify_topic)

        subscribe_future, _ = self._connection.subscribe(
            topic=self._notify_topic,
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self._on_job_notification,
        )
        subscribe_future.result()

        self._running = True
        log.info("OTAAgent started — listening for job notifications")

        # Request the next pending job (if any) so we pick up jobs
        # that were queued while the agent was not running (Req 2.5).
        get_topic = "$aws/things/%s/jobs/$next/get" % self._thing_name
        log.info("Requesting next pending job via %s", get_topic)
        self._connection.publish(
            topic=get_topic,
            payload="{}",
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )

    def stop(self):
        """Unsubscribe from IoT Jobs topics and clean up."""
        if not self._running:
            log.warning("OTAAgent not running")
            return

        log.info("OTAAgent stopping — unsubscribing from %s", self._notify_topic)

        try:
            unsubscribe_future, _ = self._connection.unsubscribe(
                topic=self._notify_topic,
            )
            unsubscribe_future.result()
        except Exception as e:
            log.error("Error unsubscribing from notify topic: %s", e)

        self._running = False
        log.info("OTAAgent stopped")

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_update_response(self, topic, payload, dup, qos, retain, **kwargs):
        """Handle update accepted/rejected responses for debugging."""
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            log.info("Update response on %s: %s", topic, payload[:500])
        except Exception as e:
            log.error("Error handling update response: %s", e)

    def _on_job_notification(self, topic, payload, dup, qos, retain, **kwargs):
        """Handle incoming job notification from IoT Jobs.

        Called when a message arrives on $aws/things/{thing}/jobs/notify-next.
        Parses the job document, validates it, publishes IN_PROGRESS, and
        kicks off the update pipeline via _process_job().

        Reconnection handling: The notify-next topic automatically delivers
        any pending job when the device reconnects after being offline
        (Req 2.5). No special reconnection logic is needed — AWS IoT Jobs
        re-publishes the next queued job execution on re-subscribe.

        All exceptions are caught to avoid crashing the main IoT bridge
        (Req 9.4).
        """
        try:
            log.info("Job notification received on %s", topic)

            # Decode payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")

            data = json.loads(payload)

            # The notify-next payload wraps the job execution info
            execution = data.get("execution")
            if execution is None:
                # No pending job — this is normal after all jobs complete
                log.info("No pending job execution in notification")
                return

            job_id = execution.get("jobId")
            if not job_id:
                log.error("Job notification missing jobId")
                return

            self._current_job_id = job_id
            self._current_version = execution.get("versionNumber", 1)
            self._current_execution_number = execution.get("executionNumber")
            log.info("Processing job: %s", job_id)

            # Extract the job document from the execution
            job_document = execution.get("jobDocument")
            if job_document is None:
                log.error("Job %s has no jobDocument", job_id)
                self._report_failure(
                    job_id, "missing_fields",
                    "Job notification did not contain a jobDocument"
                )
                return

            # Parse and validate the job document.
            # job_document may be a dict (already parsed by IoT) or a
            # JSON string — handle both cases.
            doc = self._validate_job_document(job_id, job_document)

            log.info(
                "Job %s: operation=%s, %d artifact(s)",
                job_id, doc.get("operation"), len(doc.get("artifacts", []))
            )

            # Valid job — report IN_PROGRESS (Req 2.3)
            # First subscribe to update response topics to see rejections
            accepted_topic = "$aws/things/%s/jobs/%s/update/accepted" % (
                self._thing_name, job_id
            )
            rejected_topic = "$aws/things/%s/jobs/%s/update/rejected" % (
                self._thing_name, job_id
            )
            try:
                self._connection.subscribe(
                    topic=accepted_topic,
                    qos=mqtt.QoS.AT_LEAST_ONCE,
                    callback=self._on_update_response,
                )
                self._connection.subscribe(
                    topic=rejected_topic,
                    qos=mqtt.QoS.AT_LEAST_ONCE,
                    callback=self._on_update_response,
                )
            except Exception as e:
                log.warning("Failed to subscribe to update response topics: %s", e)

            self._report_in_progress(job_id)

            # Small delay to allow IN_PROGRESS status to propagate
            # before the pipeline completes and publishes SUCCEEDED
            time.sleep(1)

            # Hand off to the processing pipeline (Tasks 6, 7, 9)
            self._process_job(job_id, doc)

        except (ValueError, TypeError) as e:
            # Determine the appropriate failure step from the error message
            error_msg = str(e)
            if "Unsupported job document version" in error_msg:
                step = "unsupported_version"
            elif "missing required fields" in error_msg:
                step = "missing_fields"
            else:
                step = "parse_error"
            log.error("Failed to process job notification: %s", e)
            if self._current_job_id:
                self._report_failure(self._current_job_id, step, error_msg)
        except Exception as e:
            # Catch-all to protect the main IoT bridge process (Req 9.4)
            log.error("Unhandled error in job notification handler: %s", e)
            if self._current_job_id:
                self._report_failure(
                    self._current_job_id, "unhandled_error", str(e)
                )

    def _validate_job_document(self, job_id, job_document):
        """Validate a job document from the notification payload.

        Handles both dict (pre-parsed by IoT) and string (raw JSON)
        representations. Raises ValueError with a descriptive message
        on invalid JSON, unsupported version, or missing fields.

        Args:
            job_id: The job ID (for logging).
            job_document: dict or str — the job document from the
                execution payload.

        Returns:
            dict — the validated job document.

        Raises:
            ValueError: On invalid JSON, unsupported version, or
                missing required fields.
        """
        if isinstance(job_document, dict):
            doc = job_document
            # Validate top-level required fields
            required_top = ["version", "operation", "artifacts", "post_action"]
            missing = [f for f in required_top if f not in doc]
            if missing:
                raise ValueError(
                    "Job document missing required fields: %s"
                    % ", ".join(missing)
                )

            # Validate version
            if doc["version"] != SUPPORTED_SCHEMA_VERSION:
                raise ValueError(
                    "Unsupported job document version: %s (expected %s)"
                    % (doc["version"], SUPPORTED_SCHEMA_VERSION)
                )

            # Validate artifacts is a non-empty list
            if not isinstance(doc.get("artifacts"), list):
                raise ValueError("Job document 'artifacts' must be a list")
            if len(doc["artifacts"]) == 0:
                raise ValueError("Job document 'artifacts' must not be empty")

            # Validate each artifact descriptor
            required_artifact = ["url", "target_path", "file_size", "sha256"]
            for i, artifact in enumerate(doc["artifacts"]):
                if not isinstance(artifact, dict):
                    raise ValueError("Artifact %d must be a JSON object" % i)
                missing_art = [f for f in required_artifact if f not in artifact]
                if missing_art:
                    raise ValueError(
                        "Artifact %d missing required fields: %s"
                        % (i, ", ".join(missing_art))
                    )

            return doc
        else:
            # String payload — delegate to the standalone parser
            return parse_job_document(job_document)

    # ------------------------------------------------------------------
    # Artifact download (Task 6.1)
    # ------------------------------------------------------------------

    def _download_artifact(self, url, staging_path):
        """Download artifact from presigned URL to staging path.

        Retries up to self._download_retries times with exponential
        backoff (2s, 4s, 8s) on network errors. Raises immediately
        on HTTP 403 (URL expired) without retrying.

        Args:
            url: Presigned S3 URL string.
            staging_path: Local file path to write the downloaded
                artifact to (inside .ota-staging/).

        Raises:
            ValueError: On HTTP 403 (URL expired).
            IOError: After all retries exhausted on network errors.
        """
        # Ensure staging directory exists
        staging_dir = os.path.dirname(staging_path)
        if not os.path.isdir(staging_dir):
            os.makedirs(staging_dir)

        last_error = None
        for attempt in range(self._download_retries):
            try:
                log.info(
                    "Downloading artifact (attempt %d/%d): %s",
                    attempt + 1, self._download_retries,
                    url[:80] + "..." if len(url) > 80 else url
                )
                request = Request(url)
                response = urlopen(request, timeout=120)
                data = response.read()

                with open(staging_path, "wb") as f:
                    f.write(data)

                log.info(
                    "Downloaded %d bytes to %s",
                    len(data), staging_path
                )
                return

            except HTTPError as e:
                if e.code == 403:
                    # URL expired — do not retry (Req 3.3)
                    raise ValueError(
                        "Presigned URL expired or access denied (HTTP 403)"
                    )
                last_error = e
                log.warning(
                    "HTTP error %d on attempt %d: %s",
                    e.code, attempt + 1, e
                )
            except (URLError, IOError, OSError) as e:
                last_error = e
                log.warning(
                    "Network error on attempt %d: %s",
                    attempt + 1, e
                )

            # Exponential backoff: 2^(attempt+1) seconds → 2, 4, 8
            if attempt < self._download_retries - 1:
                backoff = 2 ** (attempt + 1)
                log.info("Retrying in %d seconds...", backoff)
                time.sleep(backoff)

        # All retries exhausted (Req 3.4)
        raise IOError(
            "Download failed after %d attempts: %s"
            % (self._download_retries, last_error)
        )

    # ------------------------------------------------------------------
    # Hash and file size verification (Task 6.2)
    # ------------------------------------------------------------------

    def _verify_file_size(self, file_path, expected_size):
        """Verify downloaded file size matches expected size.

        Args:
            file_path: Path to the downloaded file.
            expected_size: Expected file size in bytes (int).

        Returns:
            True if sizes match, False otherwise.
        """
        actual_size = os.path.getsize(file_path)
        if actual_size != expected_size:
            log.error(
                "File size mismatch for %s: expected %d, got %d",
                file_path, expected_size, actual_size
            )
            return False
        log.info("File size verified: %d bytes", actual_size)
        return True

    def _verify_hash(self, file_path, expected_sha256):
        """Verify SHA-256 hash of downloaded file.

        Args:
            file_path: Path to the downloaded file.
            expected_sha256: Expected SHA-256 hex digest string.

        Returns:
            True if hash matches, False otherwise.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)

        actual_hash = sha256.hexdigest()
        if actual_hash != expected_sha256.lower():
            log.error(
                "SHA-256 hash mismatch for %s: expected %s, got %s",
                file_path, expected_sha256, actual_hash
            )
            return False
        log.info("SHA-256 hash verified: %s", actual_hash)
        return True

    # ------------------------------------------------------------------
    # Code signature verification (Task 6.3)
    # ------------------------------------------------------------------

    def _verify_signature(self, file_path, codesign):
        """Verify code signature of downloaded artifact.

        Uses a lightweight PKCS#1 v1.5 RSA-SHA256 verification
        approach with only hashlib and standard library modules.
        Python 3.5.3 compatible.

        When codesign is None, verification is skipped (Req 12.8).
        Signature verification runs after SHA-256 hash check (Req 12.9).

        Args:
            file_path: Path to the downloaded file.
            codesign: The codesign dict from the artifact descriptor,
                or None if code signing is not enabled.
                Expected keys: 'signature', 'algorithm'.

        Returns:
            True if signature is valid or codesign is None (skip).
            False if signature verification fails.
        """
        if codesign is None:
            log.info("No codesign object — skipping signature verification")
            return True

        pubkey_path = self._config.get(
            "ota_codesign_pubkey",
            "/home/pi/zumi-iot/certs/code-signing.pem"
        )

        if not os.path.isfile(pubkey_path):
            log.error(
                "Code signing public key not found: %s", pubkey_path
            )
            return False

        signature_b64 = codesign.get("signature")
        if not signature_b64:
            log.error("Codesign object missing 'signature' field")
            return False

        algorithm = codesign.get("algorithm", "RSA-SHA256")
        if algorithm != "RSA-SHA256":
            log.error("Unsupported signing algorithm: %s", algorithm)
            return False

        try:
            signature = base64.b64decode(signature_b64)
        except (ValueError, TypeError) as e:
            log.error("Invalid base64 signature: %s", e)
            return False

        # Compute SHA-256 digest of the file
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        file_digest = sha256.digest()

        # Read the PEM public key and verify using PKCS#1 v1.5
        try:
            with open(pubkey_path, "rb") as f:
                pubkey_pem = f.read()

            result = _pkcs1_v15_verify_rsa_sha256(
                pubkey_pem, signature, file_digest
            )
            if result:
                log.info("Code signature verified successfully")
            else:
                log.error("Code signature verification failed")
            return result

        except Exception as e:
            log.error("Signature verification error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Update application (Task 9.1)
    # ------------------------------------------------------------------

    def _apply_update(self, staging_path, target_path):
        """Copy staged artifact to target path, preserving permissions.

        Gets the original file permissions before overwriting, copies
        the staged file to the target path using shutil.copy2, then
        restores the original permissions via os.chmod.

        Args:
            staging_path: Path to the staged artifact in .ota-staging/.
            target_path: Destination path for the updated file.

        Returns:
            True on success, False on failure (caller handles rollback).
        """
        try:
            # Get original file permissions if file exists (Req 5.2)
            if os.path.isfile(target_path):
                original_mode = os.stat(target_path).st_mode & 0o777
                log.info(
                    "Original permissions for %s: 0o%03o",
                    target_path, original_mode
                )
            else:
                # New file — use sensible default (owner rw, group/other r)
                original_mode = 0o644
                log.info(
                    "Target %s does not exist yet — using default permissions 0o%03o",
                    target_path, original_mode
                )

            # Ensure target directory exists
            target_dir = os.path.dirname(target_path)
            if target_dir and not os.path.isdir(target_dir):
                os.makedirs(target_dir)

            # Copy staged file to target (Req 5.1)
            shutil.copy2(staging_path, target_path)

            # Restore original permissions (Req 5.2)
            os.chmod(target_path, original_mode)

            log.info(
                "Applied update: %s -> %s (permissions: 0o%03o)",
                staging_path, target_path, original_mode
            )
            return True

        except (IOError, OSError) as e:
            # Disk full, permission denied, etc. (Req 5.3)
            log.error(
                "Failed to apply update %s -> %s: %s",
                staging_path, target_path, e
            )
            return False

    # ------------------------------------------------------------------
    # Service restart and health check (Task 9.2)
    # ------------------------------------------------------------------

    def _restart_and_health_check(self):
        """Restart zumi-iot service and wait for healthy state.

        Restarts the systemd service via systemctl, then polls
        systemctl is-active every 2 seconds for up to
        self._health_check_timeout seconds.

        Returns:
            True if service reaches 'active' state within timeout.
            False if timeout expires without healthy state.
        """
        # Restart the service (Req 6.1)
        log.info("Restarting zumi-iot service")
        subprocess.call(["sudo", "systemctl", "restart", "zumi-iot"])

        # Poll for healthy state (Req 6.2)
        elapsed = 0
        poll_interval = 2
        while elapsed < self._health_check_timeout:
            try:
                output = subprocess.check_output(
                    ["systemctl", "is-active", "zumi-iot"]
                )
                state = output.strip()
                # Handle bytes vs str (Python 3.5 compat)
                if isinstance(state, bytes):
                    state = state.decode("utf-8")
                if state == "active":
                    log.info(
                        "Health check passed: service active after %d seconds",
                        elapsed
                    )
                    return True
            except subprocess.CalledProcessError:
                # is-active returns non-zero for inactive/failed
                pass
            except (OSError, IOError) as e:
                log.warning("Health check poll error: %s", e)

            time.sleep(poll_interval)
            elapsed += poll_interval

        log.error(
            "Health check failed: service not active after %d seconds",
            self._health_check_timeout
        )
        return False

    # ------------------------------------------------------------------
    # Self-update detection (Task 9.3)
    # ------------------------------------------------------------------

    def _is_self_update(self, target_paths):
        """Check if any target path contains ota_agent.py or zumi_iot.py.

        When the OTA agent or the main IoT bridge script is being
        updated, the restart and health check must be delegated to
        the watchdog script instead of being done in-process (Req 6.5).

        Args:
            target_paths: List of target file path strings.

        Returns:
            True if self-update detected, False otherwise.
        """
        self_update_files = ("ota_agent.py", "zumi_iot.py")
        for path in target_paths:
            basename = os.path.basename(path)
            if basename in self_update_files:
                log.info(
                    "Self-update detected: %s is among updated files", basename
                )
                return True
        return False

    def _delegate_to_watchdog(self, job_id, thing_name):
        """Delegate restart and health check to the watchdog script.

        Launches ota_watchdog.sh as a detached subprocess and returns
        immediately. The watchdog handles service restart, health check,
        and status reporting independently (Req 6.5).

        Args:
            job_id: The AWS IoT Jobs job ID.
            thing_name: The AWS IoT thing name.
        """
        watchdog_path = "/home/pi/zumi-iot/ota_watchdog.sh"
        log.info(
            "Delegating restart + health check to watchdog: %s %s %s",
            watchdog_path, job_id, thing_name
        )
        subprocess.Popen(
            ["bash", watchdog_path, job_id, thing_name]
        )

    # ------------------------------------------------------------------
    # Job processing pipeline
    # ------------------------------------------------------------------

    def _process_job(self, job_id, doc):
        """Execute the full OTA update pipeline for a validated job.

        This is the entry point for the OTA pipeline after the job
        document has been validated and IN_PROGRESS has been reported.

        Pipeline steps:
          - Task 6: Download artifact, verify size, hash, and signature
          - Task 7: Backup current files via RollbackManager
          - Task 9: Apply update, restart service, health check

        Args:
            job_id: The AWS IoT Jobs job ID.
            doc: The validated job document dict.
        """
        log.info("Job %s: starting processing pipeline", job_id)

        artifacts = doc.get("artifacts", [])

        # Collect target paths and staging paths for later steps
        artifact_info = []

        for i, artifact in enumerate(artifacts):
            url = artifact["url"]
            target_path = artifact["target_path"]
            expected_size = artifact["file_size"]
            expected_sha256 = artifact["sha256"]
            codesign = artifact.get("codesign")

            # Derive staging file path
            filename = os.path.basename(target_path)
            staging_path = os.path.join(self._staging_dir, filename)

            # Step 1: Download artifact (Req 3.1, 3.3, 3.4, 3.5)
            try:
                self._download_artifact(url, staging_path)
            except ValueError as e:
                # HTTP 403 — URL expired (Req 3.3)
                self._report_failure(job_id, "download", str(e))
                return
            except IOError as e:
                # Retries exhausted (Req 3.4)
                self._report_failure(job_id, "download", str(e))
                return

            # Step 2: Verify file size (Req 3.2)
            if not self._verify_file_size(staging_path, expected_size):
                self._discard_staged_file(staging_path)
                self._report_failure(
                    job_id, "verify_size",
                    "File size mismatch for artifact %d (%s)" % (i, filename)
                )
                return

            # Step 3: Verify SHA-256 hash (Req 10.6, 10.7)
            if not self._verify_hash(staging_path, expected_sha256):
                self._discard_staged_file(staging_path)
                self._report_failure(
                    job_id, "verify_hash",
                    "SHA-256 hash mismatch for artifact %d (%s)" % (i, filename)
                )
                return

            # Step 4: Verify code signature if present (Req 12.5, 12.9)
            # Signature check runs AFTER hash check passes
            if not self._verify_signature(staging_path, codesign):
                self._discard_staged_file(staging_path)
                self._report_failure(
                    job_id, "verify_signature",
                    "Code signature verification failed for artifact %d (%s)"
                    % (i, filename)
                )
                return

            log.info(
                "Job %s: artifact %d (%s) downloaded and verified",
                job_id, i, filename
            )

            artifact_info.append({
                "staging_path": staging_path,
                "target_path": target_path,
                "sha256": expected_sha256,
            })

        log.info(
            "Job %s: all %d artifact(s) downloaded and verified",
            job_id, len(artifacts)
        )

        # Step 5: Backup current files via RollbackManager (Req 4.1, 4.2)
        target_paths = [info["target_path"] for info in artifact_info]
        rollback_mgr = RollbackManager(backup_dir=self._backup_dir)
        try:
            rollback_mgr.backup(target_paths)
        except (IOError, OSError) as e:
            log.error("Job %s: backup failed: %s", job_id, e)
            self._report_failure(job_id, "backup", str(e))
            return

        log.info("Job %s: backup complete", job_id)

        # Step 6: Apply each artifact update (Req 5.1, 5.2, 5.3)
        files_updated = []
        combined_sha256 = ""
        for info in artifact_info:
            if not self._apply_update(info["staging_path"], info["target_path"]):
                # Apply failed — rollback and report FAILED (Req 5.3)
                log.error(
                    "Job %s: apply failed for %s, triggering rollback",
                    job_id, info["target_path"]
                )
                try:
                    rollback_mgr.rollback()
                except Exception as e:
                    log.error("Job %s: rollback failed: %s", job_id, e)
                self._report_failure(
                    job_id, "apply",
                    "Failed to copy artifact to %s" % info["target_path"]
                )
                return
            files_updated.append(info["target_path"])
            combined_sha256 = info["sha256"]

        log.info(
            "Job %s: all artifacts applied successfully", job_id
        )

        # Step 7: Check for self-update (Req 6.5)
        if self._is_self_update(target_paths):
            # Delegate to watchdog — it handles restart, health check,
            # and status reporting independently
            log.info(
                "Job %s: self-update detected, delegating to watchdog",
                job_id
            )
            self._delegate_to_watchdog(job_id, self._thing_name)
            return

        # Step 8: Check post_action to decide whether to restart
        post_action = doc.get("post_action", "restart_service")

        if post_action == "restart_service":
            # Restart service and health check (Req 6.1, 6.2)
            if self._restart_and_health_check():
                # Health check passed — report SUCCEEDED (Req 6.3, 7.1, 7.3)
                self._report_success(job_id, files_updated, combined_sha256)
            else:
                # Health check failed — rollback and report FAILED (Req 6.4)
                log.error(
                    "Job %s: health check failed, triggering rollback",
                    job_id
                )
                try:
                    rollback_mgr.rollback()
                except Exception as e:
                    log.error("Job %s: rollback after health check failed: %s", job_id, e)
                self._report_failure(
                    job_id, "health_check",
                    "Service failed to reach active state within %d seconds"
                    % self._health_check_timeout
                )
        elif post_action == "extract_model":
            # Extract tar.gz artifacts into their target directories (Req 3.5)
            log.info("Job %s: post_action=extract_model, extracting tar.gz artifacts", job_id)
            extracted_files = []

            for info in artifact_info:
                target_path = info["target_path"]

                # Only process tar.gz files (Req 3.5)
                if not target_path.endswith(".tar.gz"):
                    log.info(
                        "Job %s: skipping non-tar.gz artifact: %s",
                        job_id, target_path
                    )
                    continue

                extract_dir = os.path.dirname(target_path)
                log.info(
                    "Job %s: extracting %s into %s",
                    job_id, target_path, extract_dir
                )

                try:
                    tf = tarfile.open(target_path, "r:gz")
                except (tarfile.TarError, IOError, OSError) as e:
                    log.error(
                        "Job %s: failed to open tar.gz %s: %s",
                        job_id, target_path, e
                    )
                    try:
                        rollback_mgr.rollback()
                    except Exception as rb_err:
                        log.error("Job %s: rollback failed: %s", job_id, rb_err)
                    self._report_failure(
                        job_id, "extract_model",
                        "Failed to open tar.gz: %s" % str(e)
                    )
                    return

                try:
                    # Check for path traversal in member names (Req 3.8)
                    members = tf.getmembers()
                    for member in members:
                        if "../" in member.name:
                            log.error(
                                "Job %s: path traversal detected in tar.gz member: %s",
                                job_id, member.name
                            )
                            tf.close()
                            try:
                                rollback_mgr.rollback()
                            except Exception as rb_err:
                                log.error("Job %s: rollback failed: %s", job_id, rb_err)
                            self._report_failure(
                                job_id, "extract_model",
                                "Path traversal detected in tar.gz member: %s" % member.name
                            )
                            return

                    # Extract all members into the target directory
                    tf.extractall(path=extract_dir)
                    tf.close()

                    # Verify extracted files exist and are non-empty (Req 3.5)
                    for member in members:
                        if member.isfile():
                            extracted_path = os.path.join(extract_dir, member.name)
                            if not os.path.isfile(extracted_path):
                                log.error(
                                    "Job %s: extracted file missing: %s",
                                    job_id, extracted_path
                                )
                                try:
                                    rollback_mgr.rollback()
                                except Exception as rb_err:
                                    log.error("Job %s: rollback failed: %s", job_id, rb_err)
                                self._report_failure(
                                    job_id, "extract_model",
                                    "Extracted file missing: %s" % extracted_path
                                )
                                return

                            file_size = os.path.getsize(extracted_path)
                            if file_size == 0:
                                log.error(
                                    "Job %s: extracted file is empty: %s",
                                    job_id, extracted_path
                                )
                                try:
                                    rollback_mgr.rollback()
                                except Exception as rb_err:
                                    log.error("Job %s: rollback failed: %s", job_id, rb_err)
                                self._report_failure(
                                    job_id, "extract_model",
                                    "Extracted file is empty: %s" % extracted_path
                                )
                                return

                            extracted_files.append(extracted_path)
                            log.info(
                                "Job %s: verified extracted file: %s (%d bytes)",
                                job_id, extracted_path, file_size
                            )

                except (tarfile.TarError, IOError, OSError) as e:
                    log.error(
                        "Job %s: extraction failed for %s: %s",
                        job_id, target_path, e
                    )
                    tf.close()
                    try:
                        rollback_mgr.rollback()
                    except Exception as rb_err:
                        log.error("Job %s: rollback failed: %s", job_id, rb_err)
                    self._report_failure(
                        job_id, "extract_model",
                        "Extraction failed: %s" % str(e)
                    )
                    return

            # All tar.gz artifacts extracted successfully (Req 3.10)
            all_files = files_updated + extracted_files
            log.info(
                "Job %s: extract_model complete, %d extracted file(s)",
                job_id, len(extracted_files)
            )
            self._report_success(job_id, all_files, combined_sha256)

        else:
            # No restart needed — report SUCCEEDED immediately
            log.info(
                "Job %s: post_action=%s, skipping service restart",
                job_id, post_action
            )
            self._report_success(job_id, files_updated, combined_sha256)

    def _discard_staged_file(self, staging_path):
        """Remove a staged file after verification failure.

        Args:
            staging_path: Path to the staged file to remove.
        """
        try:
            if os.path.isfile(staging_path):
                os.remove(staging_path)
                log.info("Discarded staged file: %s", staging_path)
        except OSError as e:
            log.warning("Failed to discard staged file %s: %s", staging_path, e)

    # ------------------------------------------------------------------
    # Job status reporting (Req 7.1, 7.2, 7.3)
    # ------------------------------------------------------------------

    def _report_in_progress(self, job_id):
        """Report job execution in-progress to IoT Jobs.

        Publishes IN_PROGRESS status to the job update topic
        at $aws/things/{thing_name}/jobs/{job_id}/update.

        Args:
            job_id: The AWS IoT Jobs job ID.
        """
        log.info("Job %s IN_PROGRESS", job_id)
        topic = "$aws/things/%s/jobs/%s/update" % (
            self._thing_name, job_id
        )
        update_payload = {
            "status": "IN_PROGRESS",
            "statusDetails": {},
        }
        if self._current_execution_number is not None:
            update_payload["executionNumber"] = self._current_execution_number
        payload = json.dumps(update_payload)
        try:
            self._connection.publish(
                topic=topic,
                payload=payload,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            log.info(
                "Published IN_PROGRESS for job %s to %s", job_id, topic
            )
        except Exception as e:
            log.error(
                "Failed to publish IN_PROGRESS for job %s: %s",
                job_id, e
            )

    def _report_failure(self, job_id, step, reason):
        """Report job execution failure to IoT Jobs.

        Publishes FAILED status with detail JSON containing the
        failure reason, the step that failed, and a timestamp
        to the job update topic (Req 7.2).

        Args:
            job_id: The AWS IoT Jobs job ID.
            step: The pipeline step that failed (e.g. 'verify_hash').
            reason: Human-readable failure reason string.
        """
        log.error("Job %s FAILED at step '%s': %s", job_id, step, reason)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        topic = "$aws/things/%s/jobs/%s/update" % (
            self._thing_name, job_id
        )
        update_payload = {
            "status": "FAILED",
            "statusDetails": {
                "reason": reason,
                "step": step,
                "timestamp": timestamp,
            },
        }
        if self._current_execution_number is not None:
            update_payload["executionNumber"] = self._current_execution_number
        payload = json.dumps(update_payload)
        try:
            self._connection.publish(
                topic=topic,
                payload=payload,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            log.info(
                "Published FAILED for job %s to %s", job_id, topic
            )
        except Exception as e:
            log.error(
                "Failed to publish FAILED for job %s: %s",
                job_id, e
            )

    def _report_success(self, job_id, files_updated, artifact_sha256):
        """Report job execution success to IoT Jobs.

        Publishes SUCCEEDED status with detail JSON containing the
        files updated, artifact SHA-256, and a timestamp to the
        job update topic (Req 7.3).

        Args:
            job_id: The AWS IoT Jobs job ID.
            files_updated: List of file path strings that were updated.
            artifact_sha256: SHA-256 hex digest of the applied artifact.
        """
        log.info("Job %s SUCCEEDED: updated %s", job_id, files_updated)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        topic = "$aws/things/%s/jobs/%s/update" % (
            self._thing_name, job_id
        )
        # Convert files_updated list to comma-separated string for
        # IoT Jobs statusDetails (values must be strings)
        files_str = ",".join(files_updated) if files_updated else ""
        update_payload = {
            "status": "SUCCEEDED",
            "statusDetails": {
                "files_updated": files_str,
                "artifact_sha256": artifact_sha256,
                "timestamp": timestamp,
            },
        }
        if self._current_execution_number is not None:
            update_payload["executionNumber"] = self._current_execution_number
        payload = json.dumps(update_payload)
        try:
            self._connection.publish(
                topic=topic,
                payload=payload,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            log.info(
                "Published SUCCEEDED for job %s to %s", job_id, topic
            )
        except Exception as e:
            log.error(
                "Failed to publish SUCCEEDED for job %s: %s",
                job_id, e
            )
