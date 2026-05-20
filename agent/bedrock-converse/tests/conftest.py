"""Pytest configuration for bedrock-converse tests.

Adds the parent directory (agent/bedrock-converse/) to sys.path so that
test files can import modules like `orchestrator`, `models`, etc. directly.
Also adds device-side paths for tests that validate device code.
"""

import sys
from pathlib import Path

# Add the bedrock-converse directory to the path
_bedrock_converse = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_bedrock_converse))

# Add device-side paths for tests that import device modules (e.g., ota_agent)
_repo_root = _bedrock_converse.parent.parent
sys.path.insert(0, str(_repo_root / "example" / "zumi" / "device"))
sys.path.insert(0, str(_repo_root / "example" / "xgo2" / "components" / "xgo2-vision-navigation"))
