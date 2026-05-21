"""
Articraft MCP Server — Articulated 3D Asset Generation & Retrieval

MCP Server 1: Generator (runs on ECS Fargate)
- generate_asset: Create new articulated 3D models from text descriptions
- fork_asset: Modify existing models
- list_categories: Browse available object categories
- get_generation_status: Check async generation progress

Transport: SSE (HTTP) for remote access from AgentCore Gateway
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import boto3
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("articraft-mcp")

# Config
S3_BUCKET = os.environ.get("ARTICRAFT_S3_BUCKET", "articraft-assets")
S3_REGION = os.environ.get("AWS_REGION", "us-west-2")
ARTICRAFT_WORKDIR = os.environ.get("ARTICRAFT_WORKDIR", "/opt/articraft")
LLM_MODEL = os.environ.get("ARTICRAFT_MODEL", "anthropic.claude-sonnet-4-20250514")
MAX_COST_USD = float(os.environ.get("ARTICRAFT_MAX_COST_USD", "2.0"))

s3 = boto3.client("s3", region_name=S3_REGION)
dynamodb = boto3.resource("dynamodb", region_name=S3_REGION)
jobs_table = dynamodb.Table(os.environ.get("JOBS_TABLE", "articraft-jobs"))

mcp = FastMCP(
    "articraft-generator",
    description="Generate and manage articulated 3D assets (URDF) using Articraft",
)


@mcp.tool()
async def generate_asset(
    description: str,
    category: str = "general",
    model: str | None = None,
    max_cost_usd: float | None = None,
) -> dict:
    """Generate a new articulated 3D asset from a text description.

    The asset will be generated with semantic parts, joints, and physics-ready URDF output.
    Generation is async — returns a job_id to poll with get_generation_status.

    Args:
        description: Detailed description of the articulated object to generate.
                    Example: "A desk lamp with a weighted base, two hinged arms, and adjustable head"
        category: Object category slug (e.g. "furniture", "electronics", "tools"). Default "general".
        model: LLM model to use for generation. Default uses server config.
        max_cost_usd: Maximum generation cost in USD. Default 2.0.

    Returns:
        dict with job_id, status, and estimated_time_seconds.
    """
    job_id = str(uuid.uuid4())
    use_model = model or LLM_MODEL
    cost_limit = max_cost_usd or MAX_COST_USD

    # Store job metadata
    jobs_table.put_item(Item={
        "job_id": job_id,
        "status": "running",
        "description": description,
        "category": category,
        "model": use_model,
        "max_cost_usd": str(cost_limit),
        "created_at": str(asyncio.get_event_loop().time()),
    })

    # Run generation in background
    asyncio.create_task(_run_generation(job_id, description, category, use_model, cost_limit))

    return {
        "job_id": job_id,
        "status": "running",
        "description": description,
        "estimated_time_seconds": 60,
        "message": f"Generation started. Poll with get_generation_status(job_id='{job_id}')",
    }


async def _run_generation(
    job_id: str, description: str, category: str, model: str, max_cost: float
):
    """Background task: run articraft generate and upload result to S3."""
    try:
        output_dir = Path(tempfile.mkdtemp(prefix=f"articraft-{job_id[:8]}-"))

        # Run articraft CLI
        cmd = [
            "uv", "run", "articraft", "generate",
            "--model", model,
            "--max-cost-usd", str(max_cost),
            "--output-dir", str(output_dir),
            "--category", category,
            description,
        ]

        log.info(f"[{job_id}] Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=ARTICRAFT_WORKDIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode()[-500:]
            jobs_table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, error_message = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": error_msg},
            )
            log.error(f"[{job_id}] Generation failed: {error_msg}")
            return

        # Find output files (URDF + meshes)
        urdf_files = list(output_dir.rglob("*.urdf"))
        if not urdf_files:
            jobs_table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, error_message = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": "No URDF generated"},
            )
            return

        # Upload all output files to S3
        s3_prefix = f"generated/{category}/{job_id}/"
        uploaded_files = []

        for fpath in output_dir.rglob("*"):
            if fpath.is_file():
                s3_key = s3_prefix + str(fpath.relative_to(output_dir))
                s3.upload_file(str(fpath), S3_BUCKET, s3_key)
                uploaded_files.append(s3_key)

        # Find the main URDF key
        urdf_key = next(k for k in uploaded_files if k.endswith(".urdf"))

        # Update job status
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, s3_prefix = :p, urdf_key = :u, file_count = :f",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "completed",
                ":p": s3_prefix,
                ":u": urdf_key,
                ":f": len(uploaded_files),
            },
        )
        log.info(f"[{job_id}] Completed. {len(uploaded_files)} files → s3://{S3_BUCKET}/{s3_prefix}")

    except Exception as e:
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, error_message = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":e": str(e)[:500]},
        )
        log.exception(f"[{job_id}] Unexpected error")


@mcp.tool()
async def get_generation_status(job_id: str) -> dict:
    """Check the status of an asset generation job.

    Args:
        job_id: The job ID returned by generate_asset.

    Returns:
        dict with status (running/completed/failed), and s3 location if completed.
    """
    response = jobs_table.get_item(Key={"job_id": job_id})
    item = response.get("Item")

    if not item:
        return {"error": f"Job {job_id} not found"}

    result = {
        "job_id": job_id,
        "status": item["status"],
        "description": item.get("description", ""),
    }

    if item["status"] == "completed":
        # Generate presigned URL for the URDF
        urdf_key = item.get("urdf_key", "")
        if urdf_key:
            presigned_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": urdf_key},
                ExpiresIn=3600,
            )
            result["urdf_url"] = presigned_url
            result["s3_prefix"] = item.get("s3_prefix", "")
            result["file_count"] = int(item.get("file_count", 0))

    elif item["status"] == "failed":
        result["error"] = item.get("error_message", "Unknown error")

    return result


@mcp.tool()
async def fork_asset(
    record_id: str,
    modification: str,
    model: str | None = None,
) -> dict:
    """Fork an existing articulated asset and apply modifications.

    Creates a new asset based on an existing one with the requested changes.

    Args:
        record_id: The record ID of the existing asset to fork.
        modification: Description of changes to apply (e.g. "make the handle longer").
        model: LLM model to use. Default uses server config.

    Returns:
        dict with job_id for the forked generation.
    """
    job_id = str(uuid.uuid4())
    use_model = model or LLM_MODEL

    jobs_table.put_item(Item={
        "job_id": job_id,
        "status": "running",
        "description": f"Fork of {record_id}: {modification}",
        "parent_record": record_id,
        "model": use_model,
        "created_at": str(asyncio.get_event_loop().time()),
    })

    asyncio.create_task(_run_fork(job_id, record_id, modification, use_model))

    return {
        "job_id": job_id,
        "status": "running",
        "parent_record": record_id,
        "modification": modification,
        "message": f"Fork started. Poll with get_generation_status(job_id='{job_id}')",
    }


async def _run_fork(job_id: str, record_id: str, modification: str, model: str):
    """Background task: fork an existing record."""
    try:
        # Download parent record from S3 if needed
        output_dir = Path(tempfile.mkdtemp(prefix=f"articraft-fork-{job_id[:8]}-"))

        cmd = [
            "uv", "run", "articraft", "fork",
            f"data/records/{record_id}",
            "--model", model,
            "--output-dir", str(output_dir),
            modification,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=ARTICRAFT_WORKDIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            jobs_table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, error_message = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": stderr.decode()[-500:]},
            )
            return

        # Upload result
        s3_prefix = f"generated/forks/{job_id}/"
        uploaded = []
        for fpath in output_dir.rglob("*"):
            if fpath.is_file():
                s3_key = s3_prefix + str(fpath.relative_to(output_dir))
                s3.upload_file(str(fpath), S3_BUCKET, s3_key)
                uploaded.append(s3_key)

        urdf_key = next((k for k in uploaded if k.endswith(".urdf")), "")

        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, s3_prefix = :p, urdf_key = :u, file_count = :f",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "completed", ":p": s3_prefix, ":u": urdf_key, ":f": len(uploaded),
            },
        )

    except Exception as e:
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, error_message = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":e": str(e)[:500]},
        )


@mcp.tool()
async def list_categories() -> dict:
    """List available articulated object categories in the dataset.

    Returns:
        dict with categories list including name, count, and example objects.
    """
    # Categories from Articraft-10K dataset
    categories = [
        {"slug": "furniture", "name": "Furniture", "examples": ["desk lamp", "office chair", "filing cabinet"], "count": 1200},
        {"slug": "electronics", "name": "Electronics", "examples": ["laptop", "monitor with stand", "printer"], "count": 980},
        {"slug": "appliances", "name": "Appliances", "examples": ["washing machine", "microwave", "refrigerator"], "count": 850},
        {"slug": "tools", "name": "Tools & Equipment", "examples": ["drill press", "microscope", "clamp"], "count": 720},
        {"slug": "vehicles", "name": "Vehicles & Parts", "examples": ["car door", "excavator arm", "landing gear"], "count": 650},
        {"slug": "kitchen", "name": "Kitchen & Dining", "examples": ["faucet", "bottle with cap", "pepper grinder"], "count": 580},
        {"slug": "industrial", "name": "Industrial", "examples": ["robotic arm", "vending machine", "conveyor gate"], "count": 520},
        {"slug": "music", "name": "Musical Instruments", "examples": ["piano lid", "MIDI keyboard", "guitar case"], "count": 380},
        {"slug": "toys", "name": "Toys & Games", "examples": ["action figure", "slot machine", "toy crane"], "count": 350},
        {"slug": "general", "name": "General / Other", "examples": ["scissors", "stapler", "umbrella"], "count": 2770},
    ]
    return {"categories": categories, "total_assets": 10000}


@mcp.tool()
async def download_asset(record_id: str) -> dict:
    """Download an existing asset from the Articraft-10K dataset.

    Generates a presigned S3 URL for the URDF package.

    Args:
        record_id: The record identifier (from search results or dataset).

    Returns:
        dict with presigned download URL and asset metadata.
    """
    # Check in dataset bucket
    s3_key = f"dataset/{record_id}.tar.gz"

    try:
        # Verify object exists
        s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
    except s3.exceptions.ClientError:
        # Try alternative key patterns
        s3_key = f"dataset/{record_id}/model.urdf"
        try:
            s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        except Exception:
            return {"error": f"Asset {record_id} not found in dataset"}

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=3600,
    )

    return {
        "record_id": record_id,
        "download_url": url,
        "format": "URDF",
        "expires_in_seconds": 3600,
    }


if __name__ == "__main__":
    import sys

    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "sse":
        # SSE transport for remote access (AgentCore Gateway)
        port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.run(transport="sse", port=port)
    else:
        # stdio transport for local testing
        mcp.run(transport="stdio")
