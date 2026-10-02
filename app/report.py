from __future__ import annotations

from app import config
from app.artifacts import read_run_artifact


def _fmt(value) -> str:
    return "n/a" if value is None else str(value)


def render_final_report(run_id: str) -> str:
    study = read_run_artifact(run_id, "study.json")
    plan = read_run_artifact(run_id, "plan.json")
    approval = read_run_artifact(run_id, "approval.json")
    manifest = read_run_artifact(run_id, "case_manifest.json")
    mesh_report = read_run_artifact(run_id, "mesh_report.json")
    solver_health = read_run_artifact(run_id, "solver_health.json")
    mesh_independence = read_run_artifact(run_id, "mesh_independence.json")
    sweep_results = read_run_artifact(run_id, "sweep_results.json")
    review = read_run_artifact(run_id, "review.json")
    audit_log = read_run_artifact(run_id, "audit.json")

    lines: list[str] = []
    lines.append(f"# Final Report — {run_id}")
    lines.append("")
    lines.append(f"**Objective:** {study['user_goal']}")
    lines.append(f"**Run started:** {study['created_at']}")
    lines.append(f"**Baseline case:** {plan['baseline_case']}")
    lines.append(f"**Planner/review model:** {config.BEDROCK_MODEL_ID} (AWS Bedrock)")
    lines.append("")

    lines.append("## Approval")
    lines.append("")
    lines.append(f"- Approved by: {approval.get('approved_by', 'n/a')}")
    lines.append(f"- Approved at: {approval.get('approved_at', 'n/a')}")
    if approval.get("notes"):
        lines.append(f"- Notes: {approval['notes']}")
    lines.append("")

    lines.append("## Cases run")
    lines.append("")
    lines.append("| case_id | inlet_velocity (m/s) | mesh_level |")
    lines.append("|---|---|---|")
    for case in manifest:
        lines.append(
            f"| {case['case_id']} | {_fmt(case.get('inlet_velocity'))} | {_fmt(case.get('mesh_level'))} |"
        )
    lines.append("")

    lines.append("## Mesh levels used")
    lines.append("")
    lines.append(f"- Requested: {', '.join(plan.get('mesh_levels', []))}")
    lines.append("")

    lines.append("## Validation criteria and results")
    lines.append("")
    lines.append(f"- Validation plan: {', '.join(plan.get('validation_plan', []))}")
    lines.append("")
    lines.append("### Mesh quality (Gate B)")
    lines.append("")
    for case_id, result in mesh_report.items():
        lines.append(
            f"- `{case_id}`: **{result['status']}** (cells={result.get('cells')}, "
            f"max_skewness={result.get('max_skewness')}, "
            f"max_nonorthogonality={result.get('max_nonorthogonality')})"
        )
    lines.append("")
    lines.append("### Solver health (Gate C)")
    lines.append("")
    for case_id, result in solver_health.items():
        lines.append(
            f"- `{case_id}`: **{result['status']}** (converged={result.get('converged')}, "
            f"iterations={result.get('iterations')})"
        )
    lines.append("")
    lines.append("### Mesh independence (Gate E)")
    lines.append("")
    lines.append(f"- Status: **{mesh_independence.get('status')}**")
    if mesh_independence.get("relative_changes"):
        threshold = mesh_independence.get("threshold", 0)
        for qoi_name, rc in mesh_independence["relative_changes"].items():
            lines.append(f"  - {qoi_name}: relative change {rc:.2%} (threshold {threshold:.2%})")
    if mesh_independence.get("reasons"):
        lines.append(f"  - reasons: {mesh_independence['reasons']}")
    lines.append("")

    lines.append("## Sweep results")
    lines.append("")
    rows = sweep_results.get("cases", [])
    if rows:
        lines.append("| case_id | inlet_velocity | mesh_level | pressure_drop | mass_imbalance | complete |")
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            lines.append(
                f"| {row['case_id']} | {_fmt(row.get('inlet_velocity'))} | {_fmt(row.get('mesh_level'))} | "
                f"{_fmt(row.get('pressure_drop'))} | {_fmt(row.get('mass_imbalance'))} | {row.get('complete')} |"
            )
    lines.append("")

    lines.append("## Review")
    lines.append("")
    lines.append(review.get("summary", ""))
    lines.append("")
    if review.get("findings"):
        lines.append("### Findings")
        lines.append("")
        for f in review["findings"]:
            lines.append(
                f"- **{f['claim']}** — {f['metric']}={f['value']} "
                f"(threshold {f.get('threshold', 'n/a')}), {f['pass_fail']}, "
                f"evidence: `{f['evidence_file']}`"
            )
        lines.append("")
    if review.get("trends"):
        lines.append("### Trends")
        lines.append("")
        for t in review["trends"]:
            lines.append(f"- {t}")
        lines.append("")

    lines.append("## Limitations")
    lines.append("")
    for item in review.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Uncertainties")
    lines.append("")
    for item in review.get("uncertainties", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Agent decisions")
    lines.append("")
    lines.append("| decision_id | agent | action | policy_check |")
    lines.append("|---|---|---|---|")
    for d in audit_log.get("decisions", []):
        lines.append(f"| {d['decision_id']} | {d['agent']} | {d['action']} | {d['policy_check']} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "This report was assembled deterministically from the JSON artifacts listed above; "
        "it is not a physically validated engineering certification. See AGENTS.md."
    )
    lines.append("")

    return "\n".join(lines)
