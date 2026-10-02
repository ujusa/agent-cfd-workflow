"""The complete v1 LangGraph workflow (plan section 10), START to END.

    START -> intake -> plan_study -> policy_check -> [human_approval]
          -- interrupt_before: prepare_baseline --
          -> prepare_baseline -> run_mesh -> mesh_quality_gate
          -> run_baseline -> solver_health_gate -> extract_baseline_qoi
                                   |
                                   +--FAILED, retries remaining--> diagnose_solver --> run_baseline
                                   +--FAILED, retries exhausted--> END
          -> mesh_refinement -> mesh_independence_gate
                                   |
                                   +--PASSED--> run_parameter_cases -> cross_case_analysis
                                   +--FAILED/BLOCKED--> END
          -> review_results -> final_report -> END

mesh_quality_gate FAILED still routes straight to END: the diagnostic
allowlist (relaxation/numerical-solver-setting/time-control) has no action
that actually changes mesh quality -- fixing that would mean touching
geometry, which is off-limits (AGENTS.md section 7) -- so a bad mesh is not
auto-recoverable in v1.

mesh_refinement and run_parameter_cases each run a small batch of
additional cases through app.case_pipeline.run_case_pipeline (prepare ->
mesh -> solve -> QoI, the same gates as the baseline path, but without the
bounded-retry loop -- see that module's docstring for why). A failed case
within a batch is recorded and the batch continues (case isolation, plan
section 46); mesh_independence_gate is the one place a failure actually
stops the workflow, per plan section 40 point 4 ("refuse to continue when
the required gate fails").

review_results (app.agents.reviewer) reads only already-written artifacts
and produces a cited Review; final_report (app.audit + app.report) is the
last stage gate -- it re-verifies every required artifact is actually on
disk and every gate it depends on actually PASSED before writing
reports/final_report.md, and writes nothing at all if that check fails
(plan section 28, Milestone 10).

Every node is a thin wrapper around a deterministic tool from
app/tools/*.py, app/validation/*.py, app/case_pipeline.py, app/audit.py, or
app/report.py, or (for plan_study/diagnose_solver/review_results) a Bedrock
agent -- the graph itself makes no CFD or validation decisions. Every node
that makes a decision records an AgentDecision (plan section 24) and every
stage writes its artifact contract under runs/<run_id>/ (section 25).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app import config
from app.agents.diagnostic import bedrock_diagnose_solver_failure
from app.agents.planner import bedrock_plan_study
from app.agents.reviewer import bedrock_review_results
from app.artifacts import write_run_artifact
from app.audit import run_stage_gate_audit
from app.case_pipeline import run_case_pipeline
from app.plots import write_qoi_vs_velocity_plot
from app.policy import check_diagnostic_fix, check_plan_policy
from app.report import render_final_report
from app.schemas import AgentDecision, StudyPlan
from app.state import AgentState
from app.tools import case_tools, openfoam_tools
from app.validation.common import GateStatus
from app.validation.conservation import check_conservation
from app.validation.convergence import check_case_integrity, check_solver_health
from app.validation.mesh_independence import assess_mesh_independence, check_mesh_quality
from app.validation.qoi import extract_qoi, write_qoi_artifacts

logger = logging.getLogger("agentic_cfd.graph")


def _log(stage: str, state: AgentState, **fields: Any) -> None:
    payload = {"run_id": state.get("run_id"), "stage": stage, **fields}
    logger.info("stage=%s %s", stage, payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_decision(
    run_id: str,
    prior_decisions: list[dict],
    *,
    agent: str,
    action: str,
    reason: str,
    evidence: list[str],
    policy_check: str,
    human_approval_required: bool,
) -> dict:
    """Appends one AgentDecision and rewrites audit.json with the full,
    accumulated decision history for this run (plan sections 24-25).

    `prior_decisions` is an explicit running list rather than reading
    state["agent_decisions"] directly, because a single node may record more
    than one decision (e.g. node_prepare_baseline) -- state isn't updated
    with the first decision until the node returns, so decision_id numbering
    would collide if each call recomputed its index from `state` alone.
    """
    decision = AgentDecision(
        decision_id=f"dec_{len(prior_decisions) + 1:05d}",
        agent=agent,
        action=action,
        reason=reason,
        evidence=evidence,
        policy_check=policy_check,
        human_approval_required=human_approval_required,
        timestamp=_now(),
    ).model_dump()
    write_run_artifact(run_id, "audit.json", {"decisions": prior_decisions + [decision]})
    return decision


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------

def node_intake(state: AgentState) -> dict:
    _log("intake", state, user_goal=state.get("user_goal"))
    write_run_artifact(
        state["run_id"],
        "study.json",
        {"run_id": state["run_id"], "user_goal": state["user_goal"], "created_at": _now()},
    )
    return {"current_stage": "intake"}


def node_plan_study(state: AgentState) -> dict:
    plan = bedrock_plan_study(state["user_goal"])
    _log("plan_study", state, baseline_case=plan.baseline_case, n_cases=len(plan.cases))
    write_run_artifact(state["run_id"], "plan.json", plan.model_dump())
    decision = _record_decision(
        state["run_id"], state.get("agent_decisions") or [],
        agent="planner",
        action="propose_study_plan",
        reason=f"Produced a StudyPlan for objective: {state['user_goal']!r}",
        evidence=["plan.json"],
        policy_check="n/a",
        human_approval_required=True,
    )
    return {
        "current_stage": "plan_study",
        "study_plan": plan.model_dump(),
        "agent_decisions": [decision],
    }


def node_policy_check(state: AgentState) -> dict:
    plan = StudyPlan.model_validate(state["study_plan"])
    result = check_plan_policy(plan)
    _log("policy_check", state, status=result.status, reasons=result.reasons)
    decision = _record_decision(
        state["run_id"], state.get("agent_decisions") or [],
        agent="policy_engine",
        action="check_plan_policy",
        reason="plan satisfies policy" if result.status == "PASSED" else "; ".join(result.reasons),
        evidence=["plan.json"],
        policy_check=result.status,
        human_approval_required=True,
    )
    update: dict = {"current_stage": "policy_check", "agent_decisions": [decision]}
    if result.status != "PASSED":
        update["errors"] = [f"policy_check FAILED: {result.reasons}"]
    return update


def node_human_approval(state: AgentState) -> dict:
    """Never grants approval itself. The graph is compiled with
    interrupt_before=['prepare_baseline'], so execution pauses right after
    this node; an external caller must call update_state to set
    approval_status before resuming (AGENTS.md section 8: the agent must
    not bypass this gate)."""
    _log("human_approval", state, approval_status=state.get("approval_status"))
    return {"current_stage": "human_approval"}


def node_prepare_baseline(state: AgentState) -> dict:
    approval = state.get("approval_status") or {}
    if not approval.get("approved"):
        _log("prepare_baseline", state, blocked=True)
        return {
            "current_stage": "blocked_awaiting_approval",
            "errors": ["prepare_baseline refused: approval_status.approved is not True"],
        }

    write_run_artifact(state["run_id"], "approval.json", approval)
    decisions_so_far = list(state.get("agent_decisions") or [])
    approval_decision = _record_decision(
        state["run_id"], decisions_so_far,
        agent="human",
        action="approve_study_plan",
        reason=approval.get("notes") or "approved via CLI",
        evidence=["approval.json", "plan.json"],
        policy_check="PASSED",
        human_approval_required=True,
    )
    decisions_so_far.append(approval_decision)

    plan = StudyPlan.model_validate(state["study_plan"])
    case_spec = plan.cases[0]
    case_root = case_tools.prepare_case(
        state["run_id"],
        case_spec.case_id,
        {"inlet_velocity": case_spec.inlet_velocity, "mesh_level": case_spec.mesh_level},
    )
    integrity = check_case_integrity(case_root / "case")
    write_run_artifact(
        state["run_id"], "case_manifest.json", [{**case_spec.model_dump(), "case_root": str(case_root)}]
    )
    prepare_decision = _record_decision(
        state["run_id"], decisions_so_far,
        agent="case_preparation",
        action="prepare_case",
        reason=f"prepared case {case_spec.case_id!r} from the immutable benchmark template",
        evidence=["case_manifest.json", str(case_root / "metadata.json")],
        policy_check=integrity.status,
        human_approval_required=False,
    )

    _log("prepare_baseline", state, case_id=case_spec.case_id, case_root=str(case_root),
         integrity_status=integrity.status)
    return {
        "current_stage": "prepare_baseline",
        "current_case_id": case_spec.case_id,
        "case_specs": [case_spec.model_dump()],
        "artifacts": {case_spec.case_id: {"case_root": str(case_root)}},
        "validation_results": {f"{case_spec.case_id}:case_integrity": integrity.model_dump()},
        "agent_decisions": [approval_decision, prepare_decision],
    }


def _case_root(state: AgentState) -> Path:
    case_id = state["current_case_id"]
    return Path(state["artifacts"][case_id]["case_root"])


def node_run_mesh(state: AgentState) -> dict:
    case_id = state["current_case_id"]
    case_root = _case_root(state)
    mesh_op = openfoam_tools.run_mesh(case_root)
    check_op = openfoam_tools.check_mesh(case_root)
    _log("run_mesh", state, case_id=case_id, mesh_ok=mesh_op.success, check_mesh_ok=check_op.success)
    return {
        "current_stage": "run_mesh",
        "mesh_results": {case_id: {"mesh": mesh_op.to_dict(), "check_mesh": check_op.to_dict()}},
    }


def node_mesh_quality_gate(state: AgentState) -> dict:
    case_id = state["current_case_id"]
    check_op = state["mesh_results"][case_id]["check_mesh"]
    log_text = Path(check_op["log_path"]).read_text()
    result = check_mesh_quality(log_text, check_op["return_code"], log_path=check_op["log_path"])
    _log("mesh_quality_gate", state, case_id=case_id, status=result.status, reasons=result.reasons)
    write_run_artifact(state["run_id"], "mesh_report.json", {case_id: result.model_dump()})
    decision = _record_decision(
        state["run_id"], state.get("agent_decisions") or [],
        agent="mesh_quality_gate",
        action="check_mesh_quality",
        reason="mesh quality within thresholds" if result.status == "PASSED" else "; ".join(result.reasons),
        evidence=["mesh_report.json", check_op["log_path"]],
        policy_check=result.status,
        human_approval_required=False,
    )
    update: dict = {
        "current_stage": "mesh_quality_gate",
        "validation_results": {f"{case_id}:mesh_quality": result.model_dump()},
        "agent_decisions": [decision],
    }
    if result.status != "PASSED":
        update["errors"] = [f"mesh_quality_gate FAILED for {case_id}: {result.reasons}"]
    return update


def node_run_baseline(state: AgentState) -> dict:
    case_id = state["current_case_id"]
    case_root = _case_root(state)
    attempt = (state.get("retry_count") or {}).get(case_id, 0)
    solve_op = openfoam_tools.run_solver(case_root)
    _log("run_baseline", state, case_id=case_id, attempt=attempt,
         solved_ok=solve_op.success, elapsed_s=solve_op.elapsed_s)
    return {"current_stage": "run_baseline", "solver_results": {case_id: solve_op.to_dict()}}


def node_solver_health_gate(state: AgentState) -> dict:
    case_id = state["current_case_id"]
    solve_op = state["solver_results"][case_id]
    log_text = Path(solve_op["log_path"]).read_text()
    result = check_solver_health(log_text, solve_op["return_code"], log_path=solve_op["log_path"])
    _log("solver_health_gate", state, case_id=case_id, status=result.status,
         converged=result.converged, iterations=result.iterations)
    write_run_artifact(state["run_id"], "solver_health.json", {case_id: result.model_dump()})
    decision = _record_decision(
        state["run_id"], state.get("agent_decisions") or [],
        agent="solver_health_gate",
        action="check_solver_health",
        reason=(
            f"converged in {result.iterations} iterations" if result.converged
            else "; ".join(result.reasons) or "did not converge"
        ),
        evidence=["solver_health.json", solve_op["log_path"]],
        policy_check=result.status,
        human_approval_required=False,
    )
    update: dict = {
        "current_stage": "solver_health_gate",
        "validation_results": {f"{case_id}:solver_health": result.model_dump()},
        "agent_decisions": [decision],
    }
    if result.status != "PASSED":
        update["errors"] = [f"solver_health_gate FAILED for {case_id}: {result.reasons}"]
    return update


def node_diagnose_solver(state: AgentState) -> dict:
    """Only reached when solver_health_gate FAILED and retries remain
    (route_after_solver_health). Proposes exactly one DiagnosticFix from the
    fixed allowlist, policy-checks it, and -- only if that passes -- applies
    it and increments retry_count. A policy-rejected proposal is never
    applied; the run ends FAILED rather than silently skipping the fix.
    """
    case_id = state["current_case_id"]
    run_id = state["run_id"]
    retry_count = (state.get("retry_count") or {}).get(case_id, 0)
    attempt = retry_count + 1

    health = state["validation_results"][f"{case_id}:solver_health"]
    evidence = {
        "converged": health["converged"],
        "iterations": health["iterations"],
        "last_time": health["last_time"],
        "residual_trend": health["residual_trend"],
        "final_residuals": health["final_residuals"],
        "fatal_error": health["fatal_error"],
        "reasons": health["reasons"],
    }

    fix = bedrock_diagnose_solver_failure(
        evidence, case_id=case_id, attempt=attempt, max_retries=config.MAX_SOLVER_RETRIES
    )
    policy_result = check_diagnostic_fix(fix)
    _log("diagnose_solver", state, case_id=case_id, attempt=attempt,
         action_type=fix.action_type, value=fix.value, policy_check=policy_result.status)

    decisions_so_far = list(state.get("agent_decisions") or [])
    decision = _record_decision(
        run_id, decisions_so_far,
        agent="diagnostic_agent",
        action=f"propose_fix:{fix.action_type}",
        reason=fix.reason,
        evidence=["solver_health.json", "diagnostics.json"],
        policy_check=policy_result.status,
        human_approval_required=False,
    )

    diagnosis_record = {
        "case_id": case_id,
        "attempt": attempt,
        "evidence": evidence,
        "proposed_fix": fix.model_dump(),
        "policy_check": policy_result.status,
        "policy_reasons": policy_result.reasons,
        "timestamp": _now(),
    }
    diagnostics_so_far = list(state.get("diagnostics") or []) + [diagnosis_record]
    write_run_artifact(run_id, "diagnostics.json", {"attempts": diagnostics_so_far})

    update: dict = {
        "current_stage": "diagnose_solver",
        "agent_decisions": [decision],
        "diagnostics": [diagnosis_record],
    }

    if policy_result.status != "PASSED":
        update["errors"] = [
            f"diagnose_solver: proposed fix rejected by policy for {case_id}: {policy_result.reasons}"
        ]
        return update

    case_root = _case_root(state)
    case_tools.apply_diagnostic_fix(case_root, fix)
    update["retry_count"] = {case_id: attempt}
    return update


def node_extract_baseline_qoi(state: AgentState) -> dict:
    case_id = state["current_case_id"]
    case_root = _case_root(state)
    case_dir = case_root / "case"
    openfoam_tools.run_postprocess(case_root)
    qoi_result = extract_qoi(case_dir, case_id=case_id)
    write_qoi_artifacts(case_root, qoi_result)

    validation_update: dict = {f"{case_id}:qoi_extraction_complete": qoi_result.complete}
    conservation_status = "n/a"
    if qoi_result.mass_flow_in is not None and qoi_result.mass_flow_out is not None:
        conservation = check_conservation(qoi_result.mass_flow_in, qoi_result.mass_flow_out)
        validation_update[f"{case_id}:conservation"] = conservation.model_dump()
        conservation_status = conservation.status

    _log("extract_baseline_qoi", state, case_id=case_id, complete=qoi_result.complete)
    decision = _record_decision(
        state["run_id"], state.get("agent_decisions") or [],
        agent="qoi_extraction",
        action="extract_qoi",
        reason=(
            "QoIs extracted and conservation checked" if qoi_result.complete
            else f"partial extraction: {qoi_result.errors}"
        ),
        evidence=[str(case_root / "results" / "qoi.json")],
        policy_check=conservation_status,
        human_approval_required=False,
    )
    return {
        "current_stage": "extract_baseline_qoi",
        "qoi_results": {case_id: qoi_result.model_dump()},
        "validation_results": validation_update,
        "agent_decisions": [decision],
    }


def node_mesh_refinement(state: AgentState) -> dict:
    """Runs the baseline's inlet_velocity through every mesh level in the
    study plan other than the baseline's own level (plan section 4: mesh
    independence uses the baseline velocity only)."""
    run_id = state["run_id"]
    plan = StudyPlan.model_validate(state["study_plan"])
    baseline_spec = plan.cases[0]
    levels_to_run = [lvl for lvl in plan.mesh_levels if lvl != baseline_spec.mesh_level]

    validation_update: dict = {}
    qoi_update: dict = {}
    artifacts_update: dict = {}
    case_specs_update: list = []
    levels_summary = []

    for level in levels_to_run:
        case_id = f"baseline_{level}"
        pipeline_result = run_case_pipeline(
            run_id, case_id, {"inlet_velocity": baseline_spec.inlet_velocity, "mesh_level": level}
        )
        artifacts_update[case_id] = {"case_root": pipeline_result["case_root"]}
        case_specs_update.append(
            {"case_id": case_id, "inlet_velocity": baseline_spec.inlet_velocity, "mesh_level": level}
        )
        for gate in ("case_integrity", "mesh_quality", "solver_health", "conservation"):
            if gate in pipeline_result:
                validation_update[f"{case_id}:{gate}"] = pipeline_result[gate]
        if "qoi" in pipeline_result:
            qoi_update[case_id] = pipeline_result["qoi"]
        levels_summary.append(
            {"mesh_level": level, "case_id": case_id, "success": pipeline_result["success"],
             "stage_reached": pipeline_result["stage_reached"]}
        )
        _log("mesh_refinement", state, case_id=case_id, mesh_level=level, success=pipeline_result["success"])

    write_run_artifact(run_id, "mesh_refinement.json", {"levels_run": levels_summary})

    decision = _record_decision(
        run_id, list(state.get("agent_decisions") or []),
        agent="mesh_refinement",
        action="run_mesh_levels",
        reason=f"ran mesh levels {levels_to_run} at baseline inlet_velocity={baseline_spec.inlet_velocity}",
        evidence=["mesh_refinement.json"],
        policy_check="n/a",
        human_approval_required=False,
    )

    return {
        "current_stage": "mesh_refinement",
        "validation_results": validation_update,
        "qoi_results": qoi_update,
        "artifacts": artifacts_update,
        "case_specs": case_specs_update,
        "agent_decisions": [decision],
    }


def node_mesh_independence_gate(state: AgentState) -> dict:
    """Gate E. Refuses to continue to the parameter sweep unless both the
    medium and fine mesh levels produced complete QoIs AND their relative
    change is within threshold (plan section 40 point 4)."""
    run_id = state["run_id"]
    plan = StudyPlan.model_validate(state["study_plan"])
    baseline_spec = plan.cases[0]
    qoi_results = state.get("qoi_results") or {}

    level_to_case_id = {baseline_spec.mesh_level: "baseline"}
    for level in plan.mesh_levels:
        if level != baseline_spec.mesh_level:
            level_to_case_id[level] = f"baseline_{level}"

    qois_by_level: dict[str, dict[str, float]] = {}
    for level, case_id in level_to_case_id.items():
        qoi = qoi_results.get(case_id)
        if qoi and qoi.get("complete"):
            qois_by_level[level] = {
                name: qoi[name] for name in config.MESH_INDEPENDENCE_QOIS if qoi.get(name) is not None
            }

    decisions_so_far = list(state.get("agent_decisions") or [])

    if not {"medium", "fine"} <= set(qois_by_level):
        status = "BLOCKED"
        reasons = ["insufficient mesh levels with complete QoIs to assess independence (need medium and fine)"]
        write_run_artifact(run_id, "mesh_independence.json", {"status": status, "reasons": reasons})
        decision = _record_decision(
            run_id, decisions_so_far,
            agent="mesh_independence_gate",
            action="assess_mesh_independence",
            reason="; ".join(reasons),
            evidence=["mesh_independence.json"],
            policy_check=status,
            human_approval_required=False,
        )
        return {
            "current_stage": "mesh_independence_gate",
            "agent_decisions": [decision],
            "errors": [f"mesh_independence_gate {status}: {reasons}"],
        }

    result = assess_mesh_independence(qois_by_level)
    write_run_artifact(run_id, "mesh_independence.json", result.model_dump())
    decision = _record_decision(
        run_id, decisions_so_far,
        agent="mesh_independence_gate",
        action="assess_mesh_independence",
        reason="mesh independence satisfied" if result.status == "PASSED" else "; ".join(result.reasons),
        evidence=["mesh_independence.json"],
        policy_check=result.status,
        human_approval_required=False,
    )
    _log("mesh_independence_gate", state, status=result.status, relative_changes=result.relative_changes)
    update: dict = {
        "current_stage": "mesh_independence_gate",
        "validation_results": {"_mesh_independence": result.model_dump()},
        "agent_decisions": [decision],
    }
    if result.status != "PASSED":
        update["errors"] = [f"mesh_independence_gate FAILED: {result.reasons}"]
    return update


def node_run_parameter_cases(state: AgentState) -> dict:
    """Runs every case in the approved study plan beyond the baseline
    (plan.cases[1:]) -- whatever inlet_velocity/mesh_level the planner
    proposed and the policy checker already approved."""
    run_id = state["run_id"]
    plan = StudyPlan.model_validate(state["study_plan"])
    sweep_cases = plan.cases[1:]

    validation_update: dict = {}
    qoi_update: dict = {}
    artifacts_update: dict = {}
    case_specs_update: list = []
    results_summary = []

    for case_spec in sweep_cases:
        pipeline_result = run_case_pipeline(
            run_id, case_spec.case_id,
            {"inlet_velocity": case_spec.inlet_velocity, "mesh_level": case_spec.mesh_level},
        )
        artifacts_update[case_spec.case_id] = {"case_root": pipeline_result["case_root"]}
        case_specs_update.append(case_spec.model_dump())
        for gate in ("case_integrity", "mesh_quality", "solver_health", "conservation"):
            if gate in pipeline_result:
                validation_update[f"{case_spec.case_id}:{gate}"] = pipeline_result[gate]
        if "qoi" in pipeline_result:
            qoi_update[case_spec.case_id] = pipeline_result["qoi"]
        results_summary.append({
            "case_id": case_spec.case_id, "inlet_velocity": case_spec.inlet_velocity,
            "mesh_level": case_spec.mesh_level, "success": pipeline_result["success"],
            "stage_reached": pipeline_result["stage_reached"],
        })
        _log("run_parameter_cases", state, case_id=case_spec.case_id, success=pipeline_result["success"])

    write_run_artifact(run_id, "sweep_cases.json", {"results": results_summary})
    decision = _record_decision(
        run_id, list(state.get("agent_decisions") or []),
        agent="parameter_sweep",
        action="run_parameter_cases",
        reason=f"ran {len(sweep_cases)} sweep case(s): {[c.case_id for c in sweep_cases]}",
        evidence=["sweep_cases.json"],
        policy_check="n/a",
        human_approval_required=False,
    )

    return {
        "current_stage": "run_parameter_cases",
        "validation_results": validation_update,
        "qoi_results": qoi_update,
        "artifacts": artifacts_update,
        "case_specs": case_specs_update,
        "agent_decisions": [decision],
    }


def node_cross_case_analysis(state: AgentState) -> dict:
    """Aggregates every case's QoIs into sweep_results.json and, if there
    are at least two medium-mesh velocity points, a qoi_vs_velocity.png
    plot (plan section 20/21). Purely aggregation -- no new CFD execution,
    no new gate decisions about individual cases."""
    run_id = state["run_id"]
    qoi_results = state.get("qoi_results") or {}
    specs_by_case_id = {c["case_id"]: c for c in state.get("case_specs") or []}

    rows = []
    for case_id, qoi in qoi_results.items():
        spec = specs_by_case_id.get(case_id, {})
        rows.append({
            "case_id": case_id,
            "inlet_velocity": spec.get("inlet_velocity"),
            "mesh_level": spec.get("mesh_level"),
            "pressure_drop": qoi.get("pressure_drop"),
            "mass_imbalance": qoi.get("mass_imbalance"),
            "maximum_velocity": qoi.get("maximum_velocity"),
            "average_velocity": qoi.get("average_velocity"),
            "complete": qoi.get("complete"),
        })

    write_run_artifact(run_id, "sweep_results.json", {"cases": rows})
    plot_path = write_qoi_vs_velocity_plot(run_id, rows)

    # Finalize case_manifest.json with every case actually run (baseline +
    # mesh refinement + sweep) -- node_prepare_baseline's earlier write only
    # had the baseline, since mesh refinement/sweep cases didn't exist yet.
    artifacts = state.get("artifacts") or {}
    full_manifest = [
        {**spec, "case_root": artifacts.get(spec["case_id"], {}).get("case_root")}
        for spec in (state.get("case_specs") or [])
    ]
    write_run_artifact(run_id, "case_manifest.json", full_manifest)

    decision = _record_decision(
        run_id, list(state.get("agent_decisions") or []),
        agent="cross_case_analysis",
        action="aggregate_results",
        reason=f"aggregated {len(rows)} case(s) into sweep_results.json",
        evidence=["sweep_results.json"] + ([plot_path] if plot_path else []),
        policy_check="n/a",
        human_approval_required=False,
    )
    _log("cross_case_analysis", state, n_cases=len(rows), plot_written=bool(plot_path))

    return {"current_stage": "cross_case_analysis", "agent_decisions": [decision]}


def node_review_results(state: AgentState) -> dict:
    """Builds the evidence bundle strictly from already-written artifacts
    (app.agents.reviewer.build_evidence_bundle) and asks the review agent
    to produce a cited Review -- never from raw logs or in-memory state
    directly, so the review is reproducible from the run directory alone."""
    run_id = state["run_id"]
    review = bedrock_review_results(run_id)
    write_run_artifact(run_id, "review.json", review.model_dump())

    decision = _record_decision(
        run_id, list(state.get("agent_decisions") or []),
        agent="review_agent",
        action="review_results",
        reason=review.summary,
        evidence=["review.json"],
        policy_check="n/a",
        human_approval_required=False,
    )
    _log("review_results", state, n_findings=len(review.findings), n_limitations=len(review.limitations))
    return {"current_stage": "review_results", "agent_decisions": [decision]}


def node_final_report(state: AgentState) -> dict:
    """The final stage gate (plan section 28/Milestone 10). Only writes
    reports/final_report.md if app.audit.run_stage_gate_audit PASSES --
    otherwise the run ends with the audit's reasons recorded as errors and
    no report at all, rather than a report built on missing evidence."""
    run_id = state["run_id"]
    audit_result = run_stage_gate_audit(run_id)
    write_run_artifact(run_id, "stage_gate_audit.json", audit_result.model_dump())

    decision = _record_decision(
        run_id, list(state.get("agent_decisions") or []),
        agent="stage_gate_audit",
        action="run_stage_gate_audit",
        reason="all required artifacts present and gates PASSED" if audit_result.status == "PASSED"
        else "; ".join(audit_result.reasons),
        evidence=["stage_gate_audit.json"],
        policy_check=audit_result.status,
        human_approval_required=False,
    )
    _log("final_report", state, audit_status=audit_result.status)

    if audit_result.status != "PASSED":
        return {
            "current_stage": "final_report",
            "agent_decisions": [decision],
            "errors": [f"final_report BLOCKED by stage_gate_audit: {audit_result.reasons}"],
        }

    report_text = render_final_report(run_id)
    report_path = config.RUNS_DIR / run_id / "reports" / "final_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text)

    return {
        "current_stage": "completed",
        "agent_decisions": [decision],
        "final_report_path": str(report_path),
    }


# ---------------------------------------------------------------------
# Conditional routing (pure functions of state -- the graph never guesses)
# ---------------------------------------------------------------------

def _gate_status(state: AgentState, key: str) -> GateStatus:
    return state["validation_results"][key]["status"]


def route_after_policy_check(state: AgentState) -> str:
    return "human_approval" if state["agent_decisions"][-1]["policy_check"] == "PASSED" else END


def route_after_prepare_baseline(state: AgentState) -> str:
    """If node_prepare_baseline refused to run (approval gate not satisfied),
    stop here rather than falling through into run_mesh with no case
    prepared -- AGENTS.md section 8."""
    return "run_mesh" if state["current_stage"] == "prepare_baseline" else END


def route_after_mesh_quality(state: AgentState) -> str:
    case_id = state["current_case_id"]
    return "run_baseline" if _gate_status(state, f"{case_id}:mesh_quality") == "PASSED" else END


def route_after_solver_health(state: AgentState) -> str:
    case_id = state["current_case_id"]
    if _gate_status(state, f"{case_id}:solver_health") == "PASSED":
        return "extract_baseline_qoi"
    retry_count = (state.get("retry_count") or {}).get(case_id, 0)
    return "diagnose_solver" if retry_count < config.MAX_SOLVER_RETRIES else END


def route_after_diagnose_solver(state: AgentState) -> str:
    """Only retry if the proposed fix actually passed policy and was
    applied (node_diagnose_solver only bumps retry_count in that case)."""
    case_id = state["current_case_id"]
    retry_count = (state.get("retry_count") or {}).get(case_id, 0)
    last_decision = state["agent_decisions"][-1]
    return "run_baseline" if last_decision["policy_check"] == "PASSED" and retry_count > 0 else END


def route_after_mesh_independence(state: AgentState) -> str:
    return "run_parameter_cases" if state["agent_decisions"][-1]["policy_check"] == "PASSED" else END


# ---------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------

def build_graph(checkpointer) -> CompiledStateGraph:
    g = StateGraph(AgentState)

    g.add_node("intake", node_intake)
    g.add_node("plan_study", node_plan_study)
    g.add_node("policy_check", node_policy_check)
    g.add_node("human_approval", node_human_approval)
    g.add_node("prepare_baseline", node_prepare_baseline)
    g.add_node("run_mesh", node_run_mesh)
    g.add_node("mesh_quality_gate", node_mesh_quality_gate)
    g.add_node("run_baseline", node_run_baseline)
    g.add_node("solver_health_gate", node_solver_health_gate)
    g.add_node("diagnose_solver", node_diagnose_solver)
    g.add_node("extract_baseline_qoi", node_extract_baseline_qoi)
    g.add_node("mesh_refinement", node_mesh_refinement)
    g.add_node("mesh_independence_gate", node_mesh_independence_gate)
    g.add_node("run_parameter_cases", node_run_parameter_cases)
    g.add_node("cross_case_analysis", node_cross_case_analysis)
    g.add_node("review_results", node_review_results)
    g.add_node("final_report", node_final_report)

    g.add_edge(START, "intake")
    g.add_edge("intake", "plan_study")
    g.add_edge("plan_study", "policy_check")
    g.add_conditional_edges(
        "policy_check", route_after_policy_check, {"human_approval": "human_approval", END: END}
    )
    g.add_edge("human_approval", "prepare_baseline")
    g.add_conditional_edges(
        "prepare_baseline", route_after_prepare_baseline, {"run_mesh": "run_mesh", END: END}
    )
    g.add_edge("run_mesh", "mesh_quality_gate")
    g.add_conditional_edges(
        "mesh_quality_gate", route_after_mesh_quality, {"run_baseline": "run_baseline", END: END}
    )
    g.add_edge("run_baseline", "solver_health_gate")
    g.add_conditional_edges(
        "solver_health_gate", route_after_solver_health,
        {"extract_baseline_qoi": "extract_baseline_qoi", "diagnose_solver": "diagnose_solver", END: END},
    )
    g.add_conditional_edges(
        "diagnose_solver", route_after_diagnose_solver, {"run_baseline": "run_baseline", END: END}
    )
    g.add_edge("extract_baseline_qoi", "mesh_refinement")
    g.add_edge("mesh_refinement", "mesh_independence_gate")
    g.add_conditional_edges(
        "mesh_independence_gate", route_after_mesh_independence,
        {"run_parameter_cases": "run_parameter_cases", END: END},
    )
    g.add_edge("run_parameter_cases", "cross_case_analysis")
    g.add_edge("cross_case_analysis", "review_results")
    g.add_edge("review_results", "final_report")
    g.add_edge("final_report", END)

    return g.compile(checkpointer=checkpointer, interrupt_before=["prepare_baseline"])

