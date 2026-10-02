"""Gate B (mesh quality, per case) and Gate E (mesh independence, across
mesh levels) -- plan section 19. Both are "mesh" concerns so they share a
module, matching the 4-file layout fixed by the Milestone 2 instructions.
"""
from __future__ import annotations

import math
import re

from pydantic import BaseModel

from app import config
from app.validation.common import GateStatus

# -- Gate B: mesh quality (parses checkMesh.log) ---------------------------

_CELLS_RE = re.compile(r"^\s*cells:\s+(\d+)", re.MULTILINE)
_FACES_RE = re.compile(r"^\s*faces:\s+(\d+)", re.MULTILINE)
_INTERNAL_FACES_RE = re.compile(r"^\s*internal faces:\s+(\d+)", re.MULTILINE)
_MAX_SKEWNESS_RE = re.compile(r"Max skewness = ([\d.eE+-]+)")
_MAX_NONORTHO_RE = re.compile(r"non-orthogonality Max:\s*([\d.eE+-]+)", re.IGNORECASE)
_NEGATIVE_VOLUME_RE = re.compile(r"negative[- ]volume.*?=\s*(\d+)", re.IGNORECASE)
_MESH_OK_RE = re.compile(r"^Mesh OK\.$", re.MULTILINE)
_FAILED_CHECKS_RE = re.compile(r"Failed (\d+) mesh checks")


class MeshQualityResult(BaseModel):
    status: GateStatus
    cells: int | None
    faces: int | None
    boundary_faces: int | None
    max_skewness: float | None
    max_nonorthogonality: float | None
    negative_volume_cells: int
    mesh_ok_reported: bool
    reasons: list[str]
    evidence: list[str]


def parse_check_mesh_log(log_text: str) -> dict:
    cells = int(m.group(1)) if (m := _CELLS_RE.search(log_text)) else None
    faces = int(m.group(1)) if (m := _FACES_RE.search(log_text)) else None
    internal_faces = (
        int(m.group(1)) if (m := _INTERNAL_FACES_RE.search(log_text)) else None
    )
    boundary_faces = (
        faces - internal_faces if faces is not None and internal_faces is not None else None
    )
    max_skewness = float(m.group(1)) if (m := _MAX_SKEWNESS_RE.search(log_text)) else None
    max_nonortho = float(m.group(1)) if (m := _MAX_NONORTHO_RE.search(log_text)) else None
    negative_volume_cells = (
        int(m.group(1)) if (m := _NEGATIVE_VOLUME_RE.search(log_text)) else 0
    )
    mesh_ok_reported = bool(_MESH_OK_RE.search(log_text))
    return {
        "cells": cells,
        "faces": faces,
        "boundary_faces": boundary_faces,
        "max_skewness": max_skewness,
        "max_nonorthogonality": max_nonortho,
        "negative_volume_cells": negative_volume_cells,
        "mesh_ok_reported": mesh_ok_reported,
    }


def check_mesh_quality(
    log_text: str,
    return_code: int | None,
    max_skewness: float = config.MESH_QUALITY_MAX_SKEWNESS,
    max_nonorthogonality: float = config.MESH_QUALITY_MAX_NONORTHOGONALITY,
    max_negative_volume_cells: int = config.MESH_QUALITY_MAX_NEGATIVE_VOLUME_CELLS,
    log_path: str | None = None,
) -> MeshQualityResult:
    parsed = parse_check_mesh_log(log_text)
    reasons: list[str] = []

    if return_code != 0:
        reasons.append(f"checkMesh did not exit 0 (return_code={return_code})")
    if parsed["cells"] is None or parsed["faces"] is None:
        reasons.append("could not parse cell/face counts from checkMesh log")
    if parsed["max_skewness"] is not None and parsed["max_skewness"] > max_skewness:
        reasons.append(
            f"max skewness {parsed['max_skewness']:.3f} exceeds threshold {max_skewness}"
        )
    if (
        parsed["max_nonorthogonality"] is not None
        and parsed["max_nonorthogonality"] > max_nonorthogonality
    ):
        reasons.append(
            f"max non-orthogonality {parsed['max_nonorthogonality']:.2f} "
            f"exceeds threshold {max_nonorthogonality}"
        )
    if parsed["negative_volume_cells"] > max_negative_volume_cells:
        reasons.append(
            f"{parsed['negative_volume_cells']} negative-volume cells "
            f"exceeds allowed {max_negative_volume_cells}"
        )
    if _FAILED_CHECKS_RE.search(log_text):
        reasons.append("checkMesh reported failed mesh checks")

    status: GateStatus = "PASSED" if not reasons else "FAILED"
    return MeshQualityResult(
        status=status,
        evidence=[log_path] if log_path else [],
        reasons=reasons,
        **parsed,
    )


# -- Gate E: mesh independence (compares QoIs across mesh levels) ---------


class MeshIndependenceResult(BaseModel):
    status: GateStatus
    threshold: float
    relative_changes: dict[str, float]
    qois_by_level: dict[str, dict[str, float]]
    reasons: list[str]
    evidence: list[str]


def compute_relative_change(
    q_fine: float, q_medium: float, epsilon: float = 1e-9
) -> float:
    """relative_change = abs(Q_fine - Q_medium) / max(abs(Q_fine), epsilon) --
    plan section 19 Gate E."""
    return abs(q_fine - q_medium) / max(abs(q_fine), epsilon)


def assess_mesh_independence(
    qois_by_level: dict[str, dict[str, float]],
    qoi_names: list[str] = config.MESH_INDEPENDENCE_QOIS,
    threshold: float = config.MESH_INDEPENDENCE_MAX_RELATIVE_CHANGE,
    epsilon: float = 1e-9,
) -> MeshIndependenceResult:
    reasons: list[str] = []
    for level in ("medium", "fine"):
        if level not in qois_by_level:
            raise ValueError(f"missing QoIs for mesh level required by this gate: {level!r}")

    relative_changes: dict[str, float] = {}
    for name in qoi_names:
        q_medium = qois_by_level["medium"].get(name)
        q_fine = qois_by_level["fine"].get(name)
        if q_medium is None or q_fine is None:
            reasons.append(f"missing QoI {name!r} for medium/fine comparison")
            continue
        if not (math.isfinite(q_medium) and math.isfinite(q_fine)):
            reasons.append(f"non-finite QoI {name!r} for medium/fine comparison")
            continue
        rc = compute_relative_change(q_fine, q_medium, epsilon)
        relative_changes[name] = rc
        if rc > threshold:
            reasons.append(
                f"{name}: relative change {rc:.2%} exceeds threshold {threshold:.2%}"
            )

    ok = bool(relative_changes) and not reasons
    status: GateStatus = "PASSED" if ok else "FAILED"
    return MeshIndependenceResult(
        status=status,
        threshold=threshold,
        relative_changes=relative_changes,
        qois_by_level=qois_by_level,
        reasons=reasons,
        evidence=[],
    )
