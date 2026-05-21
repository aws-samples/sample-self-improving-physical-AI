#!/usr/bin/env python3
"""
Upload Articraft-10K dataset from HuggingFace to S3 and build knowledge index.

Steps:
1. Download dataset records from HuggingFace
2. Upload tar.gz files to S3
3. Extract metadata (description, joints, parts) from each record
4. Build records_index.jsonl for Bedrock KB ingestion
5. Upload metadata docs to S3 for Knowledge Base

Usage:
    python upload_dataset.py --bucket articraft-assets-ACCOUNT_ID --max-records 100
"""

import argparse
import json
import logging
import os
import tarfile
import tempfile
from pathlib import Path

import boto3
from huggingface_hub import HfApi, hf_hub_download, list_repo_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DATASET_REPO = "camvsl/Articraft-10K"
S3_REGION = os.environ.get("AWS_REGION", "us-west-2")


def extract_metadata_from_tar(tar_path: Path) -> dict:
    """Extract metadata from an Articraft record tar.gz."""
    metadata = {"file": tar_path.name}

    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            members = tar.getnames()
            metadata["files"] = members

            # Look for metadata.json or model.py
            for member in members:
                if member.endswith("metadata.json"):
                    f = tar.extractfile(member)
                    if f:
                        meta = json.loads(f.read())
                        metadata.update(meta)
                        break
                elif member.endswith("model.py"):
                    f = tar.extractfile(member)
                    if f:
                        content = f.read().decode("utf-8", errors="ignore")
                        # Extract description from docstring
                        if '"""' in content:
                            doc = content.split('"""')[1] if '"""' in content else ""
                            metadata["description"] = doc[:500]
                        # Count joints
                        metadata["joint_count"] = content.count("Joint(")
                        metadata["part_count"] = content.count("Part(") + content.count("add_part")

            # Check for URDF
            urdf_files = [m for m in members if m.endswith(".urdf")]
            metadata["has_urdf"] = len(urdf_files) > 0
            metadata["urdf_files"] = urdf_files

    except Exception as e:
        metadata["error"] = str(e)

    return metadata


def build_kb_document(record_id: str, metadata: dict) -> str:
    """Build a text document for Bedrock KB ingestion."""
    lines = [
        f"record_id: {record_id}",
        f"category: {metadata.get('category', 'general')}",
        f"description: {metadata.get('description', metadata.get('file', ''))}",
        f"joints: {metadata.get('joint_count', 'unknown')}",
        f"parts: {metadata.get('part_count', 'unknown')}",
        f"has_urdf: {metadata.get('has_urdf', False)}",
    ]

    if "files" in metadata:
        lines.append(f"files: {', '.join(metadata['files'][:20])}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Upload Articraft-10K to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--max-records", type=int, default=None, help="Max records to process")
    parser.add_argument("--region", default=S3_REGION, help="AWS region")
    parser.add_argument("--skip-upload", action="store_true", help="Skip S3 upload, only build index")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    api = HfApi()

    # List all files in the dataset
    log.info(f"Listing files in {DATASET_REPO}...")
    all_files = list_repo_files(DATASET_REPO, repo_type="dataset")
    tar_files = [f for f in all_files if f.endswith(".tar.gz")]
    log.info(f"Found {len(tar_files)} tar.gz records")

    if args.max_records:
        tar_files = tar_files[:args.max_records]

    # Process records
    index_entries = []
    kb_docs = []

    for i, filename in enumerate(tar_files):
        log.info(f"[{i+1}/{len(tar_files)}] Processing {filename}")

        # Derive record_id from filename
        record_id = filename.replace(".tar.gz", "")

        try:
            # Download from HuggingFace
            local_path = hf_hub_download(
                repo_id=DATASET_REPO,
                filename=filename,
                repo_type="dataset",
                cache_dir=tempfile.gettempdir(),
            )

            # Upload to S3
            if not args.skip_upload:
                s3_key = f"dataset/{filename}"
                s3.upload_file(local_path, args.bucket, s3_key)
                log.info(f"  Uploaded to s3://{args.bucket}/{s3_key}")

            # Extract metadata
            metadata = extract_metadata_from_tar(Path(local_path))
            metadata["record_id"] = record_id
            metadata["s3_key"] = f"dataset/{filename}"

            index_entries.append(metadata)

            # Build KB doc
            kb_doc = build_kb_document(record_id, metadata)
            kb_docs.append({"record_id": record_id, "content": kb_doc})

        except Exception as e:
            log.error(f"  Failed: {e}")
            continue

    # Upload index
    index_path = "/tmp/records_index.jsonl"
    with open(index_path, "w") as f:
        for entry in index_entries:
            f.write(json.dumps(entry) + "\n")

    s3.upload_file(index_path, args.bucket, "dataset/records_index.jsonl")
    log.info(f"Uploaded index with {len(index_entries)} records")

    # Upload KB documents (one per record for Bedrock KB)
    for doc in kb_docs:
        doc_key = f"kb-docs/{doc['record_id']}.txt"
        s3.put_object(
            Bucket=args.bucket,
            Key=doc_key,
            Body=doc["content"].encode(),
            ContentType="text/plain",
        )

    log.info(f"Uploaded {len(kb_docs)} KB documents to s3://{args.bucket}/kb-docs/")
    log.info("Done! Next: create Bedrock KB with S3 data source pointing to kb-docs/")


if __name__ == "__main__":
    main()
