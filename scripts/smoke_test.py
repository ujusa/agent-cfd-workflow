#!/usr/bin/env python3
"""Milestone 0 environment smoke test.

Verifies, with real commands (not assumptions):
  1. SQLite checkpoint database can be created and is writable.
  2. The pinned OpenFOAM Docker image is present and reachable.
  3. blockMesh runs successfully on the benchmark case template.
  4. checkMesh runs successfully on the resulting mesh.
  5. The solver (foamRun) can be launched and runs to completion.

This script talks to Docker directly via subprocess. It is a developer
verification script, not an LLM-facing tool — see AGENTS.md section 2 for
why the agent itself must never get a generic shell-execution tool.

No LangGraph, no LLM calls. Run with: python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

SMOKE_CASE_DIR = config.RUNS_DIR / "_smoke_test" / "case"
SMOKE_ENDTIME = 20  # patched into the scratch copy only; keeps this fast


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class Report:
    steps: list[StepResult] = field(default_factory=list)

    def run(self, name: str, fn):
        start = time.monotonic()
        try:
            detail = fn() or ""
            ok = True
        except Exception as exc:  # noqa: BLE001 - smoke test wants to report, not raise
            detail = str(exc)
            ok = False
        elapsed = time.monotonic() - start
        result = StepResult(name=name, ok=ok, detail=detail, elapsed_s=elapsed)
        self.steps.append(result)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name} ({elapsed:.1f}s){': ' + detail if detail and not ok else ''}")
        return result

    @property
    def all_ok(self) -> bool:
        return all(s.ok for s in self.steps)


def check_sqlite_checkpoint_db() -> str:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS smoke_test (id INTEGER PRIMARY KEY, checked_at TEXT)"
        )
        conn.execute("INSERT INTO smoke_test (checked_at) VALUES (datetime('now'))")
        conn.commit()
        row = conn.execute(
            "SELECT COUNT(*) FROM smoke_test"
        ).fetchone()
        assert row[0] >= 1
    finally:
        conn.close()
    return f"db={config.CHECKPOINT_DB_PATH}"


def check_docker_image_present() -> str:
    proc = subprocess.run(
        ["docker", "image", "inspect", config.OPENFOAM_IMAGE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"image not found locally: {config.OPENFOAM_IMAGE} "
            f"(run: docker pull --platform {config.OPENFOAM_PLATFORM} {config.OPENFOAM_IMAGE})"
        )
    return config.OPENFOAM_IMAGE


def check_benchmark_template_exists() -> str:
    if not config.BENCHMARK_CASE_TEMPLATE.is_dir():
        raise RuntimeError(f"missing template: {config.BENCHMARK_CASE_TEMPLATE}")
    required = ["0/U", "0/p", "constant/physicalProperties", "system/blockMeshDict", "system/controlDict"]
    missing = [p for p in required if not (config.BENCHMARK_CASE_TEMPLATE / p).is_file()]
    if missing:
        raise RuntimeError(f"template missing required files: {missing}")
    return str(config.BENCHMARK_CASE_TEMPLATE)


def _prepare_scratch_case() -> Path:
    if SMOKE_CASE_DIR.exists():
        shutil.rmtree(SMOKE_CASE_DIR)
    SMOKE_CASE_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(config.BENCHMARK_CASE_TEMPLATE, SMOKE_CASE_DIR)

    control_dict = SMOKE_CASE_DIR / "system" / "controlDict"
    text = control_dict.read_text()
    text = text.replace("endTime         2000;", f"endTime         {SMOKE_ENDTIME};")
    text = text.replace("writeInterval   100;", f"writeInterval   {SMOKE_ENDTIME};")
    control_dict.write_text(text)
    return SMOKE_CASE_DIR


def _run_in_container(case_dir: Path, foam_command: str, log_name: str) -> str:
    logs_dir = case_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    script = f"source /opt/openfoam11/etc/bashrc && {foam_command}"
    cmd = [
        "docker", "run", "--rm",
        "--platform", config.OPENFOAM_PLATFORM,
        # See app/tools/openfoam_tools.py's _docker_command for why this is
        # required on real Linux Docker (not just macOS Docker Desktop).
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{case_dir}:{config.OPENFOAM_CONTAINER_WORKDIR}",
        "-w", config.OPENFOAM_CONTAINER_WORKDIR,
        "--entrypoint", "bash",
        config.OPENFOAM_IMAGE,
        "-lc", script,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.OPENFOAM_TIMEOUT_SECONDS
    )
    log_path = logs_dir / log_name
    log_path.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
        raise RuntimeError(f"{foam_command!r} exited {proc.returncode}; see {log_path}\n{tail}")
    return f"log={log_path}"


def check_block_mesh() -> str:
    case_dir = _prepare_scratch_case()
    detail = _run_in_container(case_dir, "blockMesh", "blockMesh.log")
    if not (case_dir / "constant" / "polyMesh" / "owner").is_file():
        raise RuntimeError("blockMesh ran but constant/polyMesh/owner was not created")
    return detail


def check_check_mesh() -> str:
    return _run_in_container(SMOKE_CASE_DIR, "checkMesh", "checkMesh.log")


def check_solver_runs() -> str:
    detail = _run_in_container(SMOKE_CASE_DIR, "foamRun", "foamRun.log")
    final_time_dir = SMOKE_CASE_DIR / str(SMOKE_ENDTIME)
    if not final_time_dir.is_dir():
        raise RuntimeError(
            f"foamRun exited 0 but expected time directory {final_time_dir} was not written"
        )
    return detail


def main() -> int:
    print(f"Repo root: {config.REPO_ROOT}")
    print(f"OpenFOAM image: {config.OPENFOAM_IMAGE} ({config.OPENFOAM_PLATFORM})")
    print()

    report = Report()
    report.run("sqlite checkpoint db writable", check_sqlite_checkpoint_db)
    report.run("docker image present", check_docker_image_present)
    report.run("benchmark template present", check_benchmark_template_exists)
    report.run("blockMesh runs on benchmark case", check_block_mesh)
    report.run("checkMesh runs on generated mesh", check_check_mesh)
    report.run("solver (foamRun) launches and completes", check_solver_runs)

    print()
    if report.all_ok:
        print("ALL CHECKS PASSED")
        return 0
    else:
        print("SMOKE TEST FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
