"""Property-based tests for OTA trigger module.

Uses Hypothesis to verify correctness properties across randomized inputs.
"""

import copy
from datetime import datetime, timezone

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from ota_trigger import (
    build_job_document,
    parse_job_document,
    build_failed_status_detail,
    build_succeeded_status_detail,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 64-char lowercase hex string (SHA-256 digest)
sha256_hex = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

# Base64-ish signature string (printable ASCII, non-empty)
base64_signature = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
    min_size=4,
    max_size=200,
)

signing_profile_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=50,
)

algorithm_st = st.sampled_from(["RSA-SHA256", "ECDSA-SHA256", "RSA-SHA384", "ECDSA-SHA384"])

codesign_st = st.fixed_dictionaries({
    "signature": base64_signature,
    "signing_profile": signing_profile_st,
    "algorithm": algorithm_st,
})

url_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_./:",
    min_size=10,
    max_size=300,
).map(lambda s: "https://" + s)

target_path_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_./",
    min_size=5,
    max_size=200,
).map(lambda s: "/home/pi/" + s)

file_size_st = st.integers(min_value=1, max_value=100_000_000)

artifact_st = st.fixed_dictionaries(
    {
        "url": url_st,
        "target_path": target_path_st,
        "file_size": file_size_st,
        "sha256": sha256_hex,
    },
    optional={
        "codesign": codesign_st,
    },
)

artifacts_list_st = st.lists(artifact_st, min_size=1, max_size=5)

post_action_st = st.sampled_from([
    "restart_service",
    "reboot",
    "none",
    "reload_config",
])


# ---------------------------------------------------------------------------
# Property 1: Job document serialization round-trip
# Feature: zumi-ota-updates, Property 1: Job document serialization round-trip
# Validates: Requirements 11.1, 11.2
# ---------------------------------------------------------------------------

@given(artifacts=artifacts_list_st, post_action=post_action_st)
@settings(max_examples=200)
def test_job_document_round_trip(artifacts, post_action):
    """Property 1: Job document serialization round-trip.

    For any valid job document containing arbitrary artifact descriptors
    (with or without codesign objects), serializing via build_job_document
    and then deserializing via parse_job_document produces an equivalent
    document.

    **Validates: Requirements 11.1, 11.2**
    """
    # Build the job document
    doc = build_job_document(artifacts, post_action=post_action)

    # Parse it back (operates on a deep copy to ensure no aliasing effects)
    parsed = parse_job_document(copy.deepcopy(doc))

    # Round-trip must produce an equivalent document
    assert parsed == doc

    # Verify structural invariants hold after round-trip
    assert parsed["version"] == "1.0"
    assert parsed["operation"] == "update_files"
    assert parsed["post_action"] == post_action
    assert len(parsed["artifacts"]) == len(artifacts)

    # Verify each artifact's fields survived the round-trip
    for i, (original, roundtripped) in enumerate(zip(artifacts, parsed["artifacts"])):
        assert roundtripped["url"] == original["url"]
        assert roundtripped["target_path"] == original["target_path"]
        assert roundtripped["file_size"] == original["file_size"]
        assert roundtripped["sha256"] == original["sha256"]

        # Codesign presence must be preserved
        if "codesign" in original:
            assert "codesign" in roundtripped
            assert roundtripped["codesign"]["signature"] == original["codesign"]["signature"]
            assert roundtripped["codesign"]["signing_profile"] == original["codesign"]["signing_profile"]
            assert roundtripped["codesign"]["algorithm"] == original["codesign"]["algorithm"]
        else:
            assert "codesign" not in roundtripped


# ---------------------------------------------------------------------------
# Property 2: Job document schema validation rejects invalid documents
# Feature: zumi-ota-updates, Property 2: Job document schema validation rejects invalid documents
# Validates: Requirements 10.1, 10.2, 10.3, 10.5, 2.2
# ---------------------------------------------------------------------------

# The four required top-level fields
_TOP_LEVEL_FIELDS = ["version", "operation", "artifacts", "post_action"]

# The four required artifact-level fields
_ARTIFACT_FIELDS = ["url", "target_path", "file_size", "sha256"]

# Strategy: non-empty subsets of top-level fields to remove
top_level_fields_to_remove = st.lists(
    st.sampled_from(_TOP_LEVEL_FIELDS),
    min_size=1,
    max_size=4,
    unique=True,
)

# Strategy: non-empty subsets of artifact fields to remove
artifact_fields_to_remove = st.lists(
    st.sampled_from(_ARTIFACT_FIELDS),
    min_size=1,
    max_size=4,
    unique=True,
)


@given(artifacts=artifacts_list_st, post_action=post_action_st)
@settings(max_examples=200)
def test_valid_documents_accepted(artifacts, post_action):
    """Property 2a: Valid documents are accepted by parse_job_document.

    For any JSON object containing all required fields with correct types,
    parse_job_document SHALL accept it without error.

    **Validates: Requirements 10.1, 10.2, 10.3, 2.2**
    """
    doc = build_job_document(artifacts, post_action=post_action)
    # Should not raise
    result = parse_job_document(copy.deepcopy(doc))
    assert result["version"] == "1.0"
    assert result["operation"] == "update_files"
    assert result["post_action"] == post_action
    assert len(result["artifacts"]) == len(artifacts)


@given(
    artifacts=artifacts_list_st,
    post_action=post_action_st,
    fields_to_remove=top_level_fields_to_remove,
)
@settings(max_examples=200)
def test_missing_top_level_fields_rejected(artifacts, post_action, fields_to_remove):
    """Property 2b: Documents missing required top-level fields are rejected.

    For any JSON object that is missing one or more required top-level fields
    (version, operation, artifacts, post_action), parse_job_document SHALL
    raise a ValueError whose message lists the missing fields.

    **Validates: Requirements 10.1, 10.5, 2.2**
    """
    # Build a valid document, then remove random top-level fields
    doc = build_job_document(artifacts, post_action=post_action)
    for field in fields_to_remove:
        doc.pop(field, None)

    try:
        parse_job_document(doc)
        # If we get here, the function didn't reject the document
        assert False, (
            f"parse_job_document should have raised ValueError for missing "
            f"top-level fields {fields_to_remove}, but it accepted the document"
        )
    except ValueError as exc:
        error_msg = str(exc)
        # The error message must mention each missing field
        for field in fields_to_remove:
            # The version field removal is caught by the "missing required fields"
            # check before the version value check, so all removed fields should
            # appear in the error message.
            assert field in error_msg, (
                f"ValueError message should mention missing field '{field}', "
                f"but got: {error_msg}"
            )


@given(
    post_action=post_action_st,
    artifact=artifact_st,
    fields_to_remove=artifact_fields_to_remove,
)
@settings(max_examples=200)
def test_missing_artifact_fields_rejected(post_action, artifact, fields_to_remove):
    """Property 2c: Artifact descriptors missing required fields are rejected.

    For any JSON object with valid top-level fields but artifact descriptors
    missing required fields (url, target_path, file_size, sha256),
    parse_job_document SHALL raise a ValueError listing the missing fields.

    **Validates: Requirements 10.2, 10.3, 10.5, 2.2**
    """
    # Build a valid document with one artifact, then remove fields from it
    doc = {
        "version": "1.0",
        "operation": "update_files",
        "artifacts": [copy.deepcopy(artifact)],
        "post_action": post_action,
    }
    for field in fields_to_remove:
        doc["artifacts"][0].pop(field, None)

    try:
        parse_job_document(doc)
        assert False, (
            f"parse_job_document should have raised ValueError for missing "
            f"artifact fields {fields_to_remove}, but it accepted the document"
        )
    except ValueError as exc:
        error_msg = str(exc)
        # The error message must mention each missing artifact field
        for field in fields_to_remove:
            assert field in error_msg, (
                f"ValueError message should mention missing artifact field "
                f"'{field}', but got: {error_msg}"
            )


# ---------------------------------------------------------------------------
# Strategies for Property 8
# ---------------------------------------------------------------------------

# Non-empty text for failure reasons and step names
non_empty_text_st = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

# Non-empty list of file path strings
file_path_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_./",
    min_size=5,
    max_size=200,
).map(lambda s: "/home/pi/" + s)

files_updated_st = st.lists(file_path_st, min_size=1, max_size=10)

# ISO-8601 timestamps via Hypothesis datetimes
iso_timestamp_st = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


# ---------------------------------------------------------------------------
# Property 8: Status detail completeness
# Feature: zumi-ota-updates, Property 8: Status detail completeness
# Validates: Requirements 7.2, 7.3
# ---------------------------------------------------------------------------

@given(
    reason=non_empty_text_st,
    step=non_empty_text_st,
    timestamp=iso_timestamp_st,
)
@settings(max_examples=200)
def test_failed_status_detail_completeness(reason, step, timestamp):
    """Property 8a: FAILED status details contain required fields.

    For any non-empty reason, non-empty step name, and valid ISO-8601
    timestamp, build_failed_status_detail SHALL produce a dict containing
    a non-empty ``reason``, a non-empty ``step``, and a valid ISO-8601
    ``timestamp``.

    **Validates: Requirements 7.2**
    """
    detail = build_failed_status_detail(reason, step, timestamp)

    # Must contain non-empty reason
    assert "reason" in detail
    assert isinstance(detail["reason"], str)
    assert len(detail["reason"]) > 0

    # Must contain non-empty step
    assert "step" in detail
    assert isinstance(detail["step"], str)
    assert len(detail["step"]) > 0

    # Must contain valid ISO-8601 timestamp
    assert "timestamp" in detail
    assert isinstance(detail["timestamp"], str)
    # Verify it parses as ISO-8601
    parsed_ts = datetime.fromisoformat(detail["timestamp"].replace("Z", "+00:00"))
    assert parsed_ts is not None

    # Values must match inputs
    assert detail["reason"] == reason
    assert detail["step"] == step
    assert detail["timestamp"] == timestamp


@given(
    files_updated=files_updated_st,
    artifact_sha256=sha256_hex,
    timestamp=iso_timestamp_st,
)
@settings(max_examples=200)
def test_succeeded_status_detail_completeness(files_updated, artifact_sha256, timestamp):
    """Property 8b: SUCCEEDED status details contain required fields.

    For any non-empty files_updated list, non-empty artifact_sha256 string,
    and valid ISO-8601 timestamp, build_succeeded_status_detail SHALL produce
    a dict containing a non-empty ``files_updated`` list, a non-empty
    ``artifact_sha256`` string, and a valid ISO-8601 ``timestamp``.

    **Validates: Requirements 7.3**
    """
    detail = build_succeeded_status_detail(files_updated, artifact_sha256, timestamp)

    # Must contain non-empty files_updated list
    assert "files_updated" in detail
    assert isinstance(detail["files_updated"], list)
    assert len(detail["files_updated"]) > 0

    # Must contain non-empty artifact_sha256
    assert "artifact_sha256" in detail
    assert isinstance(detail["artifact_sha256"], str)
    assert len(detail["artifact_sha256"]) > 0

    # Must contain valid ISO-8601 timestamp
    assert "timestamp" in detail
    assert isinstance(detail["timestamp"], str)
    # Verify it parses as ISO-8601
    parsed_ts = datetime.fromisoformat(detail["timestamp"].replace("Z", "+00:00"))
    assert parsed_ts is not None

    # Values must match inputs
    assert detail["files_updated"] == files_updated
    assert detail["artifact_sha256"] == artifact_sha256
    assert detail["timestamp"] == timestamp


# ---------------------------------------------------------------------------
# Imports for Property 5 and Property 6
# ---------------------------------------------------------------------------

import sys
import os
import hashlib
import tempfile

# Add scripts directory to path so we can import ota_agent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

# Mock awscrt and awsiot before importing ota_agent (same as test_ota_agent.py)
from unittest.mock import MagicMock

_mock_awscrt = MagicMock()
_mock_awsiot = MagicMock()
if 'awscrt' not in sys.modules:
    sys.modules['awscrt'] = _mock_awscrt
    sys.modules['awscrt.mqtt'] = _mock_awscrt.mqtt
    sys.modules['awscrt.io'] = _mock_awscrt.io
if 'awsiot' not in sys.modules:
    sys.modules['awsiot'] = _mock_awsiot
    sys.modules['awsiot.mqtt_connection_builder'] = _mock_awsiot.mqtt_connection_builder

from ota_agent import OTAAgent, RollbackManager, _pkcs1_v15_verify_rsa_sha256

# RSA key generation for Property 6 (cloud-side test env, Python 3.11+)
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization


# ---------------------------------------------------------------------------
# Helpers for Property 5
# ---------------------------------------------------------------------------

def _make_test_agent():
    """Create an OTAAgent with a mocked MQTT connection for property tests."""
    mock_conn = MagicMock()
    mock_future = MagicMock()
    mock_future.result.return_value = None
    mock_conn.subscribe.return_value = (mock_future, 1)
    config = {
        "ota_staging_dir": "/tmp/ota-staging",
        "ota_backup_dir": "/tmp/ota-backup",
        "ota_health_check_timeout": 60,
        "ota_download_retries": 3,
    }
    return OTAAgent(mock_conn, "prop-test-zumi", config)


# ---------------------------------------------------------------------------
# Strategies for Property 5
# ---------------------------------------------------------------------------

# Random byte strings for file content (1–10000 bytes)
file_content_st = st.binary(min_size=1, max_size=10000)

# Random byte strings that differ from the original (for wrong hash tests)
wrong_hex_char_st = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

# File sizes for size verification
positive_size_st = st.integers(min_value=1, max_value=10000)

# Non-zero size delta for mismatching sizes
nonzero_delta_st = st.integers(min_value=1, max_value=100000)


# ---------------------------------------------------------------------------
# Property 5: SHA-256 integrity verification
# Feature: zumi-ota-updates, Property 5: SHA-256 integrity verification
# Validates: Requirements 10.6, 10.7, 3.2
# ---------------------------------------------------------------------------

@given(content=file_content_st)
@settings(max_examples=200)
def test_sha256_correct_hash_accepted(content):
    """Property 5a: Correct SHA-256 hash is accepted.

    For any file content, computing the SHA-256 hex digest and passing it
    to _verify_hash SHALL return True.

    **Validates: Requirements 10.6, 10.7, 3.2**
    """
    agent = _make_test_agent()
    correct_hash = hashlib.sha256(content).hexdigest()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        assert agent._verify_hash(tmp_path, correct_hash) is True
    finally:
        os.unlink(tmp_path)


@given(content=file_content_st, wrong_hash=wrong_hex_char_st)
@settings(max_examples=200)
def test_sha256_incorrect_hash_rejected(content, wrong_hash):
    """Property 5b: Incorrect SHA-256 hash is rejected.

    For any file content paired with a hex digest that does NOT match
    the actual SHA-256, _verify_hash SHALL return False.

    **Validates: Requirements 10.6, 10.7, 3.2**
    """
    correct_hash = hashlib.sha256(content).hexdigest()
    # Ensure the wrong hash is actually different
    assume(wrong_hash.lower() != correct_hash.lower())

    agent = _make_test_agent()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        assert agent._verify_hash(tmp_path, wrong_hash) is False
    finally:
        os.unlink(tmp_path)


@given(content=file_content_st)
@settings(max_examples=200)
def test_file_size_matching_accepted(content):
    """Property 5c: Matching file size is accepted.

    For any file content, passing the correct byte length to
    _verify_file_size SHALL return True.

    **Validates: Requirements 10.6, 10.7, 3.2**
    """
    agent = _make_test_agent()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        assert agent._verify_file_size(tmp_path, len(content)) is True
    finally:
        os.unlink(tmp_path)


@given(content=file_content_st, delta=nonzero_delta_st)
@settings(max_examples=200)
def test_file_size_mismatching_rejected(content, delta):
    """Property 5d: Mismatching file size is rejected.

    For any file content paired with an expected size that differs
    from the actual size, _verify_file_size SHALL return False.

    **Validates: Requirements 10.6, 10.7, 3.2**
    """
    agent = _make_test_agent()
    wrong_size = len(content) + delta  # always differs since delta >= 1

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        assert agent._verify_file_size(tmp_path, wrong_size) is False
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Helpers for Property 6
# ---------------------------------------------------------------------------

def _generate_rsa_keypair(key_size=2048):
    """Generate an RSA key pair and return (private_key, public_pem_bytes)."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
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


# Generate fixed key pairs once at module level (expensive operation)
_PROP6_PRIVATE_KEY, _PROP6_PUBLIC_PEM = _generate_rsa_keypair()
_PROP6_WRONG_PRIVATE_KEY, _PROP6_WRONG_PUBLIC_PEM = _generate_rsa_keypair()


# ---------------------------------------------------------------------------
# Strategies for Property 6
# ---------------------------------------------------------------------------

# Random byte strings for signing (1–5000 bytes)
signable_content_st = st.binary(min_size=1, max_size=5000)


# ---------------------------------------------------------------------------
# Property 6: Code signature verification
# Feature: zumi-ota-updates, Property 6: Code signature verification
# Validates: Requirements 12.5, 12.7
# ---------------------------------------------------------------------------

@given(content=signable_content_st)
@settings(max_examples=100)
def test_valid_signature_accepted(content):
    """Property 6a: Valid RSA-SHA256 signature is accepted.

    For any file content signed with a test RSA private key, the
    signature verification function SHALL accept the file when
    verified against the corresponding public key.

    **Validates: Requirements 12.5, 12.7**
    """
    # Sign the content with the test private key
    signature = _sign_data(_PROP6_PRIVATE_KEY, content)
    file_digest = hashlib.sha256(content).digest()

    # Verify with the matching public key
    result = _pkcs1_v15_verify_rsa_sha256(
        _PROP6_PUBLIC_PEM, signature, file_digest
    )
    assert result is True


@given(content=signable_content_st)
@settings(max_examples=100)
def test_tampered_content_signature_rejected(content):
    """Property 6b: Signature on tampered content is rejected.

    For any file content signed with a test RSA private key, verifying
    the signature against different (tampered) content SHALL return False.

    **Validates: Requirements 12.5, 12.7**
    """
    # Sign the original content
    signature = _sign_data(_PROP6_PRIVATE_KEY, content)

    # Tamper with the content by flipping the first byte
    first_byte = content[0]
    tampered_byte = (first_byte + 1) % 256
    tampered_content = bytes([tampered_byte]) + content[1:]
    assume(tampered_content != content)

    tampered_digest = hashlib.sha256(tampered_content).digest()

    # Verify with the original signature but tampered digest
    result = _pkcs1_v15_verify_rsa_sha256(
        _PROP6_PUBLIC_PEM, signature, tampered_digest
    )
    assert result is False


@given(content=signable_content_st)
@settings(max_examples=100)
def test_wrong_key_signature_rejected(content):
    """Property 6c: Signature verified with wrong public key is rejected.

    For any file content signed with one RSA private key, verifying
    the signature against a different public key SHALL return False.

    **Validates: Requirements 12.5, 12.7**
    """
    # Sign with the correct private key
    signature = _sign_data(_PROP6_PRIVATE_KEY, content)
    file_digest = hashlib.sha256(content).digest()

    # Verify with the WRONG public key
    result = _pkcs1_v15_verify_rsa_sha256(
        _PROP6_WRONG_PUBLIC_PEM, signature, file_digest
    )
    assert result is False


# ---------------------------------------------------------------------------
# Imports for Property 3 and Property 4
# ---------------------------------------------------------------------------

import json
import shutil
import stat
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Strategies for Property 3
# ---------------------------------------------------------------------------

# Random binary content for files (1–1000 bytes)
backup_content_st = st.binary(min_size=1, max_size=1000)

# Random permission modes (valid octal range 0o000–0o777).
# We always set owner read+write (0o600) so backup/modify/rollback can
# operate on the file.  The remaining bits (group/other/execute) are random.
permission_mode_st = st.integers(min_value=0o000, max_value=0o777).map(
    lambda m: m | 0o600
)

# Simple safe filenames for temp files
safe_filename_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=3,
    max_size=20,
).map(lambda s: s + ".py")


# ---------------------------------------------------------------------------
# Property 3: Backup-rollback round-trip restores original files
# Feature: zumi-ota-updates, Property 3: Backup-rollback round-trip restores original files
# Validates: Requirements 4.1, 4.2, 4.3
# ---------------------------------------------------------------------------

@given(
    content=backup_content_st,
    permission_mode=permission_mode_st,
    filename=safe_filename_st,
)
@settings(max_examples=100)
def test_backup_rollback_round_trip(content, permission_mode, filename):
    """Property 3: Backup-rollback round-trip restores original files.

    For any set of target files with arbitrary content and permissions,
    performing a backup via RollbackManager.backup() followed by modifying
    the target files and then calling RollbackManager.rollback() SHALL
    restore each file to its original content, and the backup manifest
    SHALL accurately record the original path, backup path, and timestamp
    for each file.

    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    # Create temp directories for the test
    target_dir = tempfile.mkdtemp(prefix="prop3_target_")
    backup_dir = tempfile.mkdtemp(prefix="prop3_backup_")

    try:
        # Create the target file with random content and permissions
        target_path = os.path.join(target_dir, filename)
        with open(target_path, "wb") as f:
            f.write(content)
        os.chmod(target_path, permission_mode)

        # Create the RollbackManager with our temp backup dir
        rm = RollbackManager(backup_dir=backup_dir)

        # Mock subprocess.call to avoid actually calling systemctl
        with patch("subprocess.call") as mock_syscall:
            # Step 1: Backup the file
            rm.backup([target_path])

            # Verify manifest was written with correct metadata
            manifest_path = os.path.join(backup_dir, "manifest.json")
            assert os.path.isfile(manifest_path), "manifest.json should exist"

            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            # Manifest must have a timestamp
            assert "timestamp" in manifest
            assert len(manifest["timestamp"]) > 0

            # Manifest must have files list with correct metadata
            assert "files" in manifest
            assert len(manifest["files"]) == 1

            entry = manifest["files"][0]
            assert entry["original_path"] == target_path
            assert "backup_path" in entry
            assert os.path.isfile(entry["backup_path"])
            assert entry["permissions"] == "0o%03o" % permission_mode

            # Step 2: Modify the target file (simulate a bad update)
            with open(target_path, "wb") as f:
                f.write(b"MODIFIED CONTENT THAT IS DIFFERENT")
            os.chmod(target_path, 0o777)

            # Step 3: Rollback
            rm.rollback()

            # Step 4: Verify the file is restored to original content
            with open(target_path, "rb") as f:
                restored_content = f.read()
            assert restored_content == content, (
                "Restored content should match original"
            )

            # Step 5: Verify permissions are restored
            restored_mode = os.stat(target_path).st_mode & 0o777
            assert restored_mode == permission_mode, (
                "Restored permissions 0o%03o should match original 0o%03o"
                % (restored_mode, permission_mode)
            )

    finally:
        # Clean up temp directories
        shutil.rmtree(target_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Strategies for Property 4
# ---------------------------------------------------------------------------

# Strategy for a single file entry in a backup operation
backup_file_entry_st = st.fixed_dictionaries({
    "filename": safe_filename_st,
    "content": backup_content_st,
})

# Strategy for a single backup operation (1–3 files)
backup_operation_st = st.lists(
    backup_file_entry_st,
    min_size=1,
    max_size=3,
).filter(
    # Ensure unique filenames within a single operation
    lambda entries: len(set(e["filename"] for e in entries)) == len(entries)
)

# Strategy for a sequence of 2–5 backup operations
backup_sequence_st = st.lists(
    backup_operation_st,
    min_size=2,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Property 4: Only the most recent backup set is retained
# Feature: zumi-ota-updates, Property 4: Only the most recent backup set is retained
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------

@given(backup_sequence=backup_sequence_st)
@settings(max_examples=100)
def test_most_recent_backup_retention(backup_sequence):
    """Property 4: Only the most recent backup set is retained.

    For any sequence of two or more backup operations on different file
    sets, after the final backup completes, only the files from the most
    recent backup set SHALL exist in the backup directory, and all files
    from previous backup sets SHALL have been deleted.

    **Validates: Requirements 4.6**
    """
    target_dir = tempfile.mkdtemp(prefix="prop4_target_")
    backup_dir = tempfile.mkdtemp(prefix="prop4_backup_")

    try:
        rm = RollbackManager(backup_dir=backup_dir)

        # Execute each backup operation in sequence
        for operation in backup_sequence:
            # Create/overwrite target files for this operation
            target_paths = []
            for entry in operation:
                target_path = os.path.join(target_dir, entry["filename"])
                with open(target_path, "wb") as f:
                    f.write(entry["content"])
                target_paths.append(target_path)

            # Perform backup (this should also clean up old backups)
            rm.backup(target_paths)

        # After all backups, verify only the LAST backup set exists
        last_operation = backup_sequence[-1]
        last_filenames = set(entry["filename"] for entry in last_operation)

        # The backup directory should contain:
        # 1. manifest.json
        # 2. The backed-up files from the LAST operation only
        backup_contents = set(os.listdir(backup_dir))

        # manifest.json must exist
        assert "manifest.json" in backup_contents, (
            "manifest.json should exist in backup directory"
        )

        # Expected files: manifest.json + files from last backup
        expected_files = {"manifest.json"} | last_filenames
        assert backup_contents == expected_files, (
            "Backup directory should contain only manifest.json and "
            "files from the last backup. Expected: %s, Got: %s"
            % (expected_files, backup_contents)
        )

        # Verify manifest references only the last backup's files
        manifest_path = os.path.join(backup_dir, "manifest.json")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        manifest_filenames = set(
            os.path.basename(entry["backup_path"])
            for entry in manifest["files"]
        )
        assert manifest_filenames == last_filenames, (
            "Manifest should reference only the last backup's files. "
            "Expected: %s, Got: %s" % (last_filenames, manifest_filenames)
        )

    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 7: File permissions preserved on update
# Feature: zumi-ota-updates, Property 7: File permissions preserved on update
# Validates: Requirements 5.2
# ---------------------------------------------------------------------------

# Random permission modes (0o000–0o777) with minimum 0o600 for operability
permission_mode_update_st = st.integers(min_value=0o000, max_value=0o777).map(
    lambda m: m | 0o600
)

# Random binary content for staged artifacts
staged_content_st = st.binary(min_size=1, max_size=5000)


@given(
    permission_mode=permission_mode_update_st,
    original_content=staged_content_st,
    new_content=staged_content_st,
)
@settings(max_examples=200)
def test_file_permissions_preserved_on_update(permission_mode, original_content, new_content):
    """Property 7: File permissions preserved on update.

    For any original file with an arbitrary permission mode (within the
    valid octal range, with 0o600 minimum for operability), after the
    OTA Agent copies a staged artifact to the target path, the target
    file's permission mode SHALL match the original file's permission mode.

    **Validates: Requirements 5.2**
    """
    agent = _make_test_agent()

    target_dir = tempfile.mkdtemp(prefix="prop7_target_")
    staging_dir = tempfile.mkdtemp(prefix="prop7_staging_")

    try:
        # Create the original target file with the random permission mode
        target_path = os.path.join(target_dir, "target_file.py")
        with open(target_path, "wb") as f:
            f.write(original_content)
        os.chmod(target_path, permission_mode)

        # Verify the permission was set correctly
        original_actual = os.stat(target_path).st_mode & 0o777
        assert original_actual == permission_mode

        # Create the staged artifact with different content
        staging_path = os.path.join(staging_dir, "staged_file.py")
        with open(staging_path, "wb") as f:
            f.write(new_content)

        # Apply the update
        result = agent._apply_update(staging_path, target_path)
        assert result is True, "apply_update should succeed"

        # Verify the target file has the new content
        with open(target_path, "rb") as f:
            assert f.read() == new_content

        # Verify the permission mode is preserved
        updated_mode = os.stat(target_path).st_mode & 0o777
        assert updated_mode == permission_mode, (
            "Permission mode should be preserved after update. "
            "Expected 0o%03o, got 0o%03o" % (permission_mode, updated_mode)
        )

    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
        shutil.rmtree(staging_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 9: OTA Agent exception resilience
# Feature: zumi-ota-updates, Property 9: OTA Agent exception resilience
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------

# Strategy: random exception types from a predefined list
exception_type_st = st.sampled_from([
    ValueError,
    IOError,
    RuntimeError,
    TypeError,
    OSError,
    KeyError,
    AttributeError,
])

# Strategy: random exception messages
exception_message_st = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

# Exception types caught by the specific (ValueError, TypeError) handler
_SPECIFIC_EXCEPTION_TYPES = (ValueError, TypeError)


@given(
    exc_type=exception_type_st,
    exc_message=exception_message_st,
)
@settings(max_examples=200)
def test_exception_resilience(exc_type, exc_message):
    """Property 9: OTA Agent exception resilience.

    For any exception type raised within an OTA Agent job-processing
    callback, the exception SHALL be caught and logged without
    propagating to the caller, and the OTA Agent SHALL remain in a
    state where it can process subsequent job notifications.

    **Validates: Requirements 9.4**
    """
    agent = _make_test_agent()

    # Mock _process_job to raise the random exception
    with patch.object(agent, "_process_job", side_effect=exc_type(exc_message)):
        with patch.object(agent, "_report_failure") as mock_report_failure:
            with patch.object(agent, "_report_in_progress"):
                # Build a valid job notification payload
                payload = json.dumps({
                    "execution": {
                        "jobId": "test-job-resilience",
                        "jobDocument": {
                            "version": "1.0",
                            "operation": "update_files",
                            "artifacts": [{
                                "url": "https://example.com/artifact.py",
                                "target_path": "/home/pi/zumi-iot/test.py",
                                "file_size": 1234,
                                "sha256": "a" * 64,
                            }],
                            "post_action": "restart_service",
                        },
                    }
                }).encode("utf-8")

                # Call the notification handler — must NOT raise
                agent._on_job_notification(
                    topic="$aws/things/prop-test-zumi/jobs/notify-next",
                    payload=payload,
                    dup=False,
                    qos=0,
                    retain=False,
                )

                # Verify _report_failure was called (exception was caught)
                mock_report_failure.assert_called()
                call_args = mock_report_failure.call_args
                assert call_args[0][0] == "test-job-resilience"

                # ValueError and TypeError are caught by the specific
                # handler (parse_error step); all other exceptions are
                # caught by the catch-all handler (unhandled_error step).
                # Both paths report FAILED — the key property is that
                # the exception does NOT propagate.
                if issubclass(exc_type, _SPECIFIC_EXCEPTION_TYPES):
                    assert call_args[0][1] in (
                        "parse_error", "unsupported_version", "missing_fields"
                    )
                else:
                    assert call_args[0][1] == "unhandled_error"

    # Verify the agent is still operational — can process another notification
    with patch.object(agent, "_process_job") as mock_process:
        with patch.object(agent, "_report_in_progress"):
            payload2 = json.dumps({
                "execution": {
                    "jobId": "test-job-subsequent",
                    "jobDocument": {
                        "version": "1.0",
                        "operation": "update_files",
                        "artifacts": [{
                            "url": "https://example.com/artifact2.py",
                            "target_path": "/home/pi/zumi-iot/test2.py",
                            "file_size": 5678,
                            "sha256": "b" * 64,
                        }],
                        "post_action": "restart_service",
                    },
                }
            }).encode("utf-8")

            agent._on_job_notification(
                topic="$aws/things/prop-test-zumi/jobs/notify-next",
                payload=payload2,
                dup=False,
                qos=0,
                retain=False,
            )

            # Verify the subsequent job was processed (agent still works)
            mock_process.assert_called_once()
            assert mock_process.call_args[0][0] == "test-job-subsequent"
