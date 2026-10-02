"""Milestone 6: DiagnosticFix schema/policy bounds, apply_diagnostic_fix
rewrite correctness, and the mock diagnostic agent's triage logic. No
docker, no LLM."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import config
from app.agents.diagnostic import mock_diagnose_solver_failure
from app.policy import check_diagnostic_fix
from app.schemas import DiagnosticFix
from app.tools import case_tools


@pytest.fixture(autouse=True)
def isolated_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    config.RUNS_DIR.mkdir()
    yield


# ---------------------------------------------------------------------
# Schema bounds (reject before anything ever touches a case directory)
# ---------------------------------------------------------------------

def test_diagnostic_fix_rejects_unknown_action_type():
    with pytest.raises(ValidationError):
        DiagnosticFix(action_type="change_turbulence_model", value=1.0, reason="x")  # type: ignore[arg-type]


def test_diagnostic_fix_rejects_out_of_range_relaxation():
    with pytest.raises(ValidationError):
        DiagnosticFix(action_type="relaxation", value=1.5, reason="x")


def test_diagnostic_fix_rejects_out_of_range_time_control():
    with pytest.raises(ValidationError):
        DiagnosticFix(action_type="time_control", value=100.0, reason="x")  # below min 2000


def test_diagnostic_fix_rejects_unknown_field():
    with pytest.raises(ValidationError):
        DiagnosticFix(
            action_type="relaxation", value=0.5, reason="x", turbulence_model="kOmegaSST"
        )  # type: ignore[call-arg]


def test_diagnostic_fix_accepts_valid_values():
    fix = DiagnosticFix(action_type="relaxation", value=0.6, reason="more stable")
    assert fix.value == 0.6


# ---------------------------------------------------------------------
# Independent policy check (app.policy.check_diagnostic_fix)
# ---------------------------------------------------------------------

def test_check_diagnostic_fix_passes_valid_fix():
    fix = DiagnosticFix(action_type="time_control", value=4000, reason="needs more iterations")
    result = check_diagnostic_fix(fix)
    assert result.status == "PASSED"


def test_check_diagnostic_fix_passes_numerical_solver_setting_at_bound():
    fix = DiagnosticFix(action_type="numerical_solver_setting", value=3, reason="more correctors")
    assert check_diagnostic_fix(fix).status == "PASSED"


# ---------------------------------------------------------------------
# apply_diagnostic_fix rewrite correctness -- pure filesystem, no docker
# ---------------------------------------------------------------------

def _prepared_case():
    return case_tools.prepare_case("run1", "baseline", {})


def test_apply_diagnostic_fix_relaxation_rewrites_both_entries_preserving_comments():
    case_root = _prepared_case()
    fix = DiagnosticFix(action_type="relaxation", value=0.5, reason="stability")
    case_tools.apply_diagnostic_fix(case_root, fix)

    text = (case_root / "case" / "system" / "fvSolution").read_text()
    assert "U               0.5;" in text
    assert '".*"            0.5;' in text
    assert "// 0.9 is more stable" in text  # comment preserved


def test_apply_diagnostic_fix_numerical_solver_setting_rewrites_correctors():
    case_root = _prepared_case()
    fix = DiagnosticFix(action_type="numerical_solver_setting", value=2, reason="non-orthogonal mesh")
    case_tools.apply_diagnostic_fix(case_root, fix)

    text = (case_root / "case" / "system" / "fvSolution").read_text()
    assert "nNonOrthogonalCorrectors 2;" in text


def test_apply_diagnostic_fix_time_control_rewrites_end_time():
    case_root = _prepared_case()
    fix = DiagnosticFix(action_type="time_control", value=4500, reason="needs more iterations")
    case_tools.apply_diagnostic_fix(case_root, fix)

    text = (case_root / "case" / "system" / "controlDict").read_text()
    assert "endTime         4500;" in text


def test_apply_diagnostic_fix_never_touches_geometry_or_physics_files():
    case_root = _prepared_case()
    case_dir = case_root / "case"
    before = {
        p: (case_dir / p).read_text()
        for p in ("system/blockMeshDict", "0/U", "0/p", "constant/physicalProperties", "constant/momentumTransport")
    }
    fix = DiagnosticFix(action_type="relaxation", value=0.4, reason="stability")
    case_tools.apply_diagnostic_fix(case_root, fix)
    after = {p: (case_dir / p).read_text() for p in before}
    assert before == after


def test_apply_diagnostic_fix_rejects_path_outside_runs_dir(tmp_path):
    outside = tmp_path / "not_under_runs"
    outside.mkdir()
    fix = DiagnosticFix(action_type="relaxation", value=0.5, reason="x")
    with pytest.raises(ValueError):
        case_tools.apply_diagnostic_fix(outside, fix)


# ---------------------------------------------------------------------
# Mock diagnostic agent triage logic
# ---------------------------------------------------------------------

def test_mock_diagnose_proposes_time_control_when_out_of_time_but_decreasing():
    evidence = {
        "converged": False, "last_time": 500, "residual_trend": "decreasing",
        "fatal_error": False, "final_residuals": {}, "reasons": ["did not converge"],
    }
    fix = mock_diagnose_solver_failure(evidence)
    assert fix.action_type == "time_control"
    assert fix.value > 500


def test_mock_diagnose_proposes_relaxation_on_increasing_trend():
    evidence = {
        "converged": False, "last_time": 50, "residual_trend": "increasing",
        "fatal_error": False, "final_residuals": {}, "reasons": ["residual trend is increasing"],
    }
    fix = mock_diagnose_solver_failure(evidence)
    assert fix.action_type == "relaxation"


def test_mock_diagnose_proposes_relaxation_on_fatal_error():
    evidence = {
        "converged": False, "last_time": None, "residual_trend": "unknown",
        "fatal_error": True, "final_residuals": {}, "reasons": ["FOAM FATAL ERROR"],
    }
    fix = mock_diagnose_solver_failure(evidence)
    assert fix.action_type == "relaxation"


def test_mock_diagnose_proposal_always_passes_policy():
    for evidence in [
        {"converged": False, "last_time": 100, "residual_trend": "decreasing", "fatal_error": False,
         "final_residuals": {}, "reasons": []},
        {"converged": False, "last_time": None, "residual_trend": "unknown", "fatal_error": True,
         "final_residuals": {}, "reasons": []},
        {"converged": False, "last_time": 2000, "residual_trend": "stagnant", "fatal_error": False,
         "final_residuals": {}, "reasons": []},
    ]:
        fix = mock_diagnose_solver_failure(evidence)
        assert check_diagnostic_fix(fix).status == "PASSED"
