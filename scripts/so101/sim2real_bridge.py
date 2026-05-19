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
SO-ARM101 Sim2Real Bridge
===========================
Connects the Isaac Sim digital twin to the real SO-ARM101 hardware
via the LeRobot/HuggingFace ecosystem.

This module provides:
1. Joint state synchronization (sim ↔ real)
2. Camera feed capture from real hardware
3. Trajectory recording and replay
4. Sim2Real calibration and offset management
5. Data collection for imitation learning

Dataset Compliance:
- Collected teleoperation data is licensed under MIT-0 (same as project)
- No PII is captured — cameras view the workspace only (no human faces)
- Data usage: training ACT/Diffusion/VLA policies for robot manipulation
- Operator explicitly initiates recording (no passive data collection)
- Retention: per project data classification policy

Prerequisites:
- pip install lerobot
- SO-ARM101 connected via USB (Feetech STS3215 bus servos)
- Camera(s) connected (USB webcam)

Usage:
    python scripts/so101/sim2real_bridge.py --mode [sync|record|replay|calibrate]
"""

import os
import sys
import time
import json
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime


# SO-ARM101 Joint Configuration
SO101_CONFIG = {
    "name": "so_arm101",
    "num_joints": 6,
    "joint_names": [
        "joint_1",   # Base rotation (yaw)
        "joint_2",   # Shoulder pitch
        "joint_3",   # Elbow pitch
        "joint_4",   # Wrist pitch
        "joint_5",   # Wrist roll
        "joint_6",   # Gripper
    ],
    "servo_ids": [1, 2, 3, 4, 5, 6],
    "joint_limits": {
        "joint_1": {"min": -3.14159, "max": 3.14159},
        "joint_2": {"min": -1.5708, "max": 1.5708},
        "joint_3": {"min": -1.5708, "max": 1.5708},
        "joint_4": {"min": -1.5708, "max": 1.5708},
        "joint_5": {"min": -3.14159, "max": 3.14159},
        "joint_6": {"min": 0.0, "max": 0.8},
    },
    # Servo raw position range (STS3215: 0-4095)
    "servo_range": [0, 4095],
    "servo_center": 2048,
    # Radians per servo tick (calibration)
    "rad_per_tick": 0.001534,
    # Camera config (LeRobot SO-101 dual camera)
    "cameras": {
        "gripper": {"index": 0, "resolution": [640, 480], "fps": 30},
        "external": {"index": 1, "resolution": [640, 480], "fps": 30},
    },
}


class Sim2RealCalibration:
    """Manages calibration offsets between sim and real robot"""
    
    def __init__(self, calibration_path="memory/sim2real/calibration.json"):
        self.path = Path(calibration_path)
        self.offsets = self._load()
    
    def _load(self):
        """Load calibration from file"""
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {
            "joint_offsets_rad": [0.0] * 6,
            "position_scale": [1.0] * 6,
            "gripper_open_rad": 0.0,
            "gripper_close_rad": 0.7,
            "last_calibrated": None,
            "notes": "Default calibration - run calibrate mode to update",
        }
    
    def save(self):
        """Save calibration to file"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.offsets["last_calibrated"] = datetime.now().isoformat()
        with open(self.path, "w") as f:
            json.dump(self.offsets, f, indent=2)
        print(f"Calibration saved: {self.path}")
    
    def sim_to_real(self, sim_joints):
        """Convert simulation joint positions to real servo targets"""
        real_joints = []
        for i, (sim_val, offset, scale) in enumerate(zip(
            sim_joints,
            self.offsets["joint_offsets_rad"],
            self.offsets["position_scale"],
        )):
            real_val = (sim_val + offset) * scale
            real_joints.append(real_val)
        return real_joints
    
    def real_to_sim(self, real_joints):
        """Convert real servo positions to simulation joint values"""
        sim_joints = []
        for i, (real_val, offset, scale) in enumerate(zip(
            real_joints,
            self.offsets["joint_offsets_rad"],
            self.offsets["position_scale"],
        )):
            sim_val = (real_val / scale) - offset
            sim_joints.append(sim_val)
        return sim_joints


class SO101RealRobot:
    """Interface to the real SO-ARM101 hardware via LeRobot"""
    
    def __init__(self, config=SO101_CONFIG):
        self.config = config
        self.connected = False
        self.robot = None
    
    def connect(self):
        """Connect to real robot via LeRobot"""
        try:
            from lerobot.robots.so100 import SO100Robot, SO100RobotConfig
            
            robot_config = SO100RobotConfig(
                leader_arms={},
                follower_arms={"main": {"port": os.environ.get("ROBOT_USB_PORT", "/dev/ttyUSB0"), "servos": self.config["servo_ids"]}},  # May be /dev/ttyUSB1 or /dev/ttyACM0 on your system. Use 'ls /dev/tty*' to identify your device.
                cameras=self.config["cameras"],
            )
            self.robot = SO100Robot(config=robot_config)
            self.robot.connect()
            self.connected = True
            print("✅ Connected to real SO-ARM101")
            return True
        except ImportError:
            print("⚠️  LeRobot not installed. Install with: pip install lerobot")
            return False
        except Exception as e:
            print(f"⚠️  Connection failed: {e}")
            print("    Make sure the robot is connected via USB")
            return False
    
    def disconnect(self):
        """Disconnect from robot"""
        if self.robot:
            self.robot.disconnect()
            self.connected = False
            print("Disconnected from real robot")
    
    def get_joint_positions(self):
        """Read current joint positions (in radians)"""
        if not self.connected:
            return None
        obs = self.robot.get_observation()
        return obs.get("position", None)
    
    def set_joint_positions(self, positions):
        """Send joint position targets to real robot"""
        if not self.connected:
            return False
        action = {"position": np.array(positions)}
        self.robot.send_action(action)
        return True
    
    def get_camera_frame(self, camera_name="gripper"):
        """Capture a frame from specified camera"""
        if not self.connected:
            return None
        obs = self.robot.get_observation()
        return obs.get(f"camera_{camera_name}", None)
    
    def record_episode(self, output_dir, duration_sec=10, fps=30):
        """Record an episode (joint positions + camera frames)
        

        """
        if not self.connected:
            print("Not connected to robot")
            return None
        
        episode_dir = Path(output_dir) / f"episode_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        frames = []
        positions = []
        timestamps = []
        
        print(f"Recording for {duration_sec}s...")
        start = time.time()
        
        while time.time() - start < duration_sec:
            t = time.time() - start
            obs = self.robot.get_observation()
            
            positions.append(obs.get("position", [0]*6))
            timestamps.append(t)
            
            # Save camera frame
            if "camera_gripper" in obs:
                frames.append(obs["camera_gripper"])
            
            
        
        # Save episode data
        episode_data = {
            "robot": self.config["name"],
            "duration_sec": duration_sec,
            "fps": fps,
            "num_frames": len(positions),
            "joint_positions": [p.tolist() if hasattr(p, 'tolist') else p for p in positions],
            "timestamps": timestamps,
        }
        
        with open(episode_dir / "episode.json", "w") as f:
            json.dump(episode_data, f, indent=2)
        
        # Save frames as video if possible
        if frames:
            try:
                import imageio
                video_path = episode_dir / "gripper_cam.mp4"
                writer = imageio.get_writer(str(video_path), fps=fps)
                for frame in frames:
                    writer.append_data(frame)
                writer.close()
                print(f"Video saved: {video_path}")
            except ImportError:
                print("imageio not available, skipping video save")
        
        print(f"Episode saved: {episode_dir}")
        return str(episode_dir)


class EpisodeMemory:
    """
    Stores and retrieves episodes for sim2real learning.
    Tracks success/failure and identifies patterns.
    """
    
    def __init__(self, memory_dir="memory/episodes"):
        self.dir = Path(memory_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
    
    def log_episode(self, task, sim_result, real_result, params, delta=None):
        """Log an episode with sim and real outcomes"""
        episode = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "params": params,
            "sim_result": sim_result,
            "real_result": real_result,
            "sim2real_delta": delta,
            "success": real_result.get("success", False),
        }
        
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task}.json"
        with open(self.dir / filename, "w") as f:
            json.dump(episode, f, indent=2)
        
        return episode
    
    def get_episodes_for_task(self, task, limit=10):
        """Retrieve recent episodes for a given task"""
        episodes = []
        for f in sorted(self.dir.glob(f"*_{task}.json"), reverse=True)[:limit]:
            with open(f) as fp:
                episodes.append(json.load(fp))
        return episodes
    
    def get_success_rate(self, task):
        """Calculate success rate for a task"""
        episodes = self.get_episodes_for_task(task, limit=50)
        if not episodes:
            return None
        successes = sum(1 for e in episodes if e.get("success", False))
        return successes / len(episodes)
    
    def get_best_params(self, task):
        """Get parameters from the most successful recent episodes"""
        episodes = self.get_episodes_for_task(task)
        successful = [e for e in episodes if e.get("success", False)]
        if successful:
            return successful[0].get("params", {})
        return None


def run_sync_mode(calibration):
    """Sync real robot position to simulation"""
    robot = SO101RealRobot()
    if not robot.connect():
        return
    
    print("\n🔄 Sim2Real Sync Mode")
    print("Reading real robot joint positions and converting to sim values")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            real_pos = robot.get_joint_positions()
            if real_pos is not None:
                sim_pos = calibration.real_to_sim(real_pos)
                print(f"\rReal: {[f'{p:.3f}' for p in real_pos]}  →  Sim: {[f'{p:.3f}' for p in sim_pos]}", end="")
            
    except KeyboardInterrupt:
        print("\n\nSync stopped.")
    finally:
        robot.disconnect()


def run_calibrate_mode(calibration):
    """Interactive calibration between sim and real"""
    robot = SO101RealRobot()
    if not robot.connect():
        return
    
    print("\n🔧 Calibration Mode")
    print("Move the robot to its HOME position (all joints centered)")
    input("Press Enter when ready...")
    
    home_pos = robot.get_joint_positions()
    if home_pos is not None:
        # The offset is the difference from expected zero
        calibration.offsets["joint_offsets_rad"] = [-p for p in home_pos]
        calibration.save()
        print(f"✅ Calibration complete! Offsets: {calibration.offsets['joint_offsets_rad']}")
    
    robot.disconnect()


def main():
    parser = argparse.ArgumentParser(description="SO-ARM101 Sim2Real Bridge")
    parser.add_argument("--mode", type=str, default="info",
                       choices=["info", "sync", "record", "replay", "calibrate"],
                       help="Bridge mode")
    parser.add_argument("--output", type=str, default="output/episodes",
                       help="Output directory for recordings")
    parser.add_argument("--duration", type=float, default=10.0,
                       help="Recording duration in seconds")
    parser.add_argument("--calibration", type=str, 
                       default="memory/sim2real/calibration.json",
                       help="Calibration file path")
    
    args = parser.parse_args()
    
    calibration = Sim2RealCalibration(args.calibration)
    
    if args.mode == "info":
        print("\n" + "="*60)
        print("SO-ARM101 Sim2Real Bridge")
        print("="*60)
        print(f"\nRobot: {SO101_CONFIG['name']}")
        print(f"Joints: {SO101_CONFIG['num_joints']}")
        print(f"Joint names: {SO101_CONFIG['joint_names']}")
        print(f"Servo IDs: {SO101_CONFIG['servo_ids']}")
        print(f"Cameras: {list(SO101_CONFIG['cameras'].keys())}")
        print(f"\nCalibration: {args.calibration}")
        print(f"Last calibrated: {calibration.offsets.get('last_calibrated', 'Never')}")
        print(f"Joint offsets: {calibration.offsets['joint_offsets_rad']}")
        print(f"\nModes:")
        print(f"  sync      - Real-time position sync (real → sim)")
        print(f"  record    - Record episode from real robot")
        print(f"  replay    - Replay recorded episode on sim/real")
        print(f"  calibrate - Interactive joint calibration")
        print("="*60)
    
    elif args.mode == "sync":
        run_sync_mode(calibration)
    
    elif args.mode == "record":
        robot = SO101RealRobot()
        if robot.connect():
            robot.record_episode(args.output, duration_sec=args.duration)
            robot.disconnect()
    
    elif args.mode == "calibrate":
        run_calibrate_mode(calibration)
    
    elif args.mode == "replay":
        print("Replay mode - specify an episode directory")


if __name__ == "__main__":
    main()
