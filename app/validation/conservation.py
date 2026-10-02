"""Gate D -- conservation (plan section 19). The formula is fixed in code;
the LLM never invents or adjusts it (AGENTS.md section 5)."""
from __future__ import annotations

import math

from pydantic import BaseModel

from app import config
from app.validation.common import GateStatus

DEFAULT_EPSILON = 1e-9


class ConservationResult(BaseModel):
    status: GateStatus
    mass_flow_in: float
    mass_flow_out: float
    imbalance: float
    threshold: float
    reasons: list[str]


def compute_mass_imbalance(
    mass_flow_in: float, mass_flow_out: float, epsilon: float = DEFAULT_EPSILON
) -> float:
    """imbalance = abs(m_in - m_out) / max(abs(m_in), epsilon) -- plan section 19 Gate D."""
    return abs(mass_flow_in - mass_flow_out) / max(abs(mass_flow_in), epsilon)


def check_conservation(
    mass_flow_in: float,
    mass_flow_out: float,
    threshold: float = config.CONSERVATION_MAX_IMBALANCE,
    epsilon: float = DEFAULT_EPSILON,
) -> ConservationResult:
    if not (math.isfinite(mass_flow_in) and math.isfinite(mass_flow_out)):
        return ConservationResult(
            status="FAILED",
            mass_flow_in=mass_flow_in,
            mass_flow_out=mass_flow_out,
            imbalance=float("nan"),
            threshold=threshold,
            reasons=["non-finite mass flow value(s)"],
        )

    imbalance = compute_mass_imbalance(mass_flow_in, mass_flow_out, epsilon)
    reasons: list[str] = []
    ok = imbalance <= threshold
    if not ok:
        reasons.append(
            f"mass imbalance {imbalance:.2%} exceeds threshold {threshold:.2%}"
        )
    status: GateStatus = "PASSED" if ok else "FAILED"
    return ConservationResult(
        status=status,
        mass_flow_in=mass_flow_in,
        mass_flow_out=mass_flow_out,
        imbalance=imbalance,
        threshold=threshold,
        reasons=reasons,
    )
