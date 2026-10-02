from __future__ import annotations

import json

from app import config
from app.artifacts import read_run_artifact
from app.llm import LLMService, load_prompt_template
from app.schemas import Review, ReviewFinding


EVIDENCE_ARTIFACTS = [
    "study.json",
    "plan.json",
    "approval.json",
    "case_manifest.json",
    "mesh_report.json",
    "solver_health.json",
    "mesh_independence.json",
    "sweep_results.json",
]


def build_evidence_bundle(run_id: str) -> dict:
    bundle: dict = {}
    for name in EVIDENCE_ARTIFACTS:
        try:
            bundle[name] = read_run_artifact(run_id, name)
        except FileNotFoundError:
            bundle[name] = None  
    return bundle


def mock_review_results(evidence: dict) -> Review:
    mesh_independence = evidence.get("mesh_independence.json") or {}
    sweep = (evidence.get("sweep_results.json") or {}).get("cases", [])
    manifest = evidence.get("case_manifest.json") or []

    findings = [
        ReviewFinding(
            claim="Mesh independence assessment status",
            evidence_file="mesh_independence.json",
            metric="status",
            value=str(mesh_independence.get("status", "n/a")),
            pass_fail=str(mesh_independence.get("status", "n/a")),
        )
    ]
    limitations = []
    if mesh_independence.get("status") != "PASSED":
        limitations.append("mesh independence was not cleanly PASSED")
    incomplete = [row["case_id"] for row in sweep if not row.get("complete")]
    if incomplete:
        limitations.append(f"incomplete QoIs for case(s): {incomplete}")

    return Review(
        summary=f"Ran {len(manifest)} case(s) in this study.",
        findings=findings,
        trends=[],
        limitations=limitations,
        uncertainties=["mock review -- not derived from a full read of the evidence bundle"],
    )


def render_reviewer_prompt(evidence: dict) -> str:
    template = load_prompt_template("reviewer.md")
    skill = (config.SKILLS_DIR / "result-review.md").read_text()
    replacements = {
        "<<SKILL_RESULT_REVIEW>>": skill,
        "<<EVIDENCE_JSON>>": json.dumps(evidence, indent=2, default=str),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def bedrock_review_results(run_id: str, llm: LLMService | None = None) -> Review:
    llm = llm or LLMService()
    evidence = build_evidence_bundle(run_id)
    prompt = render_reviewer_prompt(evidence)
    result = llm.structured_plan(prompt, Review)
    assert isinstance(result, Review)
    return result
