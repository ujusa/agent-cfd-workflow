from __future__ import annotations

from pydantic import BaseModel, ValidationError

from app import config
from app.schemas import DiagnosticFix, StudyPlan
from app.tools.case_tools import CaseParameters
from app.validation.common import GateStatus


class PolicyCheckResult(BaseModel):
    status: GateStatus
    reasons: list[str]


def check_plan_policy(plan: StudyPlan) -> PolicyCheckResult:
    reasons: list[str] = []
    allowed_params = set(config.PARAMETER_BOUNDS) | {"mesh_level"}

    for name in plan.permitted_parameters:
        if name not in allowed_params:
            reasons.append(f"parameter not allowed by policy: {name!r}")

    if not plan.cases:
        reasons.append("study plan has no cases")

    for case in plan.cases:
        try:
            CaseParameters(inlet_velocity=case.inlet_velocity, mesh_level=case.mesh_level)
        except ValidationError as exc:
            reasons.append(f"case {case.case_id!r} failed parameter validation: {exc}")

    if plan.cases:
        if plan.cases[0].case_id != "baseline":
            reasons.append(
                f"plan.cases[0] (the baseline case) must have case_id 'baseline', "
                f"got {plan.cases[0].case_id!r}"
            )
        reserved_case_ids = {"baseline"} | {f"baseline_{level}" for level in plan.mesh_levels}
        seen_case_ids: set[str] = set()
        for case in plan.cases:
            if case.case_id in seen_case_ids:
                reasons.append(f"duplicate case_id in plan.cases: {case.case_id!r}")
            seen_case_ids.add(case.case_id)
        for case in plan.cases[1:]:
            if case.case_id in reserved_case_ids:
                reasons.append(
                    f"case_id {case.case_id!r} is reserved for the automatic mesh-"
                    f"refinement step and must not be listed explicitly in plan.cases "
                    f"beyond the baseline -- mesh_levels already covers this"
                )

    if not plan.requires_human_approval:
        reasons.append(
            "study plan must require human approval before execution (AGENTS.md section 8)"
        )

    required_levels = {"medium", "fine"}
    if not required_levels.issubset(set(plan.mesh_levels)):
        reasons.append(
            f"mesh_levels must include at least {sorted(required_levels)} for mesh "
            f"independence (plan section 3, item 10); got {plan.mesh_levels}"
        )

    status: GateStatus = "PASSED" if not reasons else "FAILED"
    return PolicyCheckResult(status=status, reasons=reasons)


def check_diagnostic_fix(fix: DiagnosticFix) -> PolicyCheckResult:
    """The deterministic policy checker every diagnostic-agent proposal
    must pass before app.tools.case_tools.apply_diagnostic_fix ever touches
    a case directory (plan section 39: "Every proposed action must pass a
    deterministic policy checker before execution"). Re-validates
    independently of the schema's own bounds check -- this function must
    not trust that the caller already validated the fix.
    """
    reasons: list[str] = []

    if fix.action_type not in config.DIAGNOSTIC_FIX_BOUNDS:
        reasons.append(f"action_type not in the diagnostic allowlist: {fix.action_type!r}")
    else:
        bounds = config.DIAGNOSTIC_FIX_BOUNDS[fix.action_type]
        if not (bounds["min"] <= fix.value <= bounds["max"]):
            reasons.append(
                f"{fix.action_type} value {fix.value} outside allowed range "
                f"[{bounds['min']}, {bounds['max']}]"
            )

    status: GateStatus = "PASSED" if not reasons else "FAILED"
    return PolicyCheckResult(status=status, reasons=reasons)
