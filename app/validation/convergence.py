"""Gate A (case integrity) and Gate C (solver health) -- plan section 19.

Pure functions over text/files already produced by app.tools.openfoam_tools.
No docker, no LLM. Every result is an independently-constructible Pydantic
model so it can be unit tested with synthetic log text.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.validation.common import GateStatus

REQUIRED_CASE_FILES = [
    "0/U",
    "0/p",
    "0/k",
    "0/epsilon",
    "constant/physicalProperties",
    "constant/momentumTransport",
    "system/blockMeshDict",
    "system/controlDict",
    "system/fvSchemes",
    "system/fvSolution",
]

REQUIRED_RESIDUAL_FIELDS = ("Ux", "Uy", "p", "k", "epsilon")

ResidualTrend = Literal["decreasing", "stagnant", "increasing", "unknown"]


class CaseIntegrityResult(BaseModel):
    status: GateStatus
    missing: list[str]
    evidence: list[str]


def check_case_integrity(case_dir: Path) -> CaseIntegrityResult:
    """Gate A. Pass only if every required file the rest of the pipeline
    depends on actually exists in the prepared case."""
    missing = [f for f in REQUIRED_CASE_FILES if not (case_dir / f).is_file()]
    status: GateStatus = "PASSED" if not missing else "FAILED"
    return CaseIntegrityResult(
        status=status,
        missing=missing,
        evidence=[str(case_dir / f) for f in REQUIRED_CASE_FILES],
    )


_NUMBER = r"-?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|nan|inf)"
_RESIDUAL_LINE_RE = re.compile(
    rf"Solving for (?P<field>\w+), Initial residual = (?P<initial>{_NUMBER}), "
    rf"Final residual = (?P<final>{_NUMBER})"
)
_FATAL_RE = re.compile(r"FOAM FATAL ERROR")
_CONVERGED_RE = re.compile(r"SIMPLE solution converged in (\d+) iterations")
_LAST_TIME_RE = re.compile(r"^Time = (\d+)", re.MULTILINE)


class ConvergenceResult(BaseModel):
    status: GateStatus
    converged: bool
    iterations: int | None
    last_time: int | None
    fatal_error: bool
    residual_fields_found: list[str]
    missing_residual_fields: list[str]
    final_residuals: dict[str, float]
    residual_trend: ResidualTrend
    reasons: list[str]
    evidence: list[str]


def parse_residual_history(log_text: str) -> dict[str, list[float]]:
    history: dict[str, list[float]] = {}
    for m in _RESIDUAL_LINE_RE.finditer(log_text):
        history.setdefault(m.group("field"), []).append(float(m.group("final")))
    return history


def _residual_trend(history: dict[str, list[float]]) -> ResidualTrend:
    key_field = "p" if len(history.get("p", [])) >= 2 else next(
        (f for f, v in history.items() if len(v) >= 2), None
    )
    if key_field is None:
        return "unknown"
    series = history[key_field]
    first, last = series[0], series[-1]
    if first <= 0 or not math.isfinite(first) or not math.isfinite(last):
        return "unknown"
    ratio = last / first
    if ratio <= 0.5:
        return "decreasing"
    if ratio >= 2.0:
        return "increasing"
    return "stagnant"


def check_solver_health(
    log_text: str, return_code: int | None, log_path: str | None = None
) -> ConvergenceResult:
    """Gate C. Requires: process exited 0, no fatal error, the solver
    explicitly reported meeting its convergence criteria (not just "ran
    without crashing" -- a run that hits endTime without converging exits 0
    and looks clean otherwise, so this must be checked explicitly), all
    required residual fields present, final residuals finite, residual
    trend not increasing."""
    reasons: list[str] = []

    fatal = bool(_FATAL_RE.search(log_text))
    if fatal:
        reasons.append("FOAM FATAL ERROR found in solver log")

    converged_match = _CONVERGED_RE.search(log_text)
    converged = converged_match is not None
    iterations = int(converged_match.group(1)) if converged_match else None
    if not converged:
        reasons.append("solver did not report convergence within the configured run (hit endTime first)")

    last_time_matches = _LAST_TIME_RE.findall(log_text)
    last_time = int(last_time_matches[-1]) if last_time_matches else None

    history = parse_residual_history(log_text)
    found = sorted(history.keys())
    missing = [f for f in REQUIRED_RESIDUAL_FIELDS if f not in history]
    if missing:
        reasons.append(f"missing residuals for required fields: {missing}")

    final_residuals = {f: v[-1] for f, v in history.items() if v}
    non_finite = [f for f, v in final_residuals.items() if not math.isfinite(v)]
    if non_finite:
        reasons.append(f"non-finite final residual for fields: {non_finite}")

    trend = _residual_trend(history)
    if trend == "increasing":
        reasons.append("residual trend is increasing")

    exited_ok = return_code == 0
    if not exited_ok:
        reasons.append(f"solver did not exit 0 (return_code={return_code})")

    ok = (
        exited_ok and not fatal and converged and not missing and not non_finite
        and trend != "increasing"
    )
    status: GateStatus = "PASSED" if ok else "FAILED"

    return ConvergenceResult(
        status=status,
        converged=converged,
        iterations=iterations,
        last_time=last_time,
        fatal_error=fatal,
        residual_fields_found=found,
        missing_residual_fields=missing,
        final_residuals=final_residuals,
        residual_trend=trend,
        reasons=reasons,
        evidence=[log_path] if log_path else [],
    )
