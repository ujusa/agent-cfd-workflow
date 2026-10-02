"""Filesystem-boundary enforcement shared by every CFD tool.

Every function here re-validates from scratch -- callers must never assume a
path was already checked upstream. This is the defense described in
AGENTS.md section 3 and plan section 8: case IDs must map to approved run
directories, and no tool may read or write outside runs/<run_id>/.
"""
from __future__ import annotations

import re
from pathlib import Path

from app import config

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_id(label: str, value: str) -> str:
    """Reject anything that isn't a plain, short identifier -- in particular
    no '/', no '..', no absolute paths, no whitespace."""
    if not isinstance(value, str) or not SAFE_ID_RE.match(value):
        raise ValueError(
            f"invalid {label}: {value!r}; must match {SAFE_ID_RE.pattern!r}"
        )
    return value


def resolve_case_root(run_id: str, case_id: str) -> Path:
    """Compute runs/<run_id>/cases/<case_id>, after validating both IDs and
    confirming the resolved path is actually inside RUNS_DIR."""
    validate_id("run_id", run_id)
    validate_id("case_id", case_id)
    runs_root = config.RUNS_DIR.resolve()
    case_root = (config.RUNS_DIR / run_id / "cases" / case_id).resolve()
    if case_root != runs_root and runs_root not in case_root.parents:
        raise ValueError(f"resolved path escapes RUNS_DIR: {case_root}")
    return case_root


def require_prepared_case(case_root: Path) -> Path:
    """Re-validate an already-resolved case_root before running anything in
    it, and return the OpenFOAM case directory (case_root/case).

    This is the check that runs immediately before every docker invocation,
    so even a caller who skipped resolve_case_root cannot point execution
    outside RUNS_DIR or at a case that was never prepared.
    """
    case_root = Path(case_root).resolve()
    runs_root = config.RUNS_DIR.resolve()
    if runs_root not in case_root.parents:
        raise ValueError(f"refusing to operate outside RUNS_DIR: {case_root}")
    case_dir = case_root / "case"
    if not (case_dir / "system" / "controlDict").is_file():
        raise FileNotFoundError(
            f"case not prepared (missing system/controlDict): {case_dir}"
        )
    return case_dir
