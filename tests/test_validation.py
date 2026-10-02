"""Milestone 2: synthetic-data coverage for every deterministic validation
gate -- pass, fail, invalid input, NaN/Inf, zero denominators. No docker,
no LLM; see app/validation/*.py."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.validation import conservation, convergence, mesh_independence, qoi

# ---------------------------------------------------------------------
# Gate A: case integrity
# ---------------------------------------------------------------------

def test_case_integrity_passes_when_all_required_files_present(tmp_path):
    for rel in convergence.REQUIRED_CASE_FILES:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    result = convergence.check_case_integrity(tmp_path)
    assert result.status == "PASSED"
    assert result.missing == []


def test_case_integrity_fails_when_files_missing(tmp_path):
    result = convergence.check_case_integrity(tmp_path)
    assert result.status == "FAILED"
    assert set(result.missing) == set(convergence.REQUIRED_CASE_FILES)


# ---------------------------------------------------------------------
# Gate C: solver health / convergence
# ---------------------------------------------------------------------

def _solver_log(
    *,
    fields=("Ux", "Uy", "p", "k", "epsilon"),
    n_iterations=3,
    start=0.1,
    factor=0.1,
    fatal=False,
    converged_line=True,
    final_override: dict[str, str] | None = None,
) -> str:
    lines = []
    for i in range(n_iterations):
        lines.append(f"Time = {i + 1}s")
        for field in fields:
            val = start * (factor ** i)
            final_str = f"{val:.6g}"
            if final_override and field in final_override and i == n_iterations - 1:
                final_str = final_override[field]
            lines.append(
                f"smoothSolver:  Solving for {field}, Initial residual = {val * 10:.6g}, "
                f"Final residual = {final_str}, No Iterations 5"
            )
    if fatal:
        lines.append("\n\n*** FOAM FATAL ERROR ***\nsomething broke\n")
    if converged_line:
        lines.append(f"\nSIMPLE solution converged in {n_iterations} iterations\n")
    lines.append("End")
    return "\n".join(lines)


def test_solver_health_passes_on_clean_converged_log():
    log = _solver_log()
    result = convergence.check_solver_health(log, return_code=0)
    assert result.status == "PASSED"
    assert result.converged is True
    assert result.fatal_error is False
    assert result.missing_residual_fields == []
    assert result.residual_trend == "decreasing"


def test_solver_health_fails_on_nonzero_return_code():
    result = convergence.check_solver_health(_solver_log(), return_code=1)
    assert result.status == "FAILED"
    assert any("return_code=1" in r for r in result.reasons)


def test_solver_health_fails_on_fatal_error():
    result = convergence.check_solver_health(_solver_log(fatal=True), return_code=1)
    assert result.status == "FAILED"
    assert result.fatal_error is True


def test_solver_health_fails_on_missing_required_field():
    log = _solver_log(fields=("Ux", "Uy", "p"))  # k, epsilon missing
    result = convergence.check_solver_health(log, return_code=0)
    assert result.status == "FAILED"
    assert "k" in result.missing_residual_fields
    assert "epsilon" in result.missing_residual_fields


def test_solver_health_fails_on_non_finite_final_residual():
    log = _solver_log(final_override={"p": "nan"})
    result = convergence.check_solver_health(log, return_code=0)
    assert result.status == "FAILED"
    assert math.isnan(result.final_residuals["p"])
    assert any("non-finite" in r for r in result.reasons)


def test_solver_health_flags_increasing_residual_trend():
    log = _solver_log(start=0.001, factor=10.0)  # grows each iteration
    result = convergence.check_solver_health(log, return_code=0)
    assert result.residual_trend == "increasing"
    assert result.status == "FAILED"


def test_solver_health_fails_when_endtime_reached_without_converging():
    """A run that hits endTime without meeting residualControl exits 0 and
    looks clean (no fatal error, all fields present, residuals still
    decreasing) but never printed the convergence line -- this must FAIL,
    not be mistaken for success."""
    log = _solver_log(converged_line=False)
    result = convergence.check_solver_health(log, return_code=0)
    assert result.status == "FAILED"
    assert result.converged is False
    assert result.iterations is None
    assert any("did not report convergence" in r for r in result.reasons)


def test_solver_health_unknown_trend_with_insufficient_data():
    log = _solver_log(n_iterations=1)
    result = convergence.check_solver_health(log, return_code=0)
    assert result.residual_trend == "unknown"


# ---------------------------------------------------------------------
# Gate D: conservation
# ---------------------------------------------------------------------

def test_conservation_passes_within_threshold():
    result = conservation.check_conservation(1.0, 1.001, threshold=0.02)
    assert result.status == "PASSED"


def test_conservation_fails_outside_threshold():
    result = conservation.check_conservation(1.0, 1.5, threshold=0.02)
    assert result.status == "FAILED"
    assert "exceeds threshold" in result.reasons[0]


def test_conservation_fails_on_nan_input():
    result = conservation.check_conservation(float("nan"), 1.0, threshold=0.02)
    assert result.status == "FAILED"
    assert "non-finite" in result.reasons[0]


def test_conservation_zero_denominator_uses_epsilon_without_crashing():
    result = conservation.check_conservation(0.0, 0.0, threshold=0.02, epsilon=1e-9)
    assert result.imbalance == 0.0
    assert result.status == "PASSED"


def test_conservation_zero_mass_in_nonzero_mass_out_is_bounded_not_infinite():
    result = conservation.check_conservation(0.0, 5.0, threshold=0.02, epsilon=1e-9)
    assert math.isfinite(result.imbalance)
    assert result.status == "FAILED"


# ---------------------------------------------------------------------
# Gate B: mesh quality
# ---------------------------------------------------------------------

_GOOD_CHECK_MESH_LOG = """
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

_BAD_CHECK_MESH_LOG = """
Mesh stats
    points:           100
    faces:            500
    internal faces:   200
    cells:            150
    boundary patches: 5

Checking geometry...
    Mesh non-orthogonality Max: 88.0 average: 40.0
    Max skewness = 12.5 OK.
    ***Zero or negative cell volume detected. Number of negative-volume cells = 3

Failed 2 mesh checks.

End
"""


def test_mesh_quality_passes_on_clean_log():
    result = mesh_independence.check_mesh_quality(_GOOD_CHECK_MESH_LOG, return_code=0)
    assert result.status == "PASSED"
    assert result.cells == 3093
    assert result.faces == 12512
    assert result.boundary_faces == 12512 - 6046
    assert result.negative_volume_cells == 0


def test_mesh_quality_fails_on_bad_metrics():
    result = mesh_independence.check_mesh_quality(_BAD_CHECK_MESH_LOG, return_code=0)
    assert result.status == "FAILED"
    assert result.negative_volume_cells == 3
    assert any("skewness" in r for r in result.reasons)
    assert any("non-orthogonality" in r for r in result.reasons)


def test_mesh_quality_fails_on_nonzero_return_code():
    result = mesh_independence.check_mesh_quality(_GOOD_CHECK_MESH_LOG, return_code=1)
    assert result.status == "FAILED"


# ---------------------------------------------------------------------
# Gate E: mesh independence
# ---------------------------------------------------------------------

def test_mesh_independence_passes_for_small_relative_change():
    qois = {
        "medium": {"pressure_drop": 10.0, "maximum_velocity": 5.0, "average_velocity": 2.0},
        "fine": {"pressure_drop": 10.2, "maximum_velocity": 5.05, "average_velocity": 2.01},
    }
    result = mesh_independence.assess_mesh_independence(qois, threshold=0.05)
    assert result.status == "PASSED"
    assert all(v <= 0.05 for v in result.relative_changes.values())


def test_mesh_independence_fails_for_large_relative_change():
    qois = {
        "medium": {"pressure_drop": 10.0, "maximum_velocity": 5.0, "average_velocity": 2.0},
        "fine": {"pressure_drop": 15.0, "maximum_velocity": 5.0, "average_velocity": 2.0},
    }
    result = mesh_independence.assess_mesh_independence(qois, threshold=0.05)
    assert result.status == "FAILED"
    assert "pressure_drop" in " ".join(result.reasons)


def test_mesh_independence_raises_on_missing_level():
    with pytest.raises(ValueError):
        mesh_independence.assess_mesh_independence({"medium": {"pressure_drop": 1.0}})


def test_mesh_independence_handles_nan_qoi_without_crashing():
    qois = {
        "medium": {"pressure_drop": float("nan"), "maximum_velocity": 5.0, "average_velocity": 2.0},
        "fine": {"pressure_drop": 10.0, "maximum_velocity": 5.0, "average_velocity": 2.0},
    }
    result = mesh_independence.assess_mesh_independence(qois, threshold=0.05)
    assert result.status == "FAILED"
    assert any("non-finite" in r for r in result.reasons)


def test_compute_relative_change_zero_denominator_uses_epsilon():
    rc = mesh_independence.compute_relative_change(0.0, 0.0, epsilon=1e-9)
    assert rc == 0.0
    rc2 = mesh_independence.compute_relative_change(0.0, 3.0, epsilon=1e-9)
    assert math.isfinite(rc2)


# ---------------------------------------------------------------------
# QoI extraction
# ---------------------------------------------------------------------

def _write_dat(case_dir: Path, func_name: str, time: str, header: str, row: str) -> None:
    out_dir = case_dir / "postProcessing" / func_name / time
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = "surfaceFieldValue.dat" if "patch" in func_name else "volFieldValue.dat"
    (out_dir / filename).write_text(f"# header\n{header}\n{row}\n")


def _fake_solved_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    _write_dat(case_dir, "patchFlowRate(patch=inlet)", "166", "# Time\tsum(phi)", "166\t-2.540001e-04")
    _write_dat(case_dir, "patchFlowRate(patch=outlet)", "166", "# Time\tsum(phi)", "166\t2.539940e-04")
    _write_dat(
        case_dir, "patchAverage(patch=inlet,fields=(p))", "166",
        "# Time\tareaAverage(p)", "166\t-6.141052e+00",
    )
    _write_dat(
        case_dir, "patchAverage(patch=outlet,fields=(p))", "166",
        "# Time\tareaAverage(p)", "166\t0.000000e+00",
    )
    _write_dat(case_dir, "cellMaxMag(U)", "166", "# Time\tmaxMag(U)", "166\t1.024690e+01")
    _write_dat(
        case_dir, "volAverage(U)", "166", "# Time\tvolAverage(U)",
        "166\t(5.436779e+00 -2.075546e-01 -2.848337e-19)",
    )
    return case_dir


def test_extract_qoi_parses_all_values_from_real_format(tmp_path):
    case_dir = _fake_solved_case(tmp_path)
    result = qoi.extract_qoi(case_dir, case_id="baseline")
    assert result.complete is True
    assert result.errors == []
    assert result.latest_time == "166"
    assert result.mass_flow_in == pytest.approx(2.540001e-04)
    assert result.mass_flow_out == pytest.approx(2.539940e-04)
    assert result.mass_imbalance == pytest.approx(
        abs(2.540001e-04 - 2.539940e-04) / 2.540001e-04, rel=1e-3
    )
    assert result.pressure_drop == pytest.approx(-6.141052)
    assert result.maximum_velocity == pytest.approx(10.2469)
    assert result.average_velocity == pytest.approx((5.436779**2 + 0.2075546**2) ** 0.5, rel=1e-4)


def test_extract_qoi_records_errors_but_computes_remaining_values(tmp_path):
    case_dir = tmp_path / "case"
    # Only write the inlet/outlet flow rate and pressure files -- omit U files.
    _write_dat(case_dir, "patchFlowRate(patch=inlet)", "10", "# Time\tsum(phi)", "10\t-1.0e-04")
    _write_dat(case_dir, "patchFlowRate(patch=outlet)", "10", "# Time\tsum(phi)", "10\t1.0e-04")
    result = qoi.extract_qoi(case_dir)
    assert result.complete is False
    assert len(result.errors) == 4  # inlet p, outlet p, max U, avg U all missing
    assert result.mass_flow_in == pytest.approx(1.0e-04)
    assert result.pressure_drop is None
    assert result.maximum_velocity is None
