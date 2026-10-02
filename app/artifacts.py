
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import config
from app.paths import validate_id


def write_run_artifact(run_id: str, filename: str, data: Any) -> Path:
    validate_id("run_id", run_id)
    path = config.RUNS_DIR / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return path


def read_run_artifact(run_id: str, filename: str) -> Any:
    validate_id("run_id", run_id)
    path = config.RUNS_DIR / run_id / filename
    return json.loads(path.read_text())
