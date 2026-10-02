from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.artifacts import read_run_artifact
from app.paths import validate_id
from app.validation.common import GateStatus

REQUIRED_ARTIFACTS = [
    "study.json",
    "plan.json",
    "approval.json",
    "case_manifest.json",
    "mesh_report.json",
    "solver_health.json",
    "mesh_independence.json",
    "sweep_results.json",
    "review.json",
    "audit.json",
]


class AuditResult(BaseModel):
    status: GateStatus
    checked_artifacts: list[str]
    missing_artifacts: list[str]
    reasons: list[str]


def run_stage_gate_audit(run_id: str) -> AuditResult:
    validate_id("run_id", run_id)
    reasons: list[str] = []
    checked: list[str] = []
    missing: list[str] = []

    loaded: dict = {}
    for name in REQUIRED_ARTIFACTS:
        try:
            loaded[name] = read_run_artifact(run_id, name)
            checked.append(name)
        except FileNotFoundError:
            missing.append(name)
    if missing:
        reasons.append(f"missing required artifact(s): {missing}")

    approval = loaded.get("approval.json")
    if approval is not None and not approval.get("approved"):
        reasons.append("approval.json exists but approved is not True")

    manifest = loaded.get("case_manifest.json")
    if manifest is not None:
        if not manifest:
            reasons.append("case_manifest.json is empty -- no case was ever run")
        else:
            for entry in manifest:
                case_root = entry.get("case_root")
                if not case_root:
                    reasons.append(f"case {entry.get('case_id')!r} has no recorded case_root")
                elif not Path(case_root).is_dir():
                    reasons.append(
                        f"case {entry.get('case_id')!r} case_root does not exist on disk: {case_root}"
                    )

    mesh_independence = loaded.get("mesh_independence.json")
    if mesh_independence is not None and mesh_independence.get("status") != "PASSED":
        reasons.append(
            f"mesh_independence.json status is {mesh_independence.get('status')!r}, not PASSED"
        )

    solver_health = loaded.get("solver_health.json")
    if solver_health is not None and not solver_health:
        reasons.append("solver_health.json is empty -- no solver health result was ever recorded")

    mesh_report = loaded.get("mesh_report.json")
    if mesh_report is not None and not mesh_report:
        reasons.append("mesh_report.json is empty -- no mesh quality result was ever recorded")

    audit_log = loaded.get("audit.json")
    if audit_log is not None and not audit_log.get("decisions"):
        reasons.append("audit.json has no recorded decisions")

    review = loaded.get("review.json")
    if review is not None and not review.get("summary"):
        reasons.append("review.json has no summary")

    status: GateStatus = "PASSED" if not reasons else "FAILED"
    return AuditResult(
        status=status, checked_artifacts=checked, missing_artifacts=missing, reasons=reasons
    )
