#!/usr/bin/env python3
"""Streamlit UI for the agentic CFD workflow.

    uv run streamlit run streamlit_app.py

Start a new study, approve the proposed plan when it pauses at the human
approval gate (the agent cannot bypass this -- AGENTS.md section 8), and
watch/browse real Docker + AWS Bedrock runs: validation gates, QoI results,
mesh independence, the velocity-sweep plot, the review, and the final
report. All execution happens on a background thread (app/ui_runner.py) so
the UI never blocks on a multi-minute CFD run; it observes progress by
re-reading the SQLite checkpoint, which is written after every graph node.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from app import config  # noqa: E402
from app.ui_runner import (  # noqa: E402
    approve_and_continue,
    get_run_thread_info,
    get_state,
    is_running,
    list_runs,
    resume_run,
    start_new_run,
)

st.set_page_config(page_title="Agentic CFD Scientist", layout="wide", initial_sidebar_state="expanded")

if "selected_run_id" not in st.session_state:
    st.session_state.selected_run_id = None


def _dataframe(rows: list[dict]) -> None:
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("None yet.")


# ---------------------------------------------------------------------
# Sidebar: environment, new run, run list
# ---------------------------------------------------------------------
with st.sidebar:
    st.title("Agentic CFD Scientist")
    st.caption("Local OpenFOAM + LangGraph + AWS Bedrock")
    st.caption(f"Model: `{config.BEDROCK_MODEL_ID}` · Image: `{config.OPENFOAM_IMAGE}`")

    with st.expander("Start a new study", expanded=st.session_state.selected_run_id is None):
        goal = st.text_area(
            "Engineering objective",
            placeholder=(
                "Study how inlet velocity (10, 15, 20 m/s) affects pressure drop "
                "in the backward-facing step, verifying mesh independence across "
                "coarse/medium/fine meshes at the baseline velocity."
            ),
            height=120,
            key="new_goal",
        )
        if st.button("Start study", type="primary", disabled=not goal.strip()):
            run_id = start_new_run(goal.strip())
            st.session_state.selected_run_id = run_id
            st.rerun()

    st.divider()
    st.subheader("Runs")
    runs = list_runs()
    if not runs:
        st.caption("No runs yet.")
    for run in runs:
        if run["has_final_report"]:
            status_tag = "[done]"
        elif is_running(run["run_id"]):
            status_tag = "[running]"
        else:
            status_tag = "[paused]"
        label = f"{status_tag} {run['run_id']}"
        if st.button(label, key=f"select_{run['run_id']}", width="stretch",
                     help=run["user_goal"]):
            st.session_state.selected_run_id = run["run_id"]
            st.rerun()

# ---------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------
run_id = st.session_state.selected_run_id
if not run_id:
    st.info("Start a new study or select a run from the sidebar.")
    st.markdown(
        "This UI drives the same workflow as `scripts/run_demo.py`: a Bedrock-backed "
        "planner proposes a study plan, a deterministic policy checker validates it, "
        "**you** approve it, and only then does real OpenFOAM execution begin -- "
        "mesh generation, solving, QoI extraction, mesh-independence and conservation "
        "gates, a bounded-retry diagnostic agent, a parameter sweep, a cited review, "
        "and a final report gated on every artifact actually being present and every "
        "gate having actually passed."
    )
    st.stop()

state = get_state(run_id)
if state is None:
    st.warning(f"No checkpoint found yet for `{run_id}` -- it may still be starting.")
    if st.button("Refresh"):
        st.rerun()
    st.stop()

st.header(run_id)
st.caption(state.get("user_goal", ""))

running = is_running(run_id)
thread_info = get_run_thread_info(run_id)

col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
col1.metric("Stage", state.get("current_stage", "unknown"))
col2.metric("Status", "running" if running else "idle")
if col3.button("Refresh"):
    st.rerun()
auto_refresh = col4.checkbox("Auto", value=False, help="Auto-refresh every 5s while running")

if thread_info.get("error"):
    st.error(f"Background execution error:\n\n```\n{thread_info['error']}\n```")

for err in state.get("errors") or []:
    st.warning(err)

# -- Human approval gate --------------------------------------------------
approval_status = state.get("approval_status") or {}
if state.get("current_stage") == "human_approval" and not approval_status.get("approved"):
    st.subheader("Proposed study plan — awaiting approval")
    plan = state.get("study_plan") or {}

    st.write(f"**Objective:** {plan.get('objective', '')}")
    st.write(f"**Baseline case:** {plan.get('baseline_case', '')}")
    st.write(f"**Mesh levels:** {', '.join(plan.get('mesh_levels', []))}")

    if plan.get("cases"):
        _dataframe([
            {"case_id": c["case_id"], "inlet_velocity (m/s)": c["inlet_velocity"], "mesh_level": c["mesh_level"]}
            for c in plan["cases"]
        ])

    with st.expander("Assumptions & validation plan"):
        st.write("**Assumptions:**")
        for a in plan.get("assumptions", []):
            st.write(f"- {a}")
        st.write("**Validation plan:**")
        for v in plan.get("validation_plan", []):
            st.write(f"- {v}")

    approved_by = st.text_input("Approved by", value="ui-user", key=f"approver_{run_id}")
    notes = st.text_area("Notes (optional)", key=f"notes_{run_id}")
    if st.button("Approve and run", type="primary", disabled=running):
        approve_and_continue(run_id, approved_by, notes)
        st.rerun()

elif state.get("current_stage") != "completed" and not running and not thread_info.get("error"):
    st.info("This run is paused and no background thread is currently driving it.")
    if st.button("Resume run"):
        resume_run(run_id)
        st.rerun()

# -- Agent decisions / audit trail ----------------------------------------
with st.expander("Agent decisions (audit trail)", expanded=False):
    decisions = state.get("agent_decisions") or []
    _dataframe([
        {"id": d["decision_id"], "agent": d["agent"], "action": d["action"],
         "policy_check": d["policy_check"], "reason": d["reason"]}
        for d in decisions
    ])

# -- Validation results -----------------------------------------------------
with st.expander("Validation results", expanded=False):
    validation = state.get("validation_results") or {}
    _dataframe([
        {"key": k, "status": str(v.get("status")) if isinstance(v, dict) else str(v)}
        for k, v in validation.items()
    ])

# -- Mesh independence --------------------------------------------------
mesh_independence = (state.get("validation_results") or {}).get("_mesh_independence")
if mesh_independence:
    with st.expander("Mesh independence", expanded=True):
        status = mesh_independence["status"]
        st.write(f"**Status:** {status}")
        if mesh_independence.get("relative_changes"):
            threshold = mesh_independence.get("threshold", 0)
            _dataframe([
                {"qoi": k, "relative_change": f"{v:.2%}", "threshold": f"{threshold:.2%}"}
                for k, v in mesh_independence["relative_changes"].items()
            ])
        for r in mesh_independence.get("reasons") or []:
            st.caption(r)

# -- QoI results -----------------------------------------------------------
qoi_results = state.get("qoi_results") or {}
if qoi_results:
    with st.expander("QoI results", expanded=True):
        _dataframe([
            {
                "case_id": case_id,
                "pressure_drop": qoi.get("pressure_drop"),
                "mass_imbalance": qoi.get("mass_imbalance"),
                "maximum_velocity": qoi.get("maximum_velocity"),
                "average_velocity": qoi.get("average_velocity"),
                "complete": qoi.get("complete"),
            }
            for case_id, qoi in qoi_results.items()
        ])

# -- Sweep plot --------------------------------------------------------
plot_path = config.RUNS_DIR / run_id / "plots" / "qoi_vs_velocity.png"
if plot_path.is_file():
    with st.expander("Pressure drop vs inlet velocity", expanded=True):
        st.image(str(plot_path))

# -- Review ------------------------------------------------------------
review_path = config.RUNS_DIR / run_id / "review.json"
if review_path.is_file():
    review = json.loads(review_path.read_text())
    with st.expander("Review", expanded=True):
        st.write(review.get("summary", ""))
        if review.get("findings"):
            _dataframe([
                {"claim": f["claim"], "metric": f["metric"], "value": f["value"],
                 "threshold": f.get("threshold"), "pass_fail": f["pass_fail"],
                 "evidence": f["evidence_file"]}
                for f in review["findings"]
            ])
        if review.get("trends"):
            st.write("**Trends:**")
            for t in review["trends"]:
                st.write(f"- {t}")
        if review.get("limitations"):
            st.write("**Limitations:**")
            for lim in review["limitations"]:
                st.write(f"- {lim}")
        if review.get("uncertainties"):
            st.write("**Uncertainties:**")
            for u in review["uncertainties"]:
                st.write(f"- {u}")

# -- Final report --------------------------------------------------------
report_path = config.RUNS_DIR / run_id / "reports" / "final_report.md"
if report_path.is_file():
    st.subheader("Final report")
    report_text = report_path.read_text()
    st.download_button("Download final_report.md", report_text, file_name=f"{run_id}_final_report.md")
    with st.expander("View report", expanded=True):
        st.markdown(report_text)

# -- Raw artifacts browser --------------------------------------------------
with st.expander("Raw artifacts", expanded=False):
    run_dir = config.RUNS_DIR / run_id
    for path in sorted(run_dir.glob("*.json")):
        st.caption(path.name)
        try:
            st.json(json.loads(path.read_text()), expanded=False)
        except json.JSONDecodeError:
            st.text(path.read_text())

if auto_refresh and running:
    time.sleep(5)
    st.rerun()
