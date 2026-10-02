"""Post-processing: extract the fixed, small QoI set (plan section 20) from
the .dat files written by the 'postprocess' operation
(app.tools.openfoam_tools.run_postprocess / POSTPROCESS_FUNCTIONS).

mass_flow_in/out are volumetric flow rates (m^3/s): this is a
constant-density incompressible solver, so volumetric and mass flow are
proportional and the imbalance ratio used by Gate D is unaffected -- this
assumption is recorded in the result so a reviewer can check it.

recirculation_length is intentionally omitted: plan section 20 only requires
it "if robustly defined," and a robust definition (zero-crossing of wall
shear stress along lowerWall) is out of scope for this milestone.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from pydantic import BaseModel

_TOKEN_RE = re.compile(r"\([^)]*\)|\S+")


class QoIResult(BaseModel):
    case_id: str | None = None
    latest_time: str | None = None
    pressure_drop: float | None = None
    mass_flow_in: float | None = None
    mass_flow_out: float | None = None
    mass_imbalance: float | None = None
    maximum_velocity: float | None = None
    average_velocity: float | None = None
    complete: bool
    errors: list[str]
    evidence: list[str]
    assumptions: list[str] = [
        "mass_flow_in/out are volumetric flow rates (m^3/s); density is "
        "treated as constant, so this does not affect the Gate D imbalance ratio.",
    ]


def _parse_last_data_row(path: Path) -> list[str]:
    lines = [
        line for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"no data rows in {path}")
    return _TOKEN_RE.findall(lines[-1].strip())


def _vector_magnitude(token: str) -> float:
    parts = token.strip("()").split()
    if len(parts) != 3:
        raise ValueError(f"expected a 3-component vector token, got {token!r}")
    x, y, z = (float(p) for p in parts)
    return (x * x + y * y + z * z) ** 0.5


def _read_function_output(case_dir: Path, func_name: str, data_filename: str) -> tuple[list[str], Path]:
    func_dir = case_dir / "postProcessing" / func_name
    matches = sorted(func_dir.glob(f"*/{data_filename}"))
    if not matches:
        raise FileNotFoundError(f"missing postProcess output: {func_dir}/*/{data_filename}")
    latest = matches[-1]
    return _parse_last_data_row(latest), latest


def extract_qoi(case_dir: Path, case_id: str | None = None) -> QoIResult:
    """case_dir is the OpenFOAM case directory itself (case_root/case), i.e.
    what app.paths.require_prepared_case returns -- not the case_root."""
    errors: list[str] = []
    evidence: list[str] = []
    latest_time: str | None = None

    def read(func_name: str, data_filename: str) -> list[str] | None:
        nonlocal latest_time
        try:
            tokens, path = _read_function_output(case_dir, func_name, data_filename)
            evidence.append(str(path))
            latest_time = latest_time or tokens[0]
            return tokens
        except Exception as exc:  # noqa: BLE001 - record and continue, don't abort other QoIs
            errors.append(f"{func_name}: {exc}")
            return None

    inlet_flow = read("patchFlowRate(patch=inlet)", "surfaceFieldValue.dat")
    outlet_flow = read("patchFlowRate(patch=outlet)", "surfaceFieldValue.dat")
    inlet_p = read("patchAverage(patch=inlet,fields=(p))", "surfaceFieldValue.dat")
    outlet_p = read("patchAverage(patch=outlet,fields=(p))", "surfaceFieldValue.dat")
    max_u = read("cellMaxMag(U)", "volFieldValue.dat")
    avg_u = read("volAverage(U)", "volFieldValue.dat")

    mass_flow_in = abs(float(inlet_flow[1])) if inlet_flow else None
    mass_flow_out = abs(float(outlet_flow[1])) if outlet_flow else None
    mass_imbalance = None
    if mass_flow_in is not None and mass_flow_out is not None:
        from app.validation.conservation import compute_mass_imbalance

        mass_imbalance = compute_mass_imbalance(mass_flow_in, mass_flow_out)

    pressure_drop = None
    if inlet_p and outlet_p:
        pressure_drop = float(inlet_p[1]) - float(outlet_p[1])

    maximum_velocity = float(max_u[1]) if max_u else None
    average_velocity = _vector_magnitude(avg_u[1]) if avg_u else None

    complete = not errors
    return QoIResult(
        case_id=case_id,
        latest_time=latest_time,
        pressure_drop=pressure_drop,
        mass_flow_in=mass_flow_in,
        mass_flow_out=mass_flow_out,
        mass_imbalance=mass_imbalance,
        maximum_velocity=maximum_velocity,
        average_velocity=average_velocity,
        complete=complete,
        errors=errors,
        evidence=evidence,
    )


def write_qoi_artifacts(case_root: Path, qoi: QoIResult) -> None:
    """Writes results/qoi.json and results/qoi.csv under case_root, per the
    artifact contract in plan section 20/25."""
    results_dir = case_root / "results"
    results_dir.mkdir(exist_ok=True)

    (results_dir / "qoi.json").write_text(json.dumps(qoi.model_dump(), indent=2) + "\n")

    fields = [
        "case_id", "latest_time", "pressure_drop", "mass_flow_in", "mass_flow_out",
        "mass_imbalance", "maximum_velocity", "average_velocity", "complete",
    ]
    with (results_dir / "qoi.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({k: qoi.model_dump()[k] for k in fields})
