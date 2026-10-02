"""Fast, docker-free stand-ins for the OpenFOAM runner operations, used by
the LangGraph workflow/checkpointing tests (tests/test_workflow.py,
tests/test_checkpointing.py) so `pytest` never needs Docker. Real,
docker-backed execution is verified separately and manually per milestone
(see conversation record) -- these tests cover graph wiring and SQLite
checkpointing, not OpenFOAM itself (that's Milestones 1-2's job).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.tools.openfoam_tools import OperationResult

GOOD_CHECK_MESH_LOG = """
Mesh stats
    points:           6468
    faces:            12512
    internal faces:   6046
    cells:            3093
    boundary patches: 5

Checking geometry...
    Mesh non-orthogonality Max: 5.92468 average: 1.7616
    Max skewness = 0.259438 OK.

Mesh OK.

End
"""

GOOD_SOLVER_LOG = """
Time = 1s
smoothSolver:  Solving for Ux, Initial residual = 0.1, Final residual = 0.01, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.1, Final residual = 0.01, No Iterations 5
GAMG:  Solving for p, Initial residual = 0.1, Final residual = 0.01, No Iterations 3
smoothSolver:  Solving for epsilon, Initial residual = 0.1, Final residual = 0.01, No Iterations 3
smoothSolver:  Solving for k, Initial residual = 0.1, Final residual = 0.01, No Iterations 4

Time = 2s
smoothSolver:  Solving for Ux, Initial residual = 0.01, Final residual = 0.0005, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.01, Final residual = 0.0005, No Iterations 5
GAMG:  Solving for p, Initial residual = 0.01, Final residual = 0.0005, No Iterations 3
smoothSolver:  Solving for epsilon, Initial residual = 0.01, Final residual = 0.0005, No Iterations 3
smoothSolver:  Solving for k, Initial residual = 0.01, Final residual = 0.0005, No Iterations 4

SIMPLE solution converged in 2 iterations

End
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_result(operation: str, log_path: Path, text: str) -> OperationResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text)
    now = _now()
    return OperationResult(
        operation=operation,
        command=f"fake-{operation}",
        success=True,
        return_code=0,
        timed_out=False,
        started_at=now,
        ended_at=now,
        elapsed_s=0.01,
        log_path=str(log_path),
    )


def fake_run_mesh(case_root: Path, timeout: int | None = None) -> OperationResult:
    return _fake_result("mesh", case_root / "logs" / "blockMesh.log", "blockMesh ... End\n")


def fake_check_mesh(case_root: Path, timeout: int | None = None) -> OperationResult:
    return _fake_result("check_mesh", case_root / "logs" / "checkMesh.log", GOOD_CHECK_MESH_LOG)


# Exits 0, all required fields present, residuals decreasing across (at
# least) two iterations so residual_trend resolves to "decreasing" -- but
# never prints "SIMPLE solution converged", simulating a run that hit
# endTime without meeting its residual targets (the exact failure
# Milestone 6 injects and recovers from via the time_control action).
BAD_SOLVER_LOG = """
Time = 1s
smoothSolver:  Solving for Ux, Initial residual = 0.2, Final residual = 0.1, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.2, Final residual = 0.1, No Iterations 5
GAMG:  Solving for p, Initial residual = 0.2, Final residual = 0.1, No Iterations 3
smoothSolver:  Solving for epsilon, Initial residual = 0.2, Final residual = 0.1, No Iterations 3
smoothSolver:  Solving for k, Initial residual = 0.2, Final residual = 0.1, No Iterations 4

Time = 2s
smoothSolver:  Solving for Ux, Initial residual = 0.1, Final residual = 0.04, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.1, Final residual = 0.04, No Iterations 5
GAMG:  Solving for p, Initial residual = 0.1, Final residual = 0.04, No Iterations 3
smoothSolver:  Solving for epsilon, Initial residual = 0.1, Final residual = 0.04, No Iterations 3
smoothSolver:  Solving for k, Initial residual = 0.1, Final residual = 0.04, No Iterations 4

End
"""


def fake_run_solver(case_root: Path, timeout: int | None = None) -> OperationResult:
    return _fake_result("solve", case_root / "logs" / "solver.log", GOOD_SOLVER_LOG)


def make_failing_then_succeeding_solver(fail_times: int):
    """Returns a fake run_solver that produces BAD_SOLVER_LOG for the first
    `fail_times` calls, then GOOD_SOLVER_LOG -- for testing the bounded
    retry loop without Docker. `.calls` exposes the call count for
    assertions."""
    calls = {"n": 0}

    def fake(case_root: Path, timeout: int | None = None) -> OperationResult:
        calls["n"] += 1
        log_text = BAD_SOLVER_LOG if calls["n"] <= fail_times else GOOD_SOLVER_LOG
        return _fake_result("solve", case_root / "logs" / "solver.log", log_text)

    fake.calls = calls
    return fake


def always_failing_solver(case_root: Path, timeout: int | None = None) -> OperationResult:
    return _fake_result("solve", case_root / "logs" / "solver.log", BAD_SOLVER_LOG)


def fake_run_postprocess(case_root: Path, timeout: int | None = None) -> OperationResult:
    case_dir = case_root / "case"

    def write(func: str, time: str, header: str, row: str, filename: str) -> None:
        d = case_dir / "postProcessing" / func / time
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(f"# header\n{header}\n{row}\n")

    write("patchFlowRate(patch=inlet)", "2", "# Time\tsum(phi)", "2\t-2.5e-04", "surfaceFieldValue.dat")
    write("patchFlowRate(patch=outlet)", "2", "# Time\tsum(phi)", "2\t2.5e-04", "surfaceFieldValue.dat")
    write(
        "patchAverage(patch=inlet,fields=(p))", "2", "# Time\tareaAverage(p)", "2\t-6.0",
        "surfaceFieldValue.dat",
    )
    write(
        "patchAverage(patch=outlet,fields=(p))", "2", "# Time\tareaAverage(p)", "2\t0.0",
        "surfaceFieldValue.dat",
    )
    write("cellMaxMag(U)", "2", "# Time\tmaxMag(U)", "2\t10.0", "volFieldValue.dat")
    write("volAverage(U)", "2", "# Time\tvolAverage(U)", "2\t(5.0 -0.2 0.0)", "volFieldValue.dat")
    return _fake_result("postprocess", case_root / "logs" / "postprocess.log", "postProcess ... End\n")


def make_qoi_postprocess(values_by_case: dict[str, dict] | None = None, default_inlet_p: float = -6.0):
    """Returns a fake run_postprocess that varies QoI values by case_id
    (case_root.name) -- for tests that need distinguishable per-case data
    (mesh independence PASS/FAIL, velocity sweep plotting), unlike
    fake_run_postprocess's fixed numbers. `values_by_case[case_id]` may set
    `inlet_p` (areaAverage(p) at inlet; outlet stays 0.0, so this *is* the
    resulting pressure_drop) and/or `max_u`."""
    values_by_case = values_by_case or {}

    def fake(case_root: Path, timeout: int | None = None) -> OperationResult:
        case_id = case_root.name
        overrides = values_by_case.get(case_id, {})
        inlet_p = overrides.get("inlet_p", default_inlet_p)
        max_u = overrides.get("max_u", 10.0)
        case_dir = case_root / "case"

        def write(func: str, time: str, header: str, row: str, filename: str) -> None:
            d = case_dir / "postProcessing" / func / time
            d.mkdir(parents=True, exist_ok=True)
            (d / filename).write_text(f"# header\n{header}\n{row}\n")

        write("patchFlowRate(patch=inlet)", "2", "# Time\tsum(phi)", "2\t-2.5e-04", "surfaceFieldValue.dat")
        write("patchFlowRate(patch=outlet)", "2", "# Time\tsum(phi)", "2\t2.5e-04", "surfaceFieldValue.dat")
        write(
            "patchAverage(patch=inlet,fields=(p))", "2", "# Time\tareaAverage(p)", f"2\t{inlet_p}",
            "surfaceFieldValue.dat",
        )
        write(
            "patchAverage(patch=outlet,fields=(p))", "2", "# Time\tareaAverage(p)", "2\t0.0",
            "surfaceFieldValue.dat",
        )
        write("cellMaxMag(U)", "2", "# Time\tmaxMag(U)", f"2\t{max_u}", "volFieldValue.dat")
        write("volAverage(U)", "2", "# Time\tvolAverage(U)", "2\t(5.0 -0.2 0.0)", "volFieldValue.dat")
        return _fake_result("postprocess", case_root / "logs" / "postprocess.log", "postProcess ... End\n")

    return fake


def install(monkeypatch) -> None:
    import app.graph as graph_mod
    from app.agents.diagnostic import mock_diagnose_solver_failure
    from app.agents.planner import mock_plan_study
    from app.agents.reviewer import build_evidence_bundle, mock_review_results
    from app.tools import openfoam_tools

    monkeypatch.setattr(openfoam_tools, "run_mesh", fake_run_mesh)
    monkeypatch.setattr(openfoam_tools, "check_mesh", fake_check_mesh)
    monkeypatch.setattr(openfoam_tools, "run_solver", fake_run_solver)
    monkeypatch.setattr(openfoam_tools, "run_postprocess", fake_run_postprocess)
    # Milestones 5/6/9 wire the real Bedrock planner/diagnostic/review agents
    # into the graph; tests stay hermetic (no network) by swapping in mocks.
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", mock_plan_study)
    monkeypatch.setattr(
        graph_mod, "bedrock_diagnose_solver_failure",
        lambda evidence, case_id, attempt=1, max_retries=2, llm=None: mock_diagnose_solver_failure(
            evidence, attempt
        ),
    )
    monkeypatch.setattr(
        graph_mod, "bedrock_review_results",
        lambda run_id, llm=None: mock_review_results(build_evidence_bundle(run_id)),
    )
