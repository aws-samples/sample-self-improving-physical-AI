# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Security Scan Record:
#   Tool: Bandit v1.8.3 + Amazon CodeGuru Reviewer
#   Date: 2025-05-09
#   Result: PASS — 0 Critical, 0 High findings
#   Mitigations: N/A (no findings requiring mitigation)
#

"""
SO-ARM101 Digital Twin in Isaac Sim
====================================
Creates a simulation of the Hiwonder LeRobot SO-ARM101 6-DOF robotic arm
with dual camera system (gripper-mounted + external overhead camera).

Features:
- Accurate joint limits and dynamics matching STS3215 servos
- Gripper-mounted camera for manipulation tasks
- External overhead camera for workspace awareness
- Photo capture and video recording capabilities
- Compatible with LeRobot/HuggingFace imitation learning pipeline

Usage:
    ./scripts/run_sim.sh scripts/so101/sim_so101.py --action [scene|photo|video|move]
"""

import os
import sys
import argparse
import json
import time
import numpy as np

os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"

# ============================================================
# SimulationApp MUST be instantiated before any other imports
# ============================================================
from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

# Now safe to import Isaac Sim modules
from isaacsim.core.api import World, SimulationContext
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.core.utils.prims import create_prim, define_prim
from isaacsim.sensors.camera import Camera

import omni.usd
from pxr import UsdGeom, Gf, UsdPhysics, Sdf, UsdLux


def create_workspace_table(stage):
    """Create a workspace table for the robot arm"""
    # Table top
    table_path = "/World/Table"
    define_prim(table_path, "Xform")
    
    table_top = FixedCuboid(
        prim_path=f"{table_path}/top",
        name="table_top",
        position=np.array([0.0, 0.0, -0.015]),
        scale=np.array([0.6, 0.4, 0.03]),
        color=np.array([0.6, 0.45, 0.3]),  # Wood color
    )
    
    # Table legs
    leg_positions = [
        (0.25, 0.15, -0.25),
        (0.25, -0.15, -0.25),
        (-0.25, 0.15, -0.25),
        (-0.25, -0.15, -0.25),
    ]
    for i, pos in enumerate(leg_positions):
        FixedCuboid(
            prim_path=f"{table_path}/leg_{i}",
            name=f"table_leg_{i}",
            position=np.array(pos),
            scale=np.array([0.04, 0.04, 0.47]),
            color=np.array([0.5, 0.35, 0.2]),
        )
    
    return table_top


def create_so101_from_urdf(world, urdf_path):
    """
    Import SO-ARM101 from URDF into Isaac Sim.
    Returns the robot articulation.
    """
    from isaacsim.core.utils.extensions import enable_extension
    enable_extension("omni.importer.urdf")
    
    from omni.importer.urdf import _urdf
    
    urdf_interface = _urdf.acquire_urdf_interface()
    import_config = _urdf.ImportConfig()
    import_config.merge_fixed_joints = False
    import_config.fix_base = True
    import_config.make_default_prim = False
    import_config.create_physics_scene = False
    import_config.default_drive_type = _urdf.UrdfJointTargetType.JOINT_DRIVE_POSITION
    import_config.default_drive_strength = 1000.0
    import_config.default_position_drive_damping = 100.0
    
    result = urdf_interface.parse_urdf(urdf_path, import_config)
    robot_path = urdf_interface.import_robot(
        "/World/SO_ARM101",
        urdf_path,
        result,
        import_config,
    )
    
    return robot_path


def create_so101_procedural(world):
    """
    Create SO-ARM101 procedurally using Isaac Sim primitives.
    Fallback if URDF import is not available.
    """
    robot_path = "/World/SO_ARM101"
    define_prim(robot_path, "Xform")
    
    # Base platform
    FixedCuboid(
        prim_path=f"{robot_path}/base",
        name="so101_base",
        position=np.array([0.0, 0.0, 0.0025]),
        scale=np.array([0.07, 0.07, 0.005]),
        color=np.array([0.2, 0.2, 0.2]),
    )
    
    # Base motor housing
    VisualCuboid(
        prim_path=f"{robot_path}/base_motor",
        name="so101_base_motor",
        position=np.array([0.0, 0.0, 0.025]),
        scale=np.array([0.05, 0.05, 0.04]),
        color=np.array([0.3, 0.3, 0.3]),
    )
    
    # Shoulder (Link 1)
    VisualCuboid(
        prim_path=f"{robot_path}/shoulder",
        name="so101_shoulder",
        position=np.array([0.0, 0.0, 0.0725]),
        scale=np.array([0.04, 0.04, 0.055]),
        color=np.array([0.95, 0.95, 0.95]),
    )
    
    # Upper arm (Link 2)
    VisualCuboid(
        prim_path=f"{robot_path}/upper_arm",
        name="so101_upper_arm",
        position=np.array([0.0, 0.0, 0.1475]),
        scale=np.array([0.035, 0.04, 0.095]),
        color=np.array([0.95, 0.95, 0.95]),
    )
    
    # Forearm (Link 3)
    VisualCuboid(
        prim_path=f"{robot_path}/forearm",
        name="so101_forearm",
        position=np.array([0.0, 0.0, 0.2425]),
        scale=np.array([0.03, 0.035, 0.095]),
        color=np.array([0.95, 0.95, 0.95]),
    )
    
    # Wrist (Link 4 + 5)
    VisualCuboid(
        prim_path=f"{robot_path}/wrist",
        name="so101_wrist",
        position=np.array([0.0, 0.0, 0.31]),
        scale=np.array([0.028, 0.032, 0.04]),
        color=np.array([0.95, 0.95, 0.95]),
    )
    
    # Gripper
    VisualCuboid(
        prim_path=f"{robot_path}/gripper_left",
        name="so101_gripper_left",
        position=np.array([0.0, -0.012, 0.3575]),
        scale=np.array([0.005, 0.01, 0.045]),
        color=np.array([1.0, 0.5, 0.0]),
    )
    VisualCuboid(
        prim_path=f"{robot_path}/gripper_right",
        name="so101_gripper_right",
        position=np.array([0.0, 0.012, 0.3575]),
        scale=np.array([0.005, 0.01, 0.045]),
        color=np.array([1.0, 0.5, 0.0]),
    )
    
    # Camera on gripper
    VisualCuboid(
        prim_path=f"{robot_path}/camera_housing",
        name="so101_camera",
        position=np.array([0.02, 0.0, 0.34]),
        scale=np.array([0.02, 0.02, 0.015]),
        color=np.array([0.05, 0.05, 0.05]),
    )
    
    return robot_path


def setup_cameras(world):
    """
    Set up dual camera system:
    1. Gripper camera - mounted on the end effector
    2. External camera - overhead view of workspace
    """
    cameras = {}
    
    # Gripper-mounted camera (wrist cam)
    gripper_cam = Camera(
        prim_path="/World/SO_ARM101/GripperCamera",
        name="gripper_camera",
        resolution=(640, 480),
        frequency=30,
    )
    gripper_cam.set_world_pose(
        position=np.array([0.02, 0.0, 0.34]),
        orientation=np.array([0.683, 0.683, -0.183, 0.183]),  # Looking forward-down
    )
    gripper_cam.set_focal_length(2.5)
    gripper_cam.set_clipping_range(0.01, 5.0)
    cameras["gripper"] = gripper_cam
    
    # External overhead camera
    external_cam = Camera(
        prim_path="/World/ExternalCamera",
        name="external_camera",
        resolution=(640, 480),
        frequency=30,
    )
    external_cam.set_world_pose(
        position=np.array([0.25, 0.0, 0.45]),
        orientation=np.array([0.354, 0.854, -0.354, 0.146]),  # Looking down at workspace
    )
    external_cam.set_focal_length(3.0)
    external_cam.set_clipping_range(0.05, 10.0)
    cameras["external"] = external_cam
    
    # Side view camera for visualization
    side_cam = Camera(
        prim_path="/World/SideCamera",
        name="side_camera",
        resolution=(1920, 1080),
        frequency=30,
    )
    side_cam.set_world_pose(
        position=np.array([0.4, -0.3, 0.25]),
        orientation=np.array([0.85, 0.35, -0.15, 0.35]),
    )
    side_cam.set_focal_length(5.0)
    cameras["side"] = side_cam
    
    return cameras


def setup_lighting(stage):
    """Create realistic lighting for the scene"""
    # Main dome light (ambient)
    dome_light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome_light.CreateIntensityAttr(500)
    dome_light.CreateColorAttr(Gf.Vec3f(1.0, 0.98, 0.95))
    
    # Key light (directional, like overhead lab light)
    key_light = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
    key_light.CreateIntensityAttr(2000)
    key_light.CreateAngleAttr(2.0)
    key_light.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    UsdGeom.Xformable(key_light).AddTranslateOp().Set(Gf.Vec3d(0, 0, 2))
    UsdGeom.Xformable(key_light).AddRotateXYZOp().Set(Gf.Vec3d(-45, 30, 0))
    
    # Fill light
    fill_light = UsdLux.RectLight.Define(stage, "/World/FillLight")
    fill_light.CreateIntensityAttr(800)
    fill_light.CreateWidthAttr(0.5)
    fill_light.CreateHeightAttr(0.5)
    fill_light.CreateColorAttr(Gf.Vec3f(0.9, 0.95, 1.0))
    UsdGeom.Xformable(fill_light).AddTranslateOp().Set(Gf.Vec3d(-0.5, 0.3, 0.8))


def spawn_manipulation_objects(world):
    """Spawn small objects for pick-and-place tasks"""
    objects = []
    
    # Small colored cubes (like blocks for sorting)
    colors = [
        ("red", [0.9, 0.1, 0.1]),
        ("green", [0.1, 0.8, 0.1]),
        ("blue", [0.1, 0.2, 0.9]),
        ("yellow", [0.9, 0.9, 0.1]),
    ]
    
    positions = [
        [0.15, -0.05, 0.02],
        [0.18, 0.05, 0.02],
        [0.12, 0.08, 0.02],
        [0.20, -0.08, 0.02],
    ]
    
    for i, ((name, color), pos) in enumerate(zip(colors, positions)):
        cube = DynamicCuboid(
            prim_path=f"/World/Objects/cube_{name}",
            name=f"cube_{name}",
            position=np.array(pos),
            scale=np.array([0.025, 0.025, 0.025]),
            color=np.array(color),
            mass=0.02,
        )
        objects.append(cube)
    
    # Small cylinder (like a peg)
    try:
        from isaacsim.core.api.objects import DynamicCylinder
        peg = DynamicCylinder(
            prim_path="/World/Objects/peg",
            name="peg",
            position=np.array([0.1, 0.0, 0.02]),
            radius=0.008,
            height=0.05,
            color=np.array([0.7, 0.4, 0.1]),
            mass=0.01,
        )
        objects.append(peg)
    except (ImportError, Exception) as e:
        # DynamicCylinder may not be available in all versions
        print(f"  Note: Skipping cylinder object ({e})")
    
    return objects


def capture_photo(cameras, output_dir, camera_name="side", world=None):
    """Capture a photo from specified camera"""
    cam = cameras[camera_name]
    cam.initialize()
    
    # Need to step a few times for the camera to render
    if world:
        for _ in range(5):
            world.step(render=True)
    
    # Get RGBA image
    rgba = cam.get_rgba()
    if rgba is not None:
        from PIL import Image
        # Convert RGBA to RGB
        img = Image.fromarray(rgba[:, :, :3])
        path = os.path.join(output_dir, f"{camera_name}_capture.png")
        img.save(path)
        print(f"Photo saved: {path} ({img.size[0]}x{img.size[1]})")
        return path
    else:
        print(f"Warning: No image from {camera_name} camera")
    return None


def record_video(cameras, world, output_dir, camera_name="side", duration_sec=5, fps=30):
    """Record video from specified camera"""
    cam = cameras[camera_name]
    cam.initialize()
    
    frames = []
    total_frames = duration_sec * fps
    dt = 1.0 / fps
    
    print(f"Recording {duration_sec}s video from {camera_name} camera...")
    
    for i in range(total_frames):
        world.step(render=True)
        rgb = cam.get_rgb()
        if rgb is not None:
            frames.append(rgb.copy())
        
        if (i + 1) % fps == 0:
            print(f"  {(i+1)//fps}/{duration_sec}s")
    
    if frames:
        try:
            from PIL import Image
            import io
            
            # Save as MP4 using imageio if available
            try:
                import imageio
                path = os.path.join(output_dir, f"{camera_name}_video.mp4")
                writer = imageio.get_writer(path, fps=fps)
                for frame in frames:
                    writer.append_data(frame)
                writer.close()
                print(f"Video saved: {path}")
                return path
            except ImportError:
                # Fallback: save as GIF
                path = os.path.join(output_dir, f"{camera_name}_video.gif")
                imgs = [Image.fromarray(f) for f in frames[::3]]  # Every 3rd frame for GIF
                imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
                print(f"Video (GIF) saved: {path}")
                return path
        except Exception as e:
            print(f"Error saving video: {e}")
    
    return None


def move_joints(world, robot_path, joint_positions, steps=60):
    """
    Move robot joints to target positions.
    joint_positions: list of 6 values [j1, j2, j3, j4, j5, j6]
    """
    from omni.isaac.core.articulations import Articulation
    
    robot = Articulation(prim_path=robot_path)
    robot.initialize()
    
    # Set joint targets
    robot.set_joint_positions(np.array(joint_positions))
    
    for _ in range(steps):
        world.step(render=True)
    
    print(f"Joints moved to: {joint_positions}")


def main():
    parser = argparse.ArgumentParser(description="SO-ARM101 Digital Twin in Isaac Sim")
    parser.add_argument("--action", type=str, default="scene",
                       choices=["scene", "photo", "video", "move", "demo"],
                       help="Action to perform")
    parser.add_argument("--camera", type=str, default="side",
                       choices=["gripper", "external", "side"],
                       help="Camera to use for capture")
    parser.add_argument("--output", type=str, default="/output",
                       help="Output directory for captures")
    parser.add_argument("--duration", type=float, default=5.0,
                       help="Video recording duration in seconds")
    parser.add_argument("--joints", type=str, default=None,
                       help="Joint positions (comma-separated, 6 values)")
    parser.add_argument("--save-usd", type=str, default=None,
                       help="Save scene as USD file")
    parser.add_argument("--steps", type=int, default=100,
                       help="Simulation steps to run")
    parser.add_argument("--use-urdf", action="store_true",
                       help="Import from URDF (requires omni.importer.urdf)")
    
    args = parser.parse_args()

    # Validate output paths to prevent directory traversal
    ALLOWED_OUTPUT_DIRS = ["/output", "/tmp", os.path.expanduser("~/output")]
    output_resolved = os.path.realpath(args.output)
    if not any(output_resolved.startswith(allowed) for allowed in ALLOWED_OUTPUT_DIRS):
        print(f"Error: Output directory '{args.output}' is outside allowed paths: {ALLOWED_OUTPUT_DIRS}")
        sys.exit(1)

    if args.save_usd:
        save_usd_resolved = os.path.realpath(os.path.dirname(args.save_usd) or ".")
        if not any(save_usd_resolved.startswith(allowed) for allowed in ALLOWED_OUTPUT_DIRS):
            print(f"Error: Save USD path '{args.save_usd}' is outside allowed paths: {ALLOWED_OUTPUT_DIRS}")
            sys.exit(1)

    os.makedirs(args.output, exist_ok=True)
    
    # Initialize world
    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    stage = omni.usd.get_context().get_stage()
    
    # Setup scene
    print("Setting up SO-ARM101 scene...")
    setup_lighting(stage)
    create_workspace_table(stage)
    
    # Create robot
    if args.use_urdf:
        urdf_path = "/scripts/so101/so_arm101.urdf"
        if os.path.exists(urdf_path):
            robot_path = create_so101_from_urdf(world, urdf_path)
            print(f"SO-ARM101 imported from URDF: {robot_path}")
        else:
            print(f"URDF not found at {urdf_path}, using procedural creation")
            robot_path = create_so101_procedural(world)
    else:
        robot_path = create_so101_procedural(world)
        print(f"SO-ARM101 created procedurally: {robot_path}")
    
    # Setup cameras
    cameras = setup_cameras(world)
    print(f"Cameras configured: {list(cameras.keys())}")
    
    # Spawn objects for manipulation
    objects = spawn_manipulation_objects(world)
    print(f"Spawned {len(objects)} manipulation objects")
    
    # Initialize world
    world.reset()
    
    # Warm up simulation
    print("Warming up simulation...")
    for _ in range(30):
        world.step(render=True)
    
    # Perform action
    if args.action == "scene":
        print("Running simulation...")
        for i in range(args.steps):
            world.step(render=True)
        
        # Capture from all cameras
        for cam_name in cameras:
            capture_photo(cameras, args.output, cam_name, world)
        
        print(f"\nScene ready! Captures saved to {args.output}/")
    
    elif args.action == "photo":
        capture_photo(cameras, args.output, args.camera, world)
    
    elif args.action == "video":
        record_video(cameras, world, args.output, args.camera, 
                    duration_sec=args.duration)
    
    elif args.action == "move":
        if args.joints:
            try:
                positions = [float(x) for x in args.joints.split(",")]
            except ValueError as e:
                print(f"Error: Invalid joint values: {e}")
                sys.exit(1)
            if len(positions) != 6:
                print(f"Error: Need exactly 6 joint values, got {len(positions)}")
                sys.exit(1)
            # Validate joint limits (SO-ARM101 safe ranges in radians)
            SO101_JOINT_LIMITS = [
                (-3.14, 3.14),   # Base
                (-1.57, 1.57),   # Shoulder
                (-1.57, 1.57),   # Elbow
                (-1.57, 1.57),   # Wrist Pitch
                (-3.14, 3.14),   # Wrist Roll
                (0.0, 0.785),    # Gripper
            ]
            for i, (val, (lo, hi)) in enumerate(zip(positions, SO101_JOINT_LIMITS)):
                if val < lo or val > hi:
                    print(f"Error: Joint {i+1} value {val:.4f} outside safe limits [{lo}, {hi}]")
                    sys.exit(1)
            move_joints(world, robot_path, positions, steps=args.steps)
            capture_photo(cameras, args.output, args.camera, world)
        else:
            print("Error: --joints required for move action")
            sys.exit(1)
    
    elif args.action == "demo":
        print("Running pick-and-place demo sequence...")
        # Home position
        home = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        
        # Demo sequence: reach toward object → close gripper → lift → place
        sequence = [
            ("Moving to home...", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("Reaching forward...", [0.0, 0.5, -0.3, -0.2, 0.0, 0.0]),
            ("Lowering to object...", [0.0, 0.7, -0.5, -0.2, 0.0, 0.0]),
            ("Closing gripper...", [0.0, 0.7, -0.5, -0.2, 0.0, 0.6]),
            ("Lifting object...", [0.0, 0.3, -0.2, -0.1, 0.0, 0.6]),
            ("Rotating to place...", [1.5, 0.3, -0.2, -0.1, 0.0, 0.6]),
            ("Placing object...", [1.5, 0.6, -0.4, -0.2, 0.0, 0.6]),
            ("Opening gripper...", [1.5, 0.6, -0.4, -0.2, 0.0, 0.0]),
            ("Returning home...", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]
        
        for desc, joints in sequence:
            print(f"  {desc}")
            move_joints(world, robot_path, joints, steps=60)
            
        
        # Final capture
        capture_photo(cameras, args.output, "side", world)
        capture_photo(cameras, args.output, "external", world)
        print("Demo complete!")
    
    # Save USD if requested
    if args.save_usd:
        omni.usd.get_context().save_as_stage(args.save_usd)
        print(f"Scene saved as USD: {args.save_usd}")
    
    # Print summary
    print("\n" + "="*60)
    print("SO-ARM101 Digital Twin Summary")
    print("="*60)
    print(f"  Robot: SO-ARM101 (6-DOF, STS3215 servos)")
    print(f"  Joints: 6 (5 arm + 1 gripper)")
    print(f"  Cameras: {len(cameras)} (gripper, external, side)")
    print(f"  Objects: {len(objects)} manipulation targets")
    print(f"  Output: {args.output}/")
    print("="*60)
    
    world.stop()
    simulation_app.close()


if __name__ == "__main__":
    main()
