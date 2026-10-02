"""Run-level artifact contracts (plan section 25): one predictable JSON file
per stage, written under runs/<run_id>/ (as opposed to the per-case files
under runs/<run_id>/cases/<case_id>/ written by app.tools.case_tools and
app.validation.qoi). The next stage is expected to validate the previous
artifact before reading it -- enforced today by Pydantic models at the
point each artifact is produced.
"""
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
