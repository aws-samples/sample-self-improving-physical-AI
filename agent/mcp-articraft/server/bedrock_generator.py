"""
Standalone 3D asset generator using Bedrock + CadQuery.
Runs inside ECS Fargate. Generates articulated URDF from text description.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import boto3

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
S3_BUCKET = os.environ.get("ARTICRAFT_S3_BUCKET", "articraft-assets")
JOB_ID = os.environ.get("JOB_ID", "test")
DESCRIPTION = os.environ.get("DESCRIPTION", "a simple box")
CATEGORY = os.environ.get("CATEGORY", "general")
MODEL_ID = "global.anthropic.claude-opus-4-6-v1"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
jobs_table = dynamodb.Table("articraft-jobs")


def update_status(status, **kwargs):
    expr = "SET #s = :s"
    names = {"#s": "status"}
    values = {":s": status}
    for k, v in kwargs.items():
        expr += f", {k} = :{k}"
        values[f":{k}"] = v
    jobs_table.update_item(
        Key={"job_id": JOB_ID},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def invoke_bedrock(prompt):
    """Call Bedrock Converse API."""
    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.7},
    )
    return response["output"]["message"]["content"][0]["text"]


def generate():
    update_status("generating")
    
    # Step 1: Generate CadQuery code for the object
    prompt = textwrap.dedent(f"""
    Generate CadQuery Python code that creates an articulated 3D object: "{DESCRIPTION}"
    
    Requirements:
    - Use CadQuery to create the object with multiple parts
    - Each part should be a separate solid that can be exported as an STL mesh
    - Include comments describing each part
    - Export each part as a separate STL file in a directory
    - Print the part names and joint types at the end
    
    Output ONLY the Python code, no explanation. The code should:
    1. Import cadquery
    2. Create parts as CadQuery objects
    3. Export each part to /tmp/output/meshes/<part_name>.stl
    4. Print a JSON summary: {{"parts": ["part1", "part2", ...], "joints": [{{"parent": "part1", "child": "part2", "type": "revolute", "axis": [0,0,1]}}]}}
    
    Make sure to create /tmp/output/meshes/ directory first.
    """)
    
    print(f"Generating CadQuery code for: {DESCRIPTION}")
    code = invoke_bedrock(prompt)
    
    # Extract code from markdown if needed
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    # Save code
    os.makedirs("/tmp/output/meshes", exist_ok=True)
    code_path = "/tmp/output/generate.py"
    with open(code_path, "w") as f:
        f.write(code)
    
    print(f"Generated code ({len(code)} chars), executing...")
    update_status("compiling")
    
    # Step 2: Run the CadQuery code
    result = subprocess.run(
        [sys.executable, code_path],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": "/opt/articraft"}
    )
    
    print(f"CadQuery stdout: {result.stdout[-500:]}")
    if result.returncode != 0:
        print(f"CadQuery stderr: {result.stderr[-500:]}")
        # Try to fix common errors and retry
        fix_prompt = f"""The following CadQuery code failed with error:
Code:
```python
{code[:2000]}
```

Error:
{result.stderr[-500:]}

Fix the code. Output ONLY the corrected Python code, no explanation."""
        
        fixed_code = invoke_bedrock(fix_prompt)
        if "```python" in fixed_code:
            fixed_code = fixed_code.split("```python")[1].split("```")[0]
        elif "```" in fixed_code:
            fixed_code = fixed_code.split("```")[1].split("```")[0]
        
        with open(code_path, "w") as f:
            f.write(fixed_code)
        
        result = subprocess.run(
            [sys.executable, code_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            update_status("failed", error_message=f"CadQuery failed: {result.stderr[-300:]}")
            return
    
    # Step 3: Parse output and generate URDF
    meshes = list(Path("/tmp/output/meshes").glob("*.stl"))
    if not meshes:
        # Fallback: create a basic mesh
        update_status("failed", error_message="No mesh files generated")
        return
    
    # Try to parse JSON summary from stdout
    parts_info = {"parts": [m.stem for m in meshes], "joints": []}
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("{") and "parts" in line:
            try:
                parts_info = json.loads(line)
            except json.JSONDecodeError:
                pass
    
    # Generate URDF
    urdf = generate_urdf(parts_info, DESCRIPTION)
    urdf_path = "/tmp/output/model.urdf"
    with open(urdf_path, "w") as f:
        f.write(urdf)
    
    print(f"Generated URDF with {len(meshes)} meshes")
    update_status("uploading")
    
    # Step 4: Upload to S3
    s3_prefix = f"generated/{CATEGORY}/{JOB_ID}/"
    uploaded = []
    
    for fpath in Path("/tmp/output").rglob("*"):
        if fpath.is_file():
            s3_key = s3_prefix + str(fpath.relative_to(Path("/tmp/output")))
            s3.upload_file(str(fpath), S3_BUCKET, s3_key)
            uploaded.append(s3_key)
    
    urdf_key = s3_prefix + "model.urdf"
    
    update_status(
        "completed",
        s3_prefix=s3_prefix,
        urdf_key=urdf_key,
        file_count=len(uploaded),
    )
    print(f"Done! {len(uploaded)} files uploaded to s3://{S3_BUCKET}/{s3_prefix}")


def generate_urdf(parts_info, description):
    """Generate a URDF file from parts info."""
    parts = parts_info.get("parts", [])
    joints = parts_info.get("joints", [])
    
    links = ""
    for part in parts:
        links += f"""
  <link name="{part}">
    <visual>
      <geometry><mesh filename="meshes/{part}.stl"/></geometry>
    </visual>
    <collision>
      <geometry><mesh filename="meshes/{part}.stl"/></geometry>
    </collision>
    <inertial>
      <mass value="0.1"/>
      <inertia ixx="0.001" ixy="0" ixz="0" iyy="0.001" iyz="0" izz="0.001"/>
    </inertial>
  </link>"""
    
    joint_xml = ""
    for i, joint in enumerate(joints):
        jtype = joint.get("type", "revolute")
        parent = joint.get("parent", parts[0] if parts else "base")
        child = joint.get("child", parts[min(i+1, len(parts)-1)] if parts else "part")
        axis = joint.get("axis", [0, 0, 1])
        joint_xml += f"""
  <joint name="joint_{i}" type="{jtype}">
    <parent link="{parent}"/>
    <child link="{child}"/>
    <axis xyz="{axis[0]} {axis[1]} {axis[2]}"/>
    <limit lower="-1.57" upper="1.57" effort="10" velocity="1"/>
  </joint>"""
    
    # If no joints defined, chain parts sequentially
    if not joints and len(parts) > 1:
        for i in range(len(parts) - 1):
            joint_xml += f"""
  <joint name="joint_{i}" type="revolute">
    <parent link="{parts[i]}"/>
    <child link="{parts[i+1]}"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.57" upper="1.57" effort="10" velocity="1"/>
  </joint>"""
    
    return f"""<?xml version="1.0"?>
<robot name="{description[:50].replace('"', '')}">
{links}
{joint_xml}
</robot>"""


if __name__ == "__main__":
    generate()
