"""
Telekinesis Perception-to-Grasp Pipeline

Uses Telekinesis Skills for:
1. Camera capture (Medulla)
2. Object detection (Retina) 
3. Segmentation (Cornea)
4. Point cloud processing (Vitreous)
5. Robot control (Synapse)

Requirements:
    pip install telekinesis-ai
    export TELEKINESIS_API_KEY="your_key"
"""

from telekinesis import cornea, retina, vitreous
from telekinesis.medulla import cameras


def detect_and_grasp(robot, target_object="orange"):
    """
    Full perception-to-grasp pipeline using Telekinesis Skills.
    
    Args:
        robot: Connected Telekinesis robot instance
        target_object: Text description of object to grasp
    """
    # Step 1: Capture RGB-D frame
    cam = cameras.realsense.RealSense(name="wrist_cam")
    cam.connect()
    color_image, depth_image = cam.capture_rgbd()
    cam.disconnect()

    # Step 2: Detect target object (open-vocabulary)
    detections = retina.detect_objects_using_grounding_dino(
        image=color_image,
        text_prompt=target_object
    )
    
    if not detections:
        print(f"No '{target_object}' detected in scene")
        return False

    # Step 3: Segment the detected object
    best_detection = detections[0]
    bbox = best_detection.bbox  # [x1, y1, x2, y2]
    
    segmentation = cornea.segment_image_using_sam(
        image=color_image,
        bboxes=[bbox]
    )
    mask = segmentation.to_list()[0]

    # Step 4: Extract 3D point cloud of object
    scene_pc = vitreous.create_point_cloud_from_rgbd(
        color=color_image,
        depth=depth_image,
        intrinsics=cam.get_intrinsics()
    )
    
    object_pc = vitreous.filter_point_cloud_using_mask(
        point_cloud=scene_pc,
        mask=mask
    )
    
    # Get grasp target (centroid of object)
    centroid = vitreous.get_centroid(object_pc)
    print(f"Object centroid at: {centroid}")

    # Step 5: Plan approach
    # Pre-grasp: above object
    pre_grasp_pose = [centroid[0], centroid[1], centroid[2] + 0.10, 0, 3.14, 0]
    
    # Grasp pose: at object
    grasp_pose = [centroid[0], centroid[1], centroid[2], 0, 3.14, 0]

    # Step 6: Execute grasp sequence
    robot.set_gripper_position(position=100)  # open gripper
    
    robot.set_cartesian_pose(
        pose=pre_grasp_pose,
        speed=0.25, acceleration=1.2
    )
    
    robot.set_cartesian_pose(
        pose=grasp_pose,
        speed=0.1, acceleration=0.5  # slow approach
    )
    
    robot.set_gripper_position(position=0)  # close gripper
    
    # Lift
    lift_pose = [centroid[0], centroid[1], centroid[2] + 0.15, 0, 3.14, 0]
    robot.set_cartesian_pose(pose=lift_pose, speed=0.1, acceleration=0.5)
    
    print(f"Successfully grasped '{target_object}'")
    return True


def main():
    """Example: UR10e picks an orange from counter."""
    from telekinesis.synapse.robots.manipulators.universal_robots import UniversalRobotsUR10E
    
    robot = UniversalRobotsUR10E()
    robot.connect(ip="192.168.1.2")
    
    try:
        # Move to home position
        robot.set_joint_positions(
            joint_positions=[0, -90, 90, -90, -90, 0],
            speed=60, acceleration=80
        )
        
        # Run perception-to-grasp
        success = detect_and_grasp(robot, target_object="orange fruit")
        
        if success:
            # Place at target location
            place_pose = [0.5, 0.3, 0.2, 0, 3.14, 0]
            robot.set_cartesian_pose(pose=place_pose, speed=0.2)
            robot.set_gripper_position(position=100)  # release
            print("Pick-and-place complete!")
    
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
