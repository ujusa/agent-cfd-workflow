"""The workflow's typed state (plan section 9). Flat, LangGraph-mergeable
dicts rather than nested structures -- a nested dict under a shallow-merge
reducer would silently clobber sibling keys written by earlier nodes (e.g.
two gates for the same case_id), so validation_results/mesh_results/etc. are
keyed as flat "{case_id}" or "{case_id}:{gate_name}" strings instead.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged = dict(a)
    merged.update(b)
    return merged


class AgentState(TypedDict, total=False):
    run_id: str
    user_goal: str
    study_plan: dict[str, Any] | None
    approval_status: dict[str, Any] | None
    case_specs: Annotated[list[dict[str, Any]], operator.add]
    current_case_id: str | None
    current_stage: str

    # case_id -> {"mesh": OperationResult dict, "check_mesh": OperationResult dict}
    mesh_results: Annotated[dict[str, Any], merge_dicts]
    # case_id -> OperationResult dict
    solver_results: Annotated[dict[str, Any], merge_dicts]
    # "{case_id}:{gate_name}" -> gate result dict (status/reasons/...)
    validation_results: Annotated[dict[str, Any], merge_dicts]
    # case_id -> QoIResult dict
    qoi_results: Annotated[dict[str, Any], merge_dicts]

    diagnostics: Annotated[list[dict[str, Any]], operator.add]
    agent_decisions: Annotated[list[dict[str, Any]], operator.add]
    # case_id -> {"case_root": str, ...}
    artifacts: Annotated[dict[str, Any], merge_dicts]
    errors: Annotated[list[str], operator.add]
    retry_count: Annotated[dict[str, int], merge_dicts]
    final_report_path: str | None


def initial_state(run_id: str, user_goal: str) -> AgentState:
    return AgentState(
        run_id=run_id,
        user_goal=user_goal,
        study_plan=None,
        approval_status=None,
        case_specs=[],
        current_case_id=None,
        current_stage="pending",
        mesh_results={},
        solver_results={},
        validation_results={},
        qoi_results={},
        diagnostics=[],
        agent_decisions=[],
        artifacts={},
        errors=[],
        retry_count={},
        final_report_path=None,
    )
