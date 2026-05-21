"""
Articraft Knowledge Base MCP Server — RAG over 10K articulated 3D assets

MCP Server 2: Dataset search and retrieval via Bedrock Knowledge Base.
Searches the Articraft-10K dataset metadata for existing articulated objects.

Transport: SSE (HTTP) for remote access from AgentCore Gateway
"""

import os
import json
import logging

import boto3
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("articraft-kb-mcp")

# Config
S3_BUCKET = os.environ.get("ARTICRAFT_S3_BUCKET", "articraft-assets")
S3_REGION = os.environ.get("AWS_REGION", "us-west-2")
KB_ID = os.environ.get("ARTICRAFT_KB_ID", "")  # Bedrock Knowledge Base ID

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=S3_REGION)
s3 = boto3.client("s3", region_name=S3_REGION)

mcp = FastMCP(
    "articraft-knowledge-base",
    description="Search and retrieve existing articulated 3D assets from Articraft-10K dataset",
)


@mcp.tool()
async def search_assets(
    query: str,
    max_results: int = 5,
    category: str | None = None,
) -> dict:
    """Search the Articraft-10K dataset for existing articulated 3D assets.

    Uses RAG retrieval over object descriptions, joint configurations,
    and part hierarchies. Returns matching assets with metadata.

    Args:
        query: Natural language search query.
               Examples: "desk lamp with adjustable arm", "robot gripper with 3 fingers"
        max_results: Maximum number of results to return (1-20). Default 5.
        category: Optional category filter (furniture, electronics, tools, etc.)

    Returns:
        dict with matching assets including record_id, description, joints, and similarity score.
    """
    if not KB_ID:
        return {"error": "ARTICRAFT_KB_ID not configured"}

    # Build retrieval query
    retrieval_query = query
    if category:
        retrieval_query = f"[category: {category}] {query}"

    try:
        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": retrieval_query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": min(max_results, 20),
                }
            },
        )

        results = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            score = item.get("score", 0.0)
            location = item.get("location", {})

            # Parse metadata from content
            result = {
                "score": round(score, 3),
                "description": content[:300],
                "source": location.get("s3Location", {}).get("uri", ""),
            }

            # Try to extract structured metadata
            try:
                if "record_id:" in content:
                    for line in content.split("\n"):
                        if line.startswith("record_id:"):
                            result["record_id"] = line.split(":", 1)[1].strip()
                        elif line.startswith("category:"):
                            result["category"] = line.split(":", 1)[1].strip()
                        elif line.startswith("joints:"):
                            result["joints"] = line.split(":", 1)[1].strip()
                        elif line.startswith("parts:"):
                            result["parts"] = line.split(":", 1)[1].strip()
            except Exception:
                pass

            results.append(result)

        return {
            "query": query,
            "results": results,
            "total_found": len(results),
        }

    except Exception as e:
        log.exception("KB retrieval failed")
        return {"error": str(e)}


@mcp.tool()
async def get_asset_metadata(record_id: str) -> dict:
    """Get detailed metadata for a specific asset from the dataset.

    Args:
        record_id: The record identifier from search results.

    Returns:
        dict with full metadata: description, parts list, joint definitions,
        dimensions, and download info.
    """
    # Try to fetch metadata JSON from S3
    metadata_key = f"dataset/metadata/{record_id}.json"

    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=metadata_key)
        metadata = json.loads(response["Body"].read())
        return metadata
    except s3.exceptions.NoSuchKey:
        pass
    except Exception as e:
        log.warning(f"Failed to fetch metadata for {record_id}: {e}")

    # Fallback: check index
    index_key = "dataset/records_index.jsonl"
    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=index_key)
        for line in response["Body"].iter_lines():
            record = json.loads(line)
            if record.get("record_id") == record_id:
                return record
    except Exception:
        pass

    return {"error": f"Metadata not found for {record_id}"}


@mcp.tool()
async def get_asset_urdf(record_id: str) -> dict:
    """Get a presigned download URL for an asset's URDF package.

    The URDF can be loaded directly into Isaac Sim or any physics simulator.

    Args:
        record_id: The record identifier.

    Returns:
        dict with presigned URL for the URDF tar.gz package.
    """
    # Articraft-10K stores assets as tar.gz files
    # Try the HuggingFace-style naming
    possible_keys = [
        f"dataset/{record_id}.tar.gz",
        f"dataset/{record_id}/model.urdf",
        f"dataset/records/{record_id}.tar.gz",
    ]

    for s3_key in possible_keys:
        try:
            s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": s3_key},
                ExpiresIn=3600,
            )
            return {
                "record_id": record_id,
                "download_url": url,
                "s3_key": s3_key,
                "format": "URDF (tar.gz)",
                "expires_in_seconds": 3600,
                "usage": "Extract tar.gz, load model.urdf into Isaac Sim or any URDF-compatible simulator",
            }
        except Exception:
            continue

    return {"error": f"URDF not found for {record_id}. Try search_assets to find valid IDs."}


@mcp.tool()
async def list_dataset_stats() -> dict:
    """Get statistics about the Articraft-10K dataset.

    Returns:
        dict with total assets, categories, joint types, and recent additions.
    """
    return {
        "dataset": "Articraft-10K",
        "source": "https://huggingface.co/datasets/camvsl/Articraft-10K",
        "total_assets": 10000,
        "format": "URDF with meshes (tar.gz per record)",
        "license": "CC-BY-4.0",
        "categories": [
            "furniture", "electronics", "appliances", "tools",
            "vehicles", "kitchen", "industrial", "music", "toys", "general",
        ],
        "joint_types": ["revolute", "prismatic", "fixed", "continuous"],
        "typical_structure": {
            "parts": "3-15 semantic parts per object",
            "joints": "2-8 articulated joints per object",
            "meshes": "STL/OBJ geometry per part",
        },
        "compatible_simulators": [
            "NVIDIA Isaac Sim (USD import)",
            "MuJoCo",
            "PyBullet",
            "Gazebo",
            "ROS 2 (robot_description)",
        ],
    }


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "sse":
        port = int(os.environ.get("MCP_PORT", "8081"))
        mcp.run(transport="sse", port=port)
    else:
        mcp.run(transport="stdio")
