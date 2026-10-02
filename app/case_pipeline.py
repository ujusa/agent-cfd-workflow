"""Shared single-case execution pipeline: prepare -> mesh -> check_mesh ->
solve -> postprocess -> extract_qoi, applying the same deterministic gates
used throughout (Gates A, B, C, D). Used by app.graph's node_mesh_refinement
and node_run_parameter_cases to run additional cases beyond the baseline
without duplicating tool-calling logic.

The baseline case still runs through its own dedicated graph nodes
(app/graph.py's node_prepare_baseline etc.), which additionally wire in the
Milestone 6 bounded-retry loop. Cases run through this helper do NOT retry
on solver failure -- a failed case is reported (via `success=False` and
whichever of mesh_quality/solver_health/conservation got populated) and the
caller moves on to the next case. This is deliberate case isolation (plan
section 46, item 5): one bad case in a mesh-refinement or parameter-sweep
batch must not block the others. Extending bounded retry to batch cases is
a reasonable future improvement, not required by Milestones 7-8.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools import case_tools, openfoam_tools
from app.validation.conservation import check_conservation
from app.validation.convergence import check_case_integrity, check_solver_health
from app.validation.mesh_independence import check_mesh_quality
from app.validation.qoi import extract_qoi, write_qoi_artifacts


def run_case_pipeline(run_id: str, case_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Returns a dict always containing case_id/success/stage_reached, plus
    whichever of case_integrity/mesh_quality/solver_health/qoi/conservation
    were actually reached before a gate failed."""
    result: dict[str, Any] = {"case_id": case_id, "success": False, "stage_reached": "prepare_case"}

    case_root = case_tools.prepare_case(run_id, case_id, parameters)
    result["case_root"] = str(case_root)

    integrity = check_case_integrity(case_root / "case")
    result["case_integrity"] = integrity.model_dump()
    result["stage_reached"] = "case_integrity"
    if integrity.status != "PASSED":
        return result

    mesh_op = openfoam_tools.run_mesh(case_root)
    check_op = openfoam_tools.check_mesh(case_root)
    mesh_quality = check_mesh_quality(
        Path(check_op.log_path).read_text(), check_op.return_code, log_path=check_op.log_path
    )
    result["mesh_quality"] = mesh_quality.model_dump()
    result["stage_reached"] = "mesh_quality"
    if mesh_quality.status != "PASSED":
        return result

    solve_op = openfoam_tools.run_solver(case_root)
    solver_health = check_solver_health(
        Path(solve_op.log_path).read_text(), solve_op.return_code, log_path=solve_op.log_path
    )
    result["solver_health"] = solver_health.model_dump()
    result["stage_reached"] = "solver_health"
    if solver_health.status != "PASSED":
        return result

    openfoam_tools.run_postprocess(case_root)
    qoi_result = extract_qoi(case_root / "case", case_id=case_id)
    write_qoi_artifacts(case_root, qoi_result)
    result["qoi"] = qoi_result.model_dump()
    result["stage_reached"] = "qoi"

    if qoi_result.mass_flow_in is not None and qoi_result.mass_flow_out is not None:
        conservation = check_conservation(qoi_result.mass_flow_in, qoi_result.mass_flow_out)
        result["conservation"] = conservation.model_dump()
        result["success"] = conservation.status == "PASSED" and qoi_result.complete
    else:
        result["success"] = False

    return result
