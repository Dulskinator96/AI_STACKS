"""L2 World Model CLI — python -m omega.world_model"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from omega.world_model import build_world_model  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(build_world_model(), indent=2, default=str))
