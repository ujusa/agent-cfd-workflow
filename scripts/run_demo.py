#!/usr/bin/env python3
"""CLI entry point for the agentic CFD demo workflow (plan section 42).

    python scripts/run_demo.py --goal "Study how inlet velocity affects ..."
    python scripts/run_demo.py --resume <run_id>

Approval is interactive: when the workflow pauses at the human-approval
gate, this prints the Bedrock-proposed StudyPlan and asks for y/n on the
terminal -- CLI approval is enough for v1 (plan section 11). The agent
cannot bypass this; see app/graph.py:node_prepare_baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import checkpoint  # noqa: E402
from app import state as state_mod  # noqa: E402
from app.graph import build_graph  # noqa: E402


def _new_run_id() -> str:
    return f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"


def _prompt_approval() -> bool:
    answer = input("\nApprove this study plan and begin CFD execution? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agentic CFD demo workflow.")
    parser.add_argument("--goal", help="Engineering objective for a new run.")
    parser.add_argument("--resume", metavar="RUN_ID", help="Resume an existing run_id.")
    parser.add_argument("--approved-by", default="cli-user", help="Recorded in approval.json.")
    parser.add_argument(
        "--yes", action="store_true", help="Skip the interactive prompt and approve automatically."
    )
    args = parser.parse_args()

    if not args.goal and not args.resume:
        parser.error("either --goal or --resume is required")

    graph = build_graph(checkpoint.build_checkpointer())

    if args.resume:
        run_id = args.resume
        cfg = checkpoint.thread_config(run_id)
        snapshot = graph.get_state(cfg)
        if not snapshot.values:
            print(f"no checkpoint found for run_id={run_id!r}", file=sys.stderr)
            return 1
        state = snapshot.values
        print(f"resumed run_id: {run_id} (stage: {state['current_stage']})")
    else:
        run_id = _new_run_id()
        cfg = checkpoint.thread_config(run_id)
        print(f"run_id: {run_id}")
        state = graph.invoke(state_mod.initial_state(run_id, args.goal), cfg)

    if state["current_stage"] == "human_approval":
        print("\n=== Proposed study plan ===")
        print(json.dumps(state["study_plan"], indent=2))

        approved = args.yes or _prompt_approval()
        if not approved:
            print(f"\nNot approved. Resume later with: python scripts/run_demo.py --resume {run_id}")
            return 0

        graph.update_state(cfg, {
            "approval_status": {
                "approved": True,
                "approved_by": args.approved_by,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "plan_version": "1",
                "notes": "approved via scripts/run_demo.py",
            }
        })
        state = graph.invoke(None, cfg)

    print("\n=== Final state ===")
    print("stage:", state["current_stage"])
    print("errors:", state["errors"] or "none")
    if state.get("qoi_results"):
        print("\nqoi_results:")
        print(json.dumps(state["qoi_results"], indent=2))
    if state.get("final_report_path"):
        print(f"\nFinal report: {state['final_report_path']}")
    print(f"\nRun artifacts: runs/{run_id}/")
    return 0 if not state["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
