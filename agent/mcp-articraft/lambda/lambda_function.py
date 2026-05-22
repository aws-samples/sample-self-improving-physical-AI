import json
import logging
import os
import uuid

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("ARTICRAFT_S3_BUCKET", "articraft-assets")
KB_ID = os.environ.get("ARTICRAFT_KB_ID", "Z4XPFY4Y3C")
REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))
ECS_CLUSTER = os.environ.get("ECS_CLUSTER", "articraft")
TASK_DEF = os.environ.get("TASK_DEFINITION", "articraft-generator:2")
SUBNETS = [s.strip() for s in os.environ.get("SUBNETS", "subnet-031dc3925b5d551a4").split(",") if s.strip()]
SECURITY_GROUP = os.environ.get("SECURITY_GROUP", "sg-08abb2271d69b3d79")

bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
ecs = boto3.client("ecs", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
jobs_table = dynamodb.Table("articraft-jobs")


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
    for s3_key in [f"dataset/{record_id}.tar.gz"]:
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


def generate_asset(description, category="general", model=None, max_cost_usd=2.0):
    """Launch ECS Fargate task for async 3D generation using Bedrock + CadQuery."""
    job_id = str(uuid.uuid4())

    jobs_table.put_item(Item={
        "job_id": job_id,
        "status": "launching",
        "description": description,
        "category": category,
    })

    try:
        response = ecs.run_task(
            cluster=ECS_CLUSTER,
            taskDefinition=TASK_DEF,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": SUBNETS,
                    "securityGroups": [SECURITY_GROUP],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": "generator",
                    "environment": [
                        {"name": "JOB_ID", "value": job_id},
                        {"name": "DESCRIPTION", "value": description},
                        {"name": "CATEGORY", "value": category},
                    ],
                }],
            },
        )
        task_arn = response["tasks"][0]["taskArn"] if response.get("tasks") else "unknown"
        failures = response.get("failures", [])
        if failures:
            error = failures[0].get("reason", "Unknown")
            jobs_table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, error_message = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": error},
            )
            return {"job_id": job_id, "status": "failed", "error": error}

        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, task_arn = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "running", ":t": task_arn},
        )

        return {
            "job_id": job_id,
            "status": "running",
            "description": description,
            "estimated_time_seconds": 180,
            "message": f"Generation task launched (Bedrock + CadQuery). Poll: get_generation_status(job_id='{job_id}')",
        }
    except Exception as e:
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, error_message = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":e": str(e)[:500]},
        )
        return {"job_id": job_id, "status": "failed", "error": str(e)}


def get_generation_status(job_id):
    response = jobs_table.get_item(Key={"job_id": job_id})
    item = response.get("Item")
    if not item:
        return {"error": f"Job {job_id} not found"}

    result = {"job_id": job_id, "status": item["status"], "description": item.get("description", "")}

    if item["status"] == "completed":
        urdf_key = item.get("urdf_key", "")
        if urdf_key:
            url = s3.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": urdf_key}, ExpiresIn=3600)
            result["urdf_url"] = url
            result["s3_prefix"] = item.get("s3_prefix", "")
            result["file_count"] = int(item.get("file_count", 0))
    elif item["status"] == "failed":
        result["error"] = item.get("error_message", "Unknown")

    return result


def fork_asset(record_id, modification, model=None):
    return generate_asset(f"Fork of {record_id}: {modification}", category="fork")


def list_categories():
    return {
        "categories": [
            {"slug": "furniture", "name": "Furniture", "count": 1200},
            {"slug": "electronics", "name": "Electronics", "count": 980},
            {"slug": "appliances", "name": "Appliances", "count": 850},
            {"slug": "tools", "name": "Tools & Equipment", "count": 720},
            {"slug": "vehicles", "name": "Vehicles & Parts", "count": 650},
            {"slug": "kitchen", "name": "Kitchen & Dining", "count": 580},
            {"slug": "industrial", "name": "Industrial", "count": 520},
            {"slug": "music", "name": "Musical Instruments", "count": 380},
            {"slug": "toys", "name": "Toys & Games", "count": 350},
            {"slug": "general", "name": "General / Other", "count": 2770},
        ],
        "total": 10000,
    }


def handler(event, context):
    log.info(f"Event: {json.dumps(event)}")

    tool = ""
    explicit = event.get("toolName", event.get("name", event.get("tool", "")))
    if "___" in explicit:
        explicit = explicit.split("___", 1)[1]
    if explicit:
        tool = explicit

    if not tool:
        if "description" in event and "query" not in event:
            tool = "generate_asset"
        elif "job_id" in event and "query" not in event and "record_id" not in event:
            tool = "get_generation_status"
        elif "record_id" in event and "modification" in event:
            tool = "fork_asset"
        elif "query" in event:
            tool = "search_assets"
        elif "record_id" in event:
            tool = "get_asset_urdf"
        else:
            tool = "list_dataset_stats"

    log.info(f"Routing to: {tool}")

    dispatch = {
        "search_assets": lambda: search_assets(event.get("query",""), event.get("max_results",5), event.get("category")),
        "get_asset_urdf": lambda: get_asset_urdf(event.get("record_id","")),
        "get_asset_metadata": lambda: get_asset_metadata(event.get("record_id","")),
        "list_dataset_stats": lambda: list_dataset_stats(),
        "generate_asset": lambda: generate_asset(event.get("description",""), event.get("category","general"), event.get("model"), event.get("max_cost_usd",2.0)),
        "get_generation_status": lambda: get_generation_status(event.get("job_id","")),
        "fork_asset": lambda: fork_asset(event.get("record_id",""), event.get("modification",""), event.get("model")),
        "list_categories": lambda: list_categories(),
    }

    func = dispatch.get(tool)
    if not func:
        return {"error": f"Unknown tool: {tool}", "available": list(dispatch.keys())}

    try:
        return func()
    except Exception as e:
        log.exception("Tool failed")
        return {"error": str(e)}
