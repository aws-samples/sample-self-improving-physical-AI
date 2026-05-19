"""
Episode Logger - Records simulation episodes to DynamoDB.
Used by Isaac Sim scripts to persist trajectories for Sim2Real learning.

Usage:
    from episode_logger import EpisodeLogger
    logger = EpisodeLogger()
    logger.start_episode(task="pick_orange_to_plate", robot_config={...})
    logger.add_waypoint(step=1, name="rest", joints={...})
    logger.end_episode(success=True, metrics={...})
"""
import boto3
import json
import uuid
from datetime import datetime
from decimal import Decimal


class EpisodeLogger:
    def __init__(self, table_name="sim-episodes", region="us-west-2"):
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.table = self.dynamodb.Table(table_name)
        self.current_episode = None

    def start_episode(self, task, robot_config, scene_config=None, objects=None):
        """Start recording a new episode."""
        self.current_episode = {
            'episode_id': str(uuid.uuid4()),
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'task': task,
            'robot': 'SO-ARM101',
            'scene': 'leisaac_kitchen',
            'robot_config': robot_config,
            'scene_config': scene_config or {},
            'objects': objects or {},
            'trajectory': [],
            'success': False,
            'source': 'isaac_sim_6.0'
        }
        return self.current_episode['episode_id']

    def add_waypoint(self, step, name, joints, jaw_pos=None, orange_pos=None):
        """Record a trajectory waypoint."""
        if not self.current_episode:
            raise RuntimeError("No active episode. Call start_episode() first.")
        
        wp = {'step': step, 'name': name, 'joints': joints}
        if jaw_pos:
            wp['jaw_world_pos'] = jaw_pos
        if orange_pos:
            wp['orange_world_pos'] = orange_pos
        self.current_episode['trajectory'].append(wp)

    def end_episode(self, success, metrics=None, notes=None):
        """Finish and persist the episode to DynamoDB."""
        if not self.current_episode:
            raise RuntimeError("No active episode.")
        
        self.current_episode['success'] = success
        self.current_episode['metrics'] = metrics or {}
        if notes:
            self.current_episode['notes'] = notes

        # Convert floats to Decimal for DynamoDB
        item = json.loads(json.dumps(self.current_episode), parse_float=Decimal)
        self.table.put_item(Item=item)
        
        episode_id = self.current_episode['episode_id']
        self.current_episode = None
        return episode_id

    def query_episodes(self, task=None, success_only=True, limit=10):
        """Query past episodes for learning."""
        scan_kwargs = {'Limit': limit}
        
        filter_parts = []
        expr_values = {}
        
        if task:
            filter_parts.append('task = :task')
            expr_values[':task'] = task
        if success_only:
            filter_parts.append('success = :success')
            expr_values[':success'] = True
        
        if filter_parts:
            scan_kwargs['FilterExpression'] = ' AND '.join(filter_parts)
            scan_kwargs['ExpressionAttributeValues'] = expr_values
        
        response = self.table.scan(**scan_kwargs)
        return response.get('Items', [])

    def get_best_trajectory(self, task):
        """Get the most recent successful trajectory for a task."""
        episodes = self.query_episodes(task=task, success_only=True, limit=5)
        if not episodes:
            return None
        # Sort by created_at descending
        episodes.sort(key=lambda x: x['created_at'], reverse=True)
        return episodes[0]['trajectory']
