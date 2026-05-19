"""
Sim2Real Bridge - Transfers learned trajectories from simulation to real SO-ARM101.

Architecture:
    Isaac Sim → DynamoDB (episodes) → This Bridge → Real Robot (LeRobot)

Usage:
    python bridge.py --task pick_orange_to_plate --execute
"""
import argparse
import json
import time
from episode_logger import EpisodeLogger


def get_trajectory_for_task(task):
    """Retrieve the best trajectory from simulation memory."""
    logger = EpisodeLogger()
    trajectory = logger.get_best_trajectory(task)
    if not trajectory:
        print(f"No successful episodes found for task: {task}")
        return None
    print(f"Found trajectory with {len(trajectory)} waypoints")
    return trajectory


def adapt_for_real_robot(trajectory):
    """Adapt simulation joint angles for real SO-ARM101 servos.
    
    The simulation uses the same joint naming as the real robot,
    but we may need to apply:
    - Safety limits (more conservative than sim)
    - Speed scaling (slower for safety)
    - Gripper range scaling (real gripper has smaller range)
    """
    GRIPPER_SCALE = 0.8  # Real gripper has less range
    SAFETY_MARGIN = 0.9  # 90% of sim angles for safety
    
    adapted = []
    for wp in trajectory:
        new_joints = {}
        for joint, angle in wp['joints'].items():
            if joint == 'gripper':
                new_joints[joint] = angle * GRIPPER_SCALE
            else:
                new_joints[joint] = angle * SAFETY_MARGIN
        adapted.append({
            'step': wp['step'],
            'name': wp['name'],
            'joints': new_joints
        })
    return adapted


def execute_on_real_robot(trajectory):
    """Send trajectory to real SO-ARM101 via LeRobot.
    
    This is a placeholder - implement actual servo communication
    using the LeRobot SDK or direct serial/USB connection.
    """
    try:
        # from lerobot.common.robot_devices.robots.manipulator import ManipulatorRobot
        # robot = ManipulatorRobot(config=...)
        # robot.connect()
        
        for wp in trajectory:
            print(f"  [{wp['step']:2d}] {wp['name']}: {wp['joints']}")
            # robot.send_action(wp['joints'])
            time.sleep(0.5)  # Placeholder timing
        
        print("Execution complete!")
        return True
    except Exception as e:
        print(f"Execution failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Sim2Real Bridge')
    parser.add_argument('--task', required=True, help='Task name (e.g. pick_orange_to_plate)')
    parser.add_argument('--execute', action='store_true', help='Actually execute on real robot')
    parser.add_argument('--dry-run', action='store_true', help='Print trajectory only')
    args = parser.parse_args()

    print(f"=== Sim2Real Bridge ===")
    print(f"Task: {args.task}")
    
    # 1. Get trajectory from simulation memory
    trajectory = get_trajectory_for_task(args.task)
    if not trajectory:
        return

    # 2. Adapt for real robot
    adapted = adapt_for_real_robot(trajectory)
    
    # 3. Execute or print
    if args.dry_run or not args.execute:
        print("\nAdapted trajectory (dry run):")
        for wp in adapted:
            print(f"  [{wp['step']:2d}] {wp['name']}: {wp['joints']}")
    
    if args.execute:
        print("\nExecuting on real robot...")
        success = execute_on_real_robot(adapted)
        
        # 4. Log real-world result back to DynamoDB
        logger = EpisodeLogger()
        eid = logger.start_episode(
            task=f"real_{args.task}",
            robot_config={'source': 'sim2real', 'safety_margin': 0.9}
        )
        for wp in adapted:
            logger.add_waypoint(wp['step'], wp['name'], wp['joints'])
        logger.end_episode(success=success, notes="Transferred from simulation")
        print(f"Real execution logged: {eid}")


if __name__ == '__main__':
    main()
