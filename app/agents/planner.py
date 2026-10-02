from __future__ import annotations

from app import config
from app.llm import LLMService, load_prompt_template
from app.schemas import CaseSpec, StudyPlan


def mock_plan_study(user_goal: str) -> StudyPlan:
    return StudyPlan(
        objective=user_goal,
        baseline_case="backward_facing_step",
        cases=[CaseSpec(case_id="baseline", inlet_velocity=10.0, mesh_level="medium")],
        mesh_levels=["coarse", "medium", "fine"],
        qois=[
            "pressure_drop",
            "mass_flow_in",
            "mass_flow_out",
            "mass_imbalance",
            "maximum_velocity",
            "average_velocity",
        ],
        permitted_parameters=["inlet_velocity", "mesh_level"],
        assumptions=[
            "Steady RAS kEpsilon turbulence model (foamRun/incompressibleFluid).",
            "Constant fluid properties, nu = 1e-05 (air-like, incompressible).",
            "2-D backward-facing-step geometry fixed per cfd_cases/backward_facing_step/README.md.",
        ],
        validation_plan=["case_integrity", "mesh_quality", "solver_health", "conservation"],
        requires_human_approval=True,
    )


def render_planner_prompt(user_goal: str) -> str:
    template = load_prompt_template("planner.md")
    skill = (config.SKILLS_DIR / "cfd-planning.md").read_text()
    case_readme = (config.CFD_CASES_DIR / "backward_facing_step" / "README.md").read_text()
    bounds = config.PARAMETER_BOUNDS["inlet_velocity"]
    allowed_parameters = ", ".join(sorted(set(config.PARAMETER_BOUNDS) | {"mesh_level"}))

    replacements = {
        "<<SKILL_CFD_PLANNING>>": skill,
        "<<BENCHMARK_CASE_README>>": case_readme,
        "<<ALLOWED_PARAMETERS>>": allowed_parameters,
        "<<INLET_VELOCITY_MIN>>": str(bounds["min"]),
        "<<INLET_VELOCITY_MAX>>": str(bounds["max"]),
        "<<USER_GOAL>>": user_goal,
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def bedrock_plan_study(user_goal: str, llm: LLMService | None = None) -> StudyPlan:
    """The real planner (Milestone 4). Schema validation happens inside
    LLMService.structured_plan; the caller (graph.node_plan_study, from
    Milestone 5 onward) still runs this through app.policy.check_plan_policy
    before anything executes -- the LLM's output is never trusted outright.
    """
    llm = llm or LLMService()
    prompt = render_planner_prompt(user_goal)
    result = llm.structured_plan(prompt, StudyPlan)
    assert isinstance(result, StudyPlan)
    return result
