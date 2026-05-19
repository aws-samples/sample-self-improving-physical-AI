# Telekinesis Integration

Uses [Telekinesis Agentic Skill Library](https://docs.telekinesis.ai/) for real robot perception and control.

## Setup

```bash
pip install telekinesis-ai
export TELEKINESIS_API_KEY="your_key"
```

## Scripts

### `perception_grasp.py`
Full perception-to-grasp pipeline:
1. Capture RGB-D with RealSense (Medulla)
2. Detect target object with Grounding DINO (Retina)
3. Segment with SAM (Cornea)
4. Extract 3D position from point cloud (Vitreous)
5. Plan and execute grasp (Synapse)

```bash
python scripts/telekinesis/perception_grasp.py
```

## Architecture

```
Camera (Medulla) → Detection (Retina) → Segmentation (Cornea)
                                              ↓
Point Cloud (Vitreous) → 3D Position → Robot Motion (Synapse)
```

## Sim2Real with Telekinesis

The Telekinesis Synapse module provides hardware-agnostic robot control.
Combined with our Isaac Sim pipeline:

1. **Sim (Isaac Sim)**: Train/validate pick strategies, record episodes
2. **Transfer (bridge.py)**: Map joint trajectories to real robot
3. **Real (Telekinesis)**: Execute with perception-guided correction

Telekinesis adds real-time visual servoing that pure replay cannot provide.
