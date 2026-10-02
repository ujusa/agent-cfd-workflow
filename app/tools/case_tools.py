
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app import config
from app.paths import require_prepared_case, resolve_case_root
from app.schemas import DiagnosticFix


class CaseParameters(BaseModel):

    model_config = ConfigDict(extra="forbid")

    inlet_velocity: float = 10.0
    mesh_level: Literal["coarse", "medium", "fine"] = "medium"

    @field_validator("inlet_velocity")
    @classmethod
    def _bounded_inlet_velocity(cls, v: float) -> float:
        bounds = config.PARAMETER_BOUNDS["inlet_velocity"]
        if not (bounds["min"] <= v <= bounds["max"]):
            raise ValueError(
                f"inlet_velocity {v} outside allowed range "
                f"[{bounds['min']}, {bounds['max']}]"
            )
        return v


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def _apply_inlet_velocity(case_dir: Path, velocity: float) -> None:
    u_file = case_dir / "0" / "U"
    text = u_file.read_text()
    pattern = re.compile(r"(inlet\s*\{[^}]*?value\s+uniform \()[-\d.eE]+( 0 0\);)")
    new_text, n = pattern.subn(
        lambda m: f"{m.group(1)}{velocity:.6g}{m.group(2)}", text
    )
    if n != 1:
        raise RuntimeError(
            f"expected exactly 1 inlet velocity field in {u_file}, rewrote {n}"
        )
    u_file.write_text(new_text)


def _apply_mesh_level(case_dir: Path, mesh_level: str) -> None:
    factor = config.MESH_LEVEL_FACTORS[mesh_level]
    bmd_file = case_dir / "system" / "blockMeshDict"
    text = bmd_file.read_text()
    pattern = re.compile(r"(hex \([^)]*\)\s*\n\s*)\((\d+) (\d+) (\d+)\)")

    def repl(m: re.Match) -> str:
        prefix, x, y, z = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return f"{prefix}({max(1, round(x * factor))} {max(1, round(y * factor))} {z})"

    new_text, n = pattern.subn(repl, text)
    if n != 5:
        raise RuntimeError(
            f"expected exactly 5 hex blocks in {bmd_file}, rewrote {n}"
        )
    bmd_file.write_text(new_text)


def prepare_case(
    run_id: str, case_id: str, parameters: dict[str, Any] | CaseParameters | None = None
) -> Path:
   
    params = (
        parameters
        if isinstance(parameters, CaseParameters)
        else CaseParameters.model_validate(parameters or {})
    )
    case_root = resolve_case_root(run_id, case_id)
    if case_root.exists():
        raise FileExistsError(f"case already prepared: {case_root}")
    if not config.BENCHMARK_CASE_TEMPLATE.is_dir():
        raise RuntimeError(f"benchmark template missing: {config.BENCHMARK_CASE_TEMPLATE}")

    case_dir = case_root / "case"
    case_root.mkdir(parents=True)
    shutil.copytree(config.BENCHMARK_CASE_TEMPLATE, case_dir)
    _apply_inlet_velocity(case_dir, params.inlet_velocity)
    _apply_mesh_level(case_dir, params.mesh_level)

    for sub in ("input", "logs", "results", "plots"):
        (case_root / sub).mkdir(exist_ok=True)

    _write_json(case_root / "input" / "parameters.json", params.model_dump())
    _write_json(
        case_root / "metadata.json",
        {
            "case_id": case_id,
            "run_id": run_id,
            "parameters": params.model_dump(),
            "status": "prepared",
            "created_at": _utcnow_iso(),
            "operations": [],
        },
    )
    return case_root


def _apply_relaxation_factor(case_dir: Path, factor: float) -> None:
    f = case_dir / "system" / "fvSolution"
    text = f.read_text()
    value = f"{factor:.3g}"

    text, n_u = re.subn(r"(\bU\s+)[\d.]+(;)", rf"\g<1>{value}\2", text)
    text, n_star = re.subn(r'("\.\*"\s+)[\d.]+(;)', rf"\g<1>{value}\2", text)
    if n_u != 1 or n_star != 1:
        raise RuntimeError(
            f"expected to rewrite exactly 1 'U' and 1 '\".*\"' relaxation factor in {f}, "
            f"rewrote {n_u} and {n_star}"
        )
    f.write_text(text)


def _apply_non_orthogonal_correctors(case_dir: Path, count: int) -> None:
    f = case_dir / "system" / "fvSolution"
    text = f.read_text()
    new_text, n = re.subn(
        r"(nNonOrthogonalCorrectors\s+)\d+(;)", rf"\g<1>{count}\2", text
    )
    if n != 1:
        raise RuntimeError(f"expected to rewrite exactly 1 nNonOrthogonalCorrectors in {f}, rewrote {n}")
    f.write_text(new_text)


def _apply_end_time(case_dir: Path, end_time: int) -> None:
    f = case_dir / "system" / "controlDict"
    text = f.read_text()
    new_text, n = re.subn(r"(endTime\s+)\d+(;)", rf"\g<1>{end_time}\2", text)
    if n != 1:
        raise RuntimeError(f"expected to rewrite exactly 1 endTime in {f}, rewrote {n}")
    f.write_text(new_text)


_FIX_APPLIERS = {
    "relaxation": _apply_relaxation_factor,
    "numerical_solver_setting": lambda case_dir, value: _apply_non_orthogonal_correctors(
        case_dir, int(round(value))
    ),
    "time_control": lambda case_dir, value: _apply_end_time(case_dir, int(round(value))),
}


def apply_diagnostic_fix(case_root: Path, fix: DiagnosticFix) -> None:
    case_dir = require_prepared_case(case_root)
    applier = _FIX_APPLIERS[fix.action_type]
    applier(case_dir, fix.value)
