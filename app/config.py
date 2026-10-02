from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


OPENFOAM_IMAGE = os.environ.get(
    "OPENFOAM_IMAGE", "openfoam/openfoam11-graphical-apps:11"
)
OPENFOAM_PLATFORM = os.environ.get("OPENFOAM_PLATFORM", "linux/amd64")
OPENFOAM_CONTAINER_WORKDIR = "/case"
OPENFOAM_TIMEOUT_SECONDS = int(os.environ.get("OPENFOAM_TIMEOUT_SECONDS", "900"))
MESH_TIMEOUT_SECONDS = int(os.environ.get("OPENFOAM_MESH_TIMEOUT_SECONDS", "300"))
CHECK_MESH_TIMEOUT_SECONDS = int(os.environ.get("OPENFOAM_CHECK_MESH_TIMEOUT_SECONDS", "300"))
SOLVE_TIMEOUT_SECONDS = int(
    os.environ.get("OPENFOAM_SOLVE_TIMEOUT_SECONDS", str(OPENFOAM_TIMEOUT_SECONDS))
)


PARAMETER_BOUNDS = {
    "inlet_velocity": {"min": 5.0, "max": 25.0},
}

MESH_LEVEL_FACTORS = {
    "coarse": 0.5,
    "medium": 1.0,
    "fine": 1.5,
}

POSTPROCESS_TIMEOUT_SECONDS = int(os.environ.get("OPENFOAM_POSTPROCESS_TIMEOUT_SECONDS", "180"))

MESH_QUALITY_MAX_SKEWNESS = 4.0
MESH_QUALITY_MAX_NONORTHOGONALITY = 70.0
MESH_QUALITY_MAX_NEGATIVE_VOLUME_CELLS = 0

CONSERVATION_MAX_IMBALANCE = 0.02 

MESH_INDEPENDENCE_MAX_RELATIVE_CHANGE = 0.15
MESH_INDEPENDENCE_QOIS = ["pressure_drop", "maximum_velocity", "average_velocity"]

MAX_SOLVER_RETRIES = 2
MAX_MESH_RETRIES = 1
DIAGNOSTIC_FIX_BOUNDS = {
    "relaxation": {"min": 0.3, "max": 0.95},
    "numerical_solver_setting": {"min": 0, "max": 3},
    "time_control": {"min": 2000, "max": 6000},
}


CFD_CASES_DIR = REPO_ROOT / "cfd_cases"
RUNS_DIR = REPO_ROOT / "runs"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
SKILLS_DIR = REPO_ROOT / "skills"
DATA_DIR = REPO_ROOT / "data"

BENCHMARK_CASE_ID = "backward_facing_step"
BENCHMARK_CASE_TEMPLATE = CFD_CASES_DIR / BENCHMARK_CASE_ID / "template"


CHECKPOINT_DB_PATH = Path(
    os.environ.get("CHECKPOINT_DB_PATH", str(DATA_DIR / "checkpoints.sqlite"))
)

BEDROCK_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.amazon.nova-pro-v1:0")
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "4096"))
