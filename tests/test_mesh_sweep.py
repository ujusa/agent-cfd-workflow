"""Milestones 7-8: mesh independence gate and parameter sweep, wired into
the real graph. Docker-heavy tool calls are faked (tests/fake_tools.py);
graph wiring, routing, artifact contracts, and plot generation are real.
"""
from __future__ import annotations

import json

import pytest

from app import checkpoint, config
from app import state as state_mod
from app.graph import build_graph
from app.schemas import CaseSpec, StudyPlan
from tests.fake_tools import install as install_fake_tools
from tests.fake_tools import make_qoi_postprocess


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    config.RUNS_DIR.mkdir()
    yield


def _plan_with(cases: list[CaseSpec], mesh_levels: list[str]) -> StudyPlan:
    return StudyPlan(
        objective="sweep test",
        baseline_case="backward_facing_step",
        cases=cases,
        mesh_levels=mesh_levels,
        qois=["pressure_drop"],
        permitted_parameters=["inlet_velocity", "mesh_level"],
        assumptions=[],
        validation_plan=["case_integrity", "mesh_quality", "solver_health", "conservation"],
        requires_human_approval=True,
    )


def _run_until_complete_or_blocked(graph, run_id, goal="goal"):
    cfg = checkpoint.thread_config(run_id)
    graph.invoke(state_mod.initial_state(run_id, goal), cfg)
    graph.update_state(cfg, {"approval_status": {"approved": True, "approved_by": "test"}})
    return graph.invoke(None, cfg)


def test_mesh_independence_passes_and_sweep_runs_with_plot(tmp_path, monkeypatch):
    install_fake_tools(monkeypatch)
    import app.graph as graph_mod
    from app.tools import openfoam_tools

    # Nearly identical pressure_drop across mesh levels -> small relative
    # change -> PASSED. Distinct, increasing pressure_drop across the
    # velocity sweep so the plot has real data to draw.
    monkeypatch.setattr(openfoam_tools, "run_postprocess", make_qoi_postprocess({
        "baseline": {"inlet_p": -6.0},
        "baseline_coarse": {"inlet_p": -5.9},
        "baseline_fine": {"inlet_p": -6.05},
        "case_15ms": {"inlet_p": -9.0},
        "case_20ms": {"inlet_p": -12.0},
    }))

    plan = _plan_with(
        cases=[
            CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium"),
            CaseSpec(case_id="case_15ms", inlet_velocity=15.0, mesh_level="medium"),
            CaseSpec(case_id="case_20ms", inlet_velocity=20.0, mesh_level="medium"),
        ],
        mesh_levels=["coarse", "medium", "fine"],
    )
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", lambda goal: plan)

    graph = build_graph(checkpoint.build_checkpointer(tmp_path / "checkpoints.sqlite"))
    final = _run_until_complete_or_blocked(graph, "sweep_pass")

    assert final["current_stage"] == "completed"
    assert final["validation_results"]["_mesh_independence"]["status"] == "PASSED"

    run_dir = config.RUNS_DIR / "sweep_pass"
    for name in ("mesh_refinement.json", "mesh_independence.json", "sweep_cases.json", "sweep_results.json"):
        assert (run_dir / name).is_file(), f"missing artifact: {name}"

    sweep_results = json.loads((run_dir / "sweep_results.json").read_text())
    case_ids = {row["case_id"] for row in sweep_results["cases"]}
    assert case_ids == {"baseline", "baseline_coarse", "baseline_fine", "case_15ms", "case_20ms"}

    plot_path = run_dir / "plots" / "qoi_vs_velocity.png"
    assert plot_path.is_file()
    assert plot_path.stat().st_size > 0

    agents = [d["agent"] for d in final["agent_decisions"]]
    assert "mesh_refinement" in agents
    assert "mesh_independence_gate" in agents
    assert "parameter_sweep" in agents
    assert "cross_case_analysis" in agents


def test_mesh_independence_fails_on_large_relative_change_and_skips_sweep(tmp_path, monkeypatch):
    install_fake_tools(monkeypatch)
    import app.graph as graph_mod
    from app.tools import openfoam_tools

    # medium vs fine pressure_drop differs by far more than the 5% threshold.
    monkeypatch.setattr(openfoam_tools, "run_postprocess", make_qoi_postprocess({
        "baseline": {"inlet_p": -6.0},
        "baseline_coarse": {"inlet_p": -6.0},
        "baseline_fine": {"inlet_p": -20.0},
        "case_15ms": {"inlet_p": -9.0},
    }))

    plan = _plan_with(
        cases=[
            CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium"),
            CaseSpec(case_id="case_15ms", inlet_velocity=15.0, mesh_level="medium"),
        ],
        mesh_levels=["coarse", "medium", "fine"],
    )
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", lambda goal: plan)

    graph = build_graph(checkpoint.build_checkpointer(tmp_path / "checkpoints.sqlite"))
    final = _run_until_complete_or_blocked(graph, "sweep_fail")

    assert final["current_stage"] == "mesh_independence_gate"
    assert final["validation_results"]["_mesh_independence"]["status"] == "FAILED"
    assert any("mesh_independence_gate FAILED" in e for e in final["errors"])

    run_dir = config.RUNS_DIR / "sweep_fail"
    assert (run_dir / "mesh_independence.json").is_file()
    # refused to continue: the parameter sweep must never have run.
    assert not (run_dir / "sweep_cases.json").exists()
    assert not (run_dir / "sweep_results.json").exists()
    assert "case_15ms" not in (final.get("qoi_results") or {})


def test_policy_rejects_plan_with_insufficient_mesh_levels(tmp_path, monkeypatch):
    """Mesh independence is required scope (plan section 3 item 10), not
    optional -- a plan that doesn't request at least medium+fine is
    rejected at policy_check, before anything runs (not discovered late
    and wastefully at mesh_independence_gate)."""
    install_fake_tools(monkeypatch)
    import app.graph as graph_mod

    plan = _plan_with(
        cases=[CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium")],
        mesh_levels=["medium"],
    )
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", lambda goal: plan)

    graph = build_graph(checkpoint.build_checkpointer(tmp_path / "checkpoints.sqlite"))
    cfg = checkpoint.thread_config("policy_rejects_mesh_levels")
    final = graph.invoke(state_mod.initial_state("policy_rejects_mesh_levels", "goal"), cfg)

    assert final["current_stage"] == "policy_check"
    assert any("mesh_levels must include" in e for e in final["errors"])
    # Never reached the approval gate -- no case ever prepared.
    assert final.get("approval_status") is None


def test_mesh_independence_blocked_when_fine_mesh_case_fails_to_converge(tmp_path, monkeypatch):
    """Real finding (see conversation record): a plan can correctly request
    coarse/medium/fine, and the fine-mesh case can still genuinely fail to
    converge within the iteration budget (e.g. a persistent residual
    plateau near a sharp geometric feature) -- this must BLOCK the
    independence claim and refuse the sweep, not silently skip the level."""
    install_fake_tools(monkeypatch)
    import app.graph as graph_mod
    from tests.fake_tools import BAD_SOLVER_LOG, GOOD_SOLVER_LOG, _fake_result
    from app.tools import openfoam_tools

    plan = _plan_with(
        cases=[CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium")],
        mesh_levels=["coarse", "medium", "fine"],
    )
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", lambda goal: plan)

    def solver_that_fails_fine_mesh(case_root, timeout=None):
        log = BAD_SOLVER_LOG if case_root.name == "baseline_fine" else GOOD_SOLVER_LOG
        return _fake_result("solve", case_root / "logs" / "solver.log", log)

    monkeypatch.setattr(openfoam_tools, "run_solver", solver_that_fails_fine_mesh)

    graph = build_graph(checkpoint.build_checkpointer(tmp_path / "checkpoints.sqlite"))
    final = _run_until_complete_or_blocked(graph, "sweep_blocked")

    assert final["current_stage"] == "mesh_independence_gate"
    assert final["validation_results"]["baseline_fine:solver_health"]["status"] == "FAILED"
    assert "baseline_fine" not in final["qoi_results"]
    decision = [d for d in final["agent_decisions"] if d["agent"] == "mesh_independence_gate"][0]
    assert decision["policy_check"] == "BLOCKED"

    run_dir = config.RUNS_DIR / "sweep_blocked"
    mesh_independence = json.loads((run_dir / "mesh_independence.json").read_text())
    assert mesh_independence["status"] == "BLOCKED"
    assert not (run_dir / "sweep_results.json").exists()


def test_run_parameter_cases_isolates_a_failing_sweep_case(tmp_path, monkeypatch):
    """One sweep case's solver failure must not prevent the others from
    running (or crash the graph), and cross_case_analysis must still
    aggregate whatever QoIs were successfully extracted."""
    install_fake_tools(monkeypatch)
    import app.graph as graph_mod
    from tests.fake_tools import BAD_SOLVER_LOG, GOOD_SOLVER_LOG, _fake_result
    from app.tools import openfoam_tools

    plan = _plan_with(
        cases=[
            CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium"),
            CaseSpec(case_id="case_bad", inlet_velocity=15.0, mesh_level="medium"),
            CaseSpec(case_id="case_good", inlet_velocity=20.0, mesh_level="medium"),
        ],
        mesh_levels=["coarse", "medium", "fine"],  # let mesh independence PASS so the sweep runs
    )
    monkeypatch.setattr(graph_mod, "bedrock_plan_study", lambda goal: plan)

    def solver_that_fails_one_case(case_root, timeout=None):
        log = BAD_SOLVER_LOG if case_root.name == "case_bad" else GOOD_SOLVER_LOG
        return _fake_result("solve", case_root / "logs" / "solver.log", log)

    monkeypatch.setattr(openfoam_tools, "run_solver", solver_that_fails_one_case)

    graph = build_graph(checkpoint.build_checkpointer(tmp_path / "checkpoints.sqlite"))
    final = _run_until_complete_or_blocked(graph, "sweep_isolation")

    assert final["current_stage"] == "completed"
    assert final["validation_results"]["_mesh_independence"]["status"] == "PASSED"
    assert final["validation_results"]["case_bad:solver_health"]["status"] == "FAILED"
    assert final["validation_results"]["case_good:solver_health"]["status"] == "PASSED"
    assert "case_bad" not in final["qoi_results"]  # never reached QoI extraction
    assert final["qoi_results"]["case_good"]["complete"] is True

    sweep_cases = json.loads(
        (config.RUNS_DIR / "sweep_isolation" / "sweep_cases.json").read_text()
    )["results"]
    by_id = {r["case_id"]: r for r in sweep_cases}
    assert by_id["case_bad"]["success"] is False
    assert by_id["case_bad"]["stage_reached"] == "solver_health"
    assert by_id["case_good"]["success"] is True

    # cross_case_analysis still aggregated everyone it had QoIs for.
    sweep_results = json.loads(
        (config.RUNS_DIR / "sweep_isolation" / "sweep_results.json").read_text()
    )["cases"]
    assert {r["case_id"] for r in sweep_results} == {
        "baseline", "baseline_coarse", "baseline_fine", "case_good",
    }


def test_run_case_pipeline_isolation_via_direct_call(tmp_path, monkeypatch):
    """Direct unit-level proof that one case's solver failure doesn't raise
    or corrupt state for a second, independently-run case."""
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    config.RUNS_DIR.mkdir(exist_ok=True)
    import app.case_pipeline as cp
    from tests.fake_tools import BAD_SOLVER_LOG, GOOD_SOLVER_LOG, _fake_result, fake_run_mesh, fake_check_mesh, fake_run_postprocess
    from app.tools import openfoam_tools

    monkeypatch.setattr(openfoam_tools, "run_mesh", fake_run_mesh)
    monkeypatch.setattr(openfoam_tools, "check_mesh", fake_check_mesh)
    monkeypatch.setattr(openfoam_tools, "run_postprocess", fake_run_postprocess)

    def solver_that_fails_one_case(case_root, timeout=None):
        log = BAD_SOLVER_LOG if case_root.name == "bad" else GOOD_SOLVER_LOG
        return _fake_result("solve", case_root / "logs" / "solver.log", log)

    monkeypatch.setattr(openfoam_tools, "run_solver", solver_that_fails_one_case)

    bad_result = cp.run_case_pipeline("run1", "bad", {"inlet_velocity": 10.0, "mesh_level": "medium"})
    good_result = cp.run_case_pipeline("run1", "good", {"inlet_velocity": 15.0, "mesh_level": "medium"})

    assert bad_result["success"] is False
    assert bad_result["stage_reached"] == "solver_health"
    assert bad_result["solver_health"]["status"] == "FAILED"

    assert good_result["success"] is True
    assert good_result["qoi"]["complete"] is True
