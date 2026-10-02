"""Milestone 4: prompt rendering + mocked-LLM structured-output validation.
No real Bedrock call here -- bedrock_plan_study takes an injectable `llm`,
so these tests exercise the exact validation path a real LLMService.
structured_plan would go through, using fake producers instead of a network
call. The real call is verified separately (see conversation record /
scripts), since it depends on live AWS access.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.planner import bedrock_plan_study, mock_plan_study, render_planner_prompt
from app.schemas import StudyPlan

VALID_PLAN_DICT = {
    "objective": "Study inlet velocity effect on pressure drop",
    "baseline_case": "backward_facing_step",
    "cases": [{"case_id": "baseline", "inlet_velocity": 12.0, "mesh_level": "medium"}],
    "mesh_levels": ["coarse", "medium", "fine"],
    "qois": ["pressure_drop", "mass_flow_in", "mass_flow_out"],
    "permitted_parameters": ["inlet_velocity", "mesh_level"],
    "assumptions": ["Steady RAS kEpsilon."],
    "validation_plan": ["case_integrity", "mesh_quality", "solver_health", "conservation"],
    "requires_human_approval": True,
}


class _FakeLLM:
    """Mirrors LLMService.structured_plan's contract exactly: validate
    whatever the 'model' produced against the schema, instance or raw dict."""

    def __init__(self, response):
        self._response = response

    def structured_plan(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if isinstance(self._response, schema):
            return self._response
        return schema.model_validate(self._response)


# ---------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------

def test_render_planner_prompt_substitutes_all_tokens():
    prompt = render_planner_prompt("Study inlet velocity effect on pressure drop")
    assert "<<" not in prompt and ">>" not in prompt
    assert "Study inlet velocity effect on pressure drop" in prompt
    assert "backward_facing_step" in prompt or "backward-facing-step" in prompt
    assert "inlet_velocity" in prompt
    assert "5.0" in prompt and "25.0" in prompt  # configured bounds


# ---------------------------------------------------------------------
# bedrock_plan_study with a mocked LLM -- valid output
# ---------------------------------------------------------------------

def test_bedrock_plan_study_accepts_valid_llm_output():
    plan = bedrock_plan_study("goal", llm=_FakeLLM(dict(VALID_PLAN_DICT)))
    assert isinstance(plan, StudyPlan)
    assert plan.baseline_case == "backward_facing_step"
    assert plan.cases[0].inlet_velocity == 12.0
    assert plan.requires_human_approval is True


def test_bedrock_plan_study_accepts_prebuilt_studyplan_instance():
    prebuilt = StudyPlan.model_validate(VALID_PLAN_DICT)
    plan = bedrock_plan_study("goal", llm=_FakeLLM(prebuilt))
    assert plan is prebuilt


# ---------------------------------------------------------------------
# bedrock_plan_study with a mocked LLM -- malformed / out-of-range output
# ---------------------------------------------------------------------

def test_bedrock_plan_study_rejects_unknown_field():
    bad = dict(VALID_PLAN_DICT, unexpected_field="surprise")
    with pytest.raises(ValidationError):
        bedrock_plan_study("goal", llm=_FakeLLM(bad))


def test_bedrock_plan_study_rejects_missing_required_field():
    bad = dict(VALID_PLAN_DICT)
    del bad["cases"]
    with pytest.raises(ValidationError):
        bedrock_plan_study("goal", llm=_FakeLLM(bad))


def test_bedrock_plan_study_rejects_out_of_range_inlet_velocity():
    bad = dict(VALID_PLAN_DICT)
    bad["cases"] = [{"case_id": "baseline", "inlet_velocity": 999.0, "mesh_level": "medium"}]
    with pytest.raises(ValidationError):
        bedrock_plan_study("goal", llm=_FakeLLM(bad))


def test_bedrock_plan_study_rejects_invalid_mesh_level():
    bad = dict(VALID_PLAN_DICT)
    bad["cases"] = [{"case_id": "baseline", "inlet_velocity": 10.0, "mesh_level": "ultra"}]
    with pytest.raises(ValidationError):
        bedrock_plan_study("goal", llm=_FakeLLM(bad))


def test_bedrock_plan_study_rejects_disallowed_parameter_name_in_case():
    bad = dict(VALID_PLAN_DICT)
    bad["cases"] = [
        {"case_id": "baseline", "inlet_velocity": 10.0, "mesh_level": "medium", "outlet_pressure": 0.0}
    ]
    with pytest.raises(ValidationError):
        bedrock_plan_study("goal", llm=_FakeLLM(bad))


# ---------------------------------------------------------------------
# mock_plan_study (Milestone 3) and bedrock_plan_study produce the same shape
# ---------------------------------------------------------------------

def test_mock_and_bedrock_planners_produce_the_same_schema():
    mock = mock_plan_study("goal")
    real = bedrock_plan_study("goal", llm=_FakeLLM(dict(VALID_PLAN_DICT)))
    assert type(mock) is type(real) is StudyPlan
    assert set(mock.model_dump().keys()) == set(real.model_dump().keys())
