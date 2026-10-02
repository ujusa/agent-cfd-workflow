"""mock_diagnose_solver_failure: a deterministic stand-in, same triage logic
as skills/convergence-check.md, used for fast hermetic tests and as a
fallback. bedrock_diagnose_solver_failure: the real diagnostic agent,
backed by AWS Bedrock via app.llm.LLMService. Both produce exactly the same
DiagnosticFix schema -- see AGENTS.md section 7 for the allowlist this
schema enforces, and app.policy.check_diagnostic_fix for the independent
policy check every proposal still goes through before it's ever applied.
"""
from __future__ import annotations

import json

from app import config
from app.llm import LLMService, load_prompt_template
from app.schemas import DiagnosticFix


def mock_diagnose_solver_failure(evidence: dict, attempt: int = 1) -> DiagnosticFix:
    bounds = config.DIAGNOSTIC_FIX_BOUNDS
    if evidence.get("fatal_error") or evidence.get("residual_trend") == "increasing":
        return DiagnosticFix(
            action_type="relaxation",
            value=max(bounds["relaxation"]["min"], 0.5),
            reason="residual trend is increasing or a fatal error occurred; lowering the "
            "relaxation factor for a more conservative, stable next attempt",
        )

    if not evidence.get("converged") and evidence.get("residual_trend") in ("decreasing", "stagnant"):
        last_time = evidence.get("last_time") or bounds["time_control"]["min"]
        new_end_time = min(bounds["time_control"]["max"], max(bounds["time_control"]["min"], last_time * 4))
        return DiagnosticFix(
            action_type="time_control",
            value=new_end_time,
            reason=(
                f"solver reached only iteration {last_time} without converging but residuals "
                f"were {evidence.get('residual_trend')}; extending endTime to {new_end_time} "
                "to give it enough iterations to reach the residual targets"
            ),
        )

    return DiagnosticFix(
        action_type="numerical_solver_setting",
        value=min(bounds["numerical_solver_setting"]["max"], 1),
        reason="residuals are not clearly unstable or simply slow; adding a non-orthogonal "
        "corrector to improve pressure-velocity coupling robustness",
    )


def render_diagnostic_prompt(evidence: dict, case_id: str, attempt: int, max_retries: int) -> str:
    template = load_prompt_template("diagnostic.md")
    skill = (config.SKILLS_DIR / "convergence-check.md").read_text()
    bounds = config.DIAGNOSTIC_FIX_BOUNDS

    replacements = {
        "<<SKILL_CONVERGENCE_CHECK>>": skill,
        "<<RELAXATION_MIN>>": str(bounds["relaxation"]["min"]),
        "<<RELAXATION_MAX>>": str(bounds["relaxation"]["max"]),
        "<<NUMERICAL_MIN>>": str(bounds["numerical_solver_setting"]["min"]),
        "<<NUMERICAL_MAX>>": str(bounds["numerical_solver_setting"]["max"]),
        "<<TIME_MIN>>": str(bounds["time_control"]["min"]),
        "<<TIME_MAX>>": str(bounds["time_control"]["max"]),
        "<<EVIDENCE_JSON>>": json.dumps(evidence, indent=2, default=str),
        "<<ATTEMPT_NUMBER>>": str(attempt),
        "<<MAX_RETRIES>>": str(max_retries),
        "<<CASE_ID>>": case_id,
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def bedrock_diagnose_solver_failure(
    evidence: dict,
    case_id: str,
    attempt: int = 1,
    max_retries: int = config.MAX_SOLVER_RETRIES,
    llm: LLMService | None = None,
) -> DiagnosticFix:
    llm = llm or LLMService()
    prompt = render_diagnostic_prompt(evidence, case_id, attempt, max_retries)
    result = llm.structured_plan(prompt, DiagnosticFix)
    assert isinstance(result, DiagnosticFix)
    return result
