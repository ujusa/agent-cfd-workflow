"""The only place that invokes docker/OpenFOAM. Exposes narrow, allowlisted
operations -- never a generic command string -- per AGENTS.md section 2.

run_mesh / check_mesh / run_solver execute, persist stdout+stderr+return
code to a log file, and enforce a timeout. They never raise on a normal
solver/mesh failure or timeout -- they return a structured OperationResult
so a later LangGraph gate node can route PASSED/FAILED/BLOCKED (plan section
26) instead of an exception unwinding the workflow. They only raise for
programmer/policy errors: an unknown operation, or a case_root that was
never prepared or has escaped RUNS_DIR.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app import config
from app.paths import require_prepared_case

Operation = Literal["mesh", "check_mesh", "solve", "postprocess"]

# Fixed, non-parametrized set of OpenFOAM function objects used to extract
# QoIs (app/validation/qoi.py). Patch/field names are hardcoded to match the
# benchmark case -- never built from caller input. Verified interactively
# against OpenFOAM 11 (see Milestone 2 notes): all six are valid function
# object names that write postProcessing/<name>/<time>/*.dat.
POSTPROCESS_FUNCTIONS: list[str] = [
    "patchFlowRate(patch=inlet)",
    "patchFlowRate(patch=outlet)",
    "patchAverage(patch=inlet,fields=(p))",
    "patchAverage(patch=outlet,fields=(p))",
    "cellMaxMag(U)",
    "volAverage(U)",
]
_POSTPROCESS_COMMAND = " && ".join(
    f'postProcess -func "{fn}" -latestTime' for fn in POSTPROCESS_FUNCTIONS
)

# operation -> (foam command, log filename, default timeout seconds)
_ALLOWED_OPERATIONS: dict[Operation, tuple[str, str, int]] = {
    "mesh": ("blockMesh", "blockMesh.log", config.MESH_TIMEOUT_SECONDS),
    "check_mesh": ("checkMesh", "checkMesh.log", config.CHECK_MESH_TIMEOUT_SECONDS),
    "solve": ("foamRun", "solver.log", config.SOLVE_TIMEOUT_SECONDS),
    "postprocess": (_POSTPROCESS_COMMAND, "postprocess.log", config.POSTPROCESS_TIMEOUT_SECONDS),
}


@dataclass
class OperationResult:
    operation: str
    command: str
    success: bool
    return_code: int | None
    timed_out: bool
    started_at: str
    ended_at: str
    elapsed_s: float
    log_path: str

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _docker_command(case_dir: Path, foam_command: str) -> list[str]:
    script = f"source /opt/openfoam11/etc/bashrc && {foam_command}"
    return [
        "docker", "run", "--rm",
        "--platform", config.OPENFOAM_PLATFORM,
        # Without this, the container's baked-in user (uid 98765) can't
        # write to the host-mounted case dir on real Linux Docker -- macOS
        # Docker Desktop's bind-mount layer maps this permissively, which
        # is why it was never caught there (found deploying to EC2).
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{case_dir}:{config.OPENFOAM_CONTAINER_WORKDIR}",
        "-w", config.OPENFOAM_CONTAINER_WORKDIR,
        "--entrypoint", "bash",
        config.OPENFOAM_IMAGE,
        "-lc", script,
    ]


def run_openfoam(
    case_root: Path, operation: Operation, timeout: int | None = None
) -> OperationResult:
    if operation not in _ALLOWED_OPERATIONS:
        raise ValueError(f"operation not allowlisted: {operation!r}")
    foam_command, log_name, default_timeout = _ALLOWED_OPERATIONS[operation]

    case_dir = require_prepared_case(case_root)
    logs_dir = case_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / log_name

    cmd = _docker_command(case_dir, foam_command)
    started = time.monotonic()
    started_at = _now()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout or default_timeout
        )
        return_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    elapsed = time.monotonic() - started
    ended_at = _now()

    log_path.write_text((stdout or "") + "\n--- stderr ---\n" + (stderr or ""))

    result = OperationResult(
        operation=operation,
        command=foam_command,
        success=(return_code == 0),
        return_code=return_code,
        timed_out=timed_out,
        started_at=started_at,
        ended_at=ended_at,
        elapsed_s=round(elapsed, 3),
        log_path=str(log_path),
    )
    _append_operation_to_metadata(case_root, result)
    return result


def _append_operation_to_metadata(case_root: Path, result: OperationResult) -> None:
    metadata_path = case_root / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
    metadata.setdefault("operations", []).append(result.to_dict())
    metadata["status"] = (
        "completed" if result.success else ("timed_out" if result.timed_out else "failed")
    )
    metadata["updated_at"] = _now()
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")


def run_mesh(case_root: Path, timeout: int | None = None) -> OperationResult:
    return run_openfoam(case_root, "mesh", timeout)


def check_mesh(case_root: Path, timeout: int | None = None) -> OperationResult:
    return run_openfoam(case_root, "check_mesh", timeout)


def run_solver(case_root: Path, timeout: int | None = None) -> OperationResult:
    return run_openfoam(case_root, "solve", timeout)


def run_postprocess(case_root: Path, timeout: int | None = None) -> OperationResult:
    return run_openfoam(case_root, "postprocess", timeout)


def collect_logs(case_root: Path) -> dict[str, str]:
    """Return {log filename: full text} for every log written so far. Never
    deletes anything -- raw logs are append-only evidence (AGENTS.md)."""
    case_root = Path(case_root).resolve()
    runs_root = config.RUNS_DIR.resolve()
    if runs_root not in case_root.parents:
        raise ValueError(f"refusing to read outside RUNS_DIR: {case_root}")
    logs_dir = case_root / "logs"
    if not logs_dir.is_dir():
        return {}
    return {p.name: p.read_text() for p in sorted(logs_dir.glob("*.log"))}
