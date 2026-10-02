"""Structured-output schemas shared by the mock planner (Milestone 3) and
the real Bedrock-backed planner (Milestone 4) -- same schema, different producer.
Plan section 23: every LLM output must use a Pydantic schema, never
free-form prose."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app import config


class CaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    inlet_velocity: float
    mesh_level: Literal["coarse", "medium", "fine"]

    @field_validator("inlet_velocity")
    @classmethod
    def _bounded(cls, v: float) -> float:
        bounds = config.PARAMETER_BOUNDS["inlet_velocity"]
        if not (bounds["min"] <= v <= bounds["max"]):
            raise ValueError(
                f"inlet_velocity {v} outside allowed range [{bounds['min']}, {bounds['max']}]"
            )
        return v


class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str
    baseline_case: str
    cases: list[CaseSpec]
    mesh_levels: list[str]
    qois: list[str]
    permitted_parameters: list[str]
    assumptions: list[str]
    validation_plan: list[str]
    requires_human_approval: bool = True


class AgentDecision(BaseModel):
    """The audit record schema from plan section 24: what happened, why,
    what evidence was used, and which policy allowed it."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    agent: str
    action: str
    reason: str
    evidence: list[str]
    policy_check: str
    human_approval_required: bool
    timestamp: str


class DiagnosticFix(BaseModel):
    """The diagnostic agent's only possible output (plan section 39 / Gate
    C retry loop). `action_type` is the allowlist itself -- there is no
    fourth option. `value`'s meaning and bounds depend on action_type:
    relaxation -> equations relaxation factor, numerical_solver_setting ->
    nNonOrthogonalCorrectors, time_control -> controlDict endTime. Bounds
    come from app.config.DIAGNOSTIC_FIX_BOUNDS -- the single source of
    truth also used by app.policy.check_diagnostic_fix, which re-checks
    this independently before the fix is ever applied (schema validation,
    then policy validation -- AGENTS.md section 2).
    """

    model_config = ConfigDict(extra="forbid")

    action_type: Literal["relaxation", "numerical_solver_setting", "time_control"]
    value: float
    reason: str

    @model_validator(mode="after")
    def _bounded_by_action_type(self) -> "DiagnosticFix":
        bounds = config.DIAGNOSTIC_FIX_BOUNDS[self.action_type]
        if not (bounds["min"] <= self.value <= bounds["max"]):
            raise ValueError(
                f"{self.action_type} value {self.value} outside allowed range "
                f"[{bounds['min']}, {bounds['max']}]"
            )
        return self


class ApprovalRecord(BaseModel):
    """plan section 11."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    approved_by: str
    approved_at: str
    plan_version: str = "1"
    notes: str = ""


class ReviewFinding(BaseModel):
    """One cited claim -- the Claim/Evidence/Metric/Value/Threshold/
    Pass-fail structure from skills/result-review.md."""

    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_file: str
    metric: str
    value: str
    threshold: str = "n/a"
    pass_fail: str


class Review(BaseModel):
    """The review agent's only possible output (plan section 22). Every
    field is grounded in the evidence bundle it was given -- app.agents.
    reviewer builds that bundle from artifacts only, never raw logs."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: list[ReviewFinding]
    trends: list[str]
    limitations: list[str]
    uncertainties: list[str]
