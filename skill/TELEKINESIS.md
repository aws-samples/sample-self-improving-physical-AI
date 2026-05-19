---
name: telekinesis
description: Use Telekinesis Agentic Skill Library for robot control, computer vision, and Physical AI tasks. Use when asked to control real robots (UR10e, Franka, etc.), run computer vision (segmentation, detection, point clouds), generate robot code from natural language, use BabyROS middleware, or build perception-to-action pipelines. Covers Synapse (robotics), Cornea (segmentation), Retina (detection), Vitreous (point clouds), Pupil (image processing), Illusion (synthetic data), and Medulla (hardware).
---

# Telekinesis — Physical AI Agentic Skill Library

Unified Python library for robotics, perception, and Physical AI applications.
Docs: https://docs.telekinesis.ai/

## Prerequisites

| Component | Required |
|-----------|----------|
| Python | 3.11 or 3.12 |
| Package | `pip install telekinesis-ai` |
| API Key | Set `TELEKINESIS_API_KEY` env var |
| BabyROS (optional) | `pip install babyros` |

```bash
pip install telekinesis-ai
export TELEKINESIS_API_KEY="your_key_here"
```

## Module Overview

| Module | Import | Purpose |
|--------|--------|---------|
| Synapse | `from telekinesis import synapse` | Robotics (kinematics, planning, control) |
| Cornea | `from telekinesis import cornea` | Image segmentation (SAM, color, region) |
| Retina | `from telekinesis import retina` | Object detection (YOLOX, DINO, Hough) |
| Pupil | `from telekinesis import pupil` | Image processing (morph, edges, denoise) |
| Vitreous | `from telekinesis import vitreous` | Point cloud processing (filter, register) |
| Illusion | `from telekinesis import illusion` | Synthetic data generation |
| Iris | `from telekinesis import iris` | AI model training/evaluation |
| Medulla | `from telekinesis.medulla import cameras` | Hardware (cameras, sensors) |

## Synapse — Robotics Skills

### Supported Robots
- **Manipulators**: Universal Robots (UR3e-UR20e), Franka, ABB, Fanuc, Kuka, Motoman, Neura
- **Mobile Robots & Quadrupeds**: ANYbotics ANYmal
- **Humanoids**: Various (expanding)

### Connect & Move
```python
from telekinesis.synapse.robots.manipulators.universal_robots import UniversalRobotsUR10E

robot = UniversalRobotsUR10E()
robot.connect(ip="192.168.1.2")

# Joint space motion
robot.set_joint_positions(
    joint_positions=[0, -90, 90, -90, -90, 0],
    speed=60, acceleration=80, asynchronous=False
)

# Cartesian motion
robot.set_cartesian_pose(
    pose=[0.5, 0.2, 0.3, 0, 3.14, 0],  # [x, y, z, rx, ry, rz]
    speed=0.25, acceleration=1.2
)

robot.disconnect()
```

### Kinematics
```python
from telekinesis.synapse.robots.manipulators.universal_robots import UniversalRobotsUR10E

robot = UniversalRobotsUR10E()

# Forward kinematics
fk_result = robot.forward_kinematics(joint_positions=[0, -90, 90, -90, -90, 0])

# Inverse kinematics
robot.setup_kinematics_solver(solver_name="CLIC")
ik_result = robot.inverse_kinematics(target_pose=[0.5, 0.2, 0.3, 0, 3.14, 0])

# Get all link transforms
transforms = robot.get_link_transforms(joint_positions=[0, -90, 90, -90, -90, 0])
```

### Motion Planning
```python
# Collision-aware path planning (RRT/RRT*)
trajectory = robot.motion_planning(
    target_joint_positions=[0, -90, 90, -90, -90, 0],
    obstacles=[...]  # collision objects
)
```

### Key Motion Skills
| Skill | Description |
|-------|-------------|
| `set_joint_positions` | Move to target joint config |
| `set_cartesian_pose` | Move to Cartesian pose |
| `set_cartesian_pose_in_joint_space` | Cartesian target via joint interpolation |
| `move_until_contact` | Approach until force contact |
| `stop_cartesian_motion` | Emergency stop (Cartesian) |
| `stop_joint_motion` | Emergency stop (joint) |
| `trigger_protective_stop` | Immediate halt |

### Gripper Control
```python
from telekinesis.synapse.robots.manipulators.universal_robots import UniversalRobotsUR10E

robot = UniversalRobotsUR10E()
robot.connect(ip="192.168.1.2")

# Gripper open/close (via set_joint_positions or gripper-specific API)
robot.set_gripper_position(position=0)     # fully closed
robot.set_gripper_position(position=100)   # fully open
```

## Cornea — Image Segmentation

```python
from telekinesis import cornea

# SAM-based segmentation
result = cornea.segment_image_using_sam(
    image=image,
    bboxes=[[400, 150, 1200, 450]]
)
annotations = result.to_list()

# Color-based segmentation (HSV, RGB, LAB)
mask = cornea.segment_image_using_hsv(
    image=image,
    lower_bound=[20, 100, 100],
    upper_bound=[40, 255, 255]
)

# BiRefNet foreground segmentation
foreground = cornea.segment_foreground_using_birefnet(image=image)
```

## Retina — Object Detection

```python
from telekinesis import retina

# YOLOX detection
detections = retina.detect_objects_using_yolox(image=image)

# Open-vocabulary detection (Grounding DINO)
detections = retina.detect_objects_using_grounding_dino(
    image=image,
    text_prompt="orange fruit on counter"
)

# Qwen-VL detection
detections = retina.detect_objects_using_qwen_vl(
    image=image,
    text_prompt="robot gripper"
)
```

## Vitreous — Point Cloud Processing

```python
from telekinesis import vitreous

# Load and filter
pc = vitreous.load_point_cloud('scene.ply')
downsampled = vitreous.filter_point_cloud_using_voxel_downsampling(
    point_cloud=pc, voxel_size=0.01
)

# Segmentation
clusters = vitreous.segment_point_cloud_using_dbscan(
    point_cloud=pc, eps=0.02, min_points=10
)

# Registration (ICP)
transform = vitreous.register_point_clouds_using_icp(
    source=pc1, target=pc2, method="point_to_plane"
)

# 6D Pose Estimation
pose = vitreous.estimate_pose_from_point_cloud(
    point_cloud=object_pc, reference_model=cad_model
)
```

## Medulla — Hardware / Cameras

```python
from telekinesis.medulla import cameras

# Webcam capture
webcam = cameras.webcam.Webcam(name="cam_0", camera_id=0)
webcam.connect()
frame = webcam.capture_color_image()  # RGB numpy array
webcam.disconnect()

# RealSense depth camera
realsense = cameras.realsense.RealSense(name="depth_cam")
realsense.connect()
color, depth = realsense.capture_rgbd()
realsense.disconnect()
```

## Physical AI Agents (Tzara)

Generate executable robot code from natural language prompts.

### Code-as-Policy Pattern
```
User Instruction → LLM/VLM Reasoning → Skill Selection → Generated Python → Execution
```

### Example Prompt
```
I have a UR10e and an RG6 gripper. Pick parts from a grid and place them
in a new grid with a fixed offset. Open gripper partially for close parts.
```
→ Generates complete Python using Telekinesis Skills.

### Integration with Isaac Sim
Telekinesis Synapse skills can target Isaac Sim for simulation-first workflows:
```python
# Same kinematics/planning skills work in sim and real
robot = UniversalRobotsUR10E()
# In sim: connects to Isaac Sim controller
# On real: connects to actual UR10e
```

## BabyROS — Lightweight Middleware

ROS-style pub/sub without DDS complexity. Built on Zenoh.

```bash
pip install babyros
```

```python
import babyros

# Publisher
pub = babyros.Publisher(topic="/robot/joint_states")
pub.publish({"positions": [0, -90, 90, -90, -90, 0]})

# Subscriber
def callback(msg):
    print(f"Received: {msg}")

sub = babyros.Subscriber(topic="/robot/joint_states", callback=callback)
```

### Key Advantages over ROS 2
| Pain Point | BabyROS Solution |
|-----------|-----------------|
| Complex DDS setup | Zenoh (ultra-low latency) |
| .msg file definitions | Dynamic Python serialization |
| Local-network only | Native cloud-to-device |
| Heavy containers | Single `pip install` |

## Integration with Our Platform

### Isaac Sim → Telekinesis Sim2Real
```python
# 1. Train/test in Isaac Sim (our existing pipeline)
# 2. Record episodes to DynamoDB
# 3. Use Telekinesis Synapse for real robot execution

from telekinesis.synapse.robots.manipulators.hiwonder import SOArm101  # if supported
# OR use LeRobot + Telekinesis vision for perception
from telekinesis import cornea, retina

# Detect orange in real camera
frame = webcam.capture_color_image()
detections = retina.detect_objects_using_grounding_dino(
    image=frame, text_prompt="orange"
)

# Use detection to guide robot motion
target_pos = detections[0].center_3d  # from depth
```

### Perception + Control Pipeline
```python
from telekinesis import cornea, vitreous, synapse
from telekinesis.medulla import cameras

# 1. Capture
cam = cameras.realsense.RealSense(name="wrist_cam")
cam.connect()
color, depth = cam.capture_rgbd()

# 2. Segment target object
mask = cornea.segment_image_using_sam(image=color, bboxes=[bbox])

# 3. Get 3D position from point cloud
pc = vitreous.create_point_cloud_from_rgbd(color, depth, intrinsics)
object_pc = vitreous.filter_point_cloud_using_mask(pc, mask)
centroid = vitreous.get_centroid(object_pc)

# 4. Plan and execute grasp
robot.set_cartesian_pose(pose=[*centroid, 0, 3.14, 0])
robot.set_gripper_position(position=0)  # close
```

## Critical Notes

1. **Python 3.11/3.12 only** — will not work with 3.10 or lower
2. **API key required** — free tier available, set `TELEKINESIS_API_KEY`
3. **Sim2Real consistency** — same Synapse skills work in Isaac Sim and on real hardware
4. **BabyROS ≠ ROS 2** — simpler, faster, but different ecosystem
5. **Code-as-Policy** — agents generate auditable code, not opaque end-to-end policies
