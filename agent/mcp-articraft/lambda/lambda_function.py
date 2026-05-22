import json
import logging
import os

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("ARTICRAFT_S3_BUCKET", "articraft-assets")
KB_ID = os.environ.get("ARTICRAFT_KB_ID", "Z4XPFY4Y3C")
REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))

bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)


def search_assets(query, max_results=5, category=None):
    retrieval_query = f"[category: {category}] {query}" if category else query
    response = bedrock_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": retrieval_query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": min(int(max_results), 20)}},
    )
    results = []
    for item in response.get("retrievalResults", []):
        content = item.get("content", {}).get("text", "")
        score = item.get("score", 0.0)
        result = {"score": round(score, 3), "description": content[:300]}
        for line in content.split("\n"):
            if line.startswith("record_id:"): result["record_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("category:"): result["category"] = line.split(":", 1)[1].strip()
        results.append(result)
    return {"query": query, "results": results, "total_found": len(results)}


def get_asset_urdf(record_id):
    possible_keys = [f"dataset/{record_id}.tar.gz"]
    for s3_key in possible_keys:
        try:
            s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
            url = s3.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": s3_key}, ExpiresIn=3600)
            return {"record_id": record_id, "download_url": url, "format": "URDF (tar.gz)"}
        except Exception:
            continue
    return {"error": f"URDF not found for {record_id}"}


def get_asset_metadata(record_id):
    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=f"kb-docs/{record_id}.txt")
        content = response["Body"].read().decode()
        metadata = {}
        for line in content.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                metadata[k.strip()] = v.strip()
        return metadata
    except Exception:
        return {"error": f"Metadata not found for {record_id}"}


def list_dataset_stats():
    return {
        "dataset": "Articraft-10K", "total_assets": 10000, "format": "URDF (tar.gz)",
        "license": "CC-BY-4.0",
        "categories": ["furniture","electronics","appliances","tools","vehicles","kitchen","industrial","music","toys","general"],
        "simulators": ["NVIDIA Isaac Sim","MuJoCo","PyBullet","Gazebo","ROS 2"],
    }


def handler(event, context):
    """Route based on event structure — AgentCore passes params directly as event."""
    log.info(f"Event: {json.dumps(event)}")
    
    # Try to get tool name from various AgentCore formats
    tool_name = event.get("toolName", event.get("name", event.get("tool", "")))
    
    # Strip prefix if present
    if "___" in tool_name:
        tool_name = tool_name.split("___", 1)[1]
    
    # If no tool name, infer from params
    if not tool_name:
        if "query" in event:
            tool_name = "search_assets"
        elif "record_id" in event:
            # Could be urdf or metadata — check if there's a hint
            tool_name = "get_asset_urdf"  # default to urdf
        else:
            tool_name = "list_dataset_stats"
    
    log.info(f"Resolved tool: {tool_name}")
    
    try:
        if tool_name == "search_assets":
            result = search_assets(
                query=event.get("query", ""),
                max_results=event.get("max_results", 5),
                category=event.get("category"),
            )
        elif tool_name == "get_asset_urdf":
            result = get_asset_urdf(event.get("record_id", ""))
        elif tool_name == "get_asset_metadata":
            result = get_asset_metadata(event.get("record_id", ""))
        elif tool_name == "list_dataset_stats":
            result = list_dataset_stats()
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        
        return result  # Return directly, not wrapped in statusCode
    except Exception as e:
        log.exception("Tool failed")
        return {"error": str(e)}
