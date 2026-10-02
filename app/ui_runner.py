"""Background-thread orchestration for the Streamlit UI (streamlit_app.py
at the repo root). Kept separate from presentation so it's testable without
importing streamlit.

A fresh checkpointer/graph is built for every read or write (same pattern
verified in Milestone 3's cross-process resume test) -- concurrent UI
sessions and background threads never share a single sqlite3.Connection.
Execution (graph.invoke) always happens on a background thread so the UI
process never blocks on a multi-minute Docker/Bedrock call; progress is
observed by re-reading the checkpoint, which LangGraph writes incrementally
after every node.
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from app import checkpoint, config
from app import state as state_mod
from app.graph import build_graph

_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def new_run_id() -> str:
    return f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"


def _graph():
    return build_graph(checkpoint.build_checkpointer())


def thread_config(run_id: str) -> dict:
    return checkpoint.thread_config(run_id)


def get_state(run_id: str) -> dict | None:
    """Current checkpointed state for run_id, or None if no checkpoint
    exists yet (e.g. the background thread hasn't reached node_intake)."""
    snapshot = _graph().get_state(thread_config(run_id))
    return dict(snapshot.values) if snapshot.values else None


def _set_registry(run_id: str, **fields: Any) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY.setdefault(run_id, {})
        _REGISTRY[run_id].update(fields)


def get_run_thread_info(run_id: str) -> dict[str, Any]:
    with _REGISTRY_LOCK:
        return dict(_REGISTRY.get(run_id, {}))


def is_running(run_id: str) -> bool:
    thread = get_run_thread_info(run_id).get("thread")
    return bool(thread and thread.is_alive())


def _run_in_background(run_id: str, fn) -> threading.Thread:
    def target() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- surface to the UI, don't die silently
            _set_registry(run_id, error=f"{exc}\n{traceback.format_exc()}")

    thread = threading.Thread(target=target, daemon=True, name=f"cfd-run-{run_id}")
    _set_registry(run_id, thread=thread, error=None)
    thread.start()
    return thread


def start_new_run(goal: str) -> str:
    run_id = new_run_id()
    cfg = thread_config(run_id)

    def do_run() -> None:
        _graph().invoke(state_mod.initial_state(run_id, goal), cfg)

    _run_in_background(run_id, do_run)
    return run_id


def approve_and_continue(run_id: str, approved_by: str, notes: str = "") -> None:
    cfg = thread_config(run_id)
    _graph().update_state(cfg, {
        "approval_status": {
            "approved": True,
            "approved_by": approved_by or "ui-user",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "plan_version": "1",
            "notes": notes,
        }
    })

    def do_resume() -> None:
        _graph().invoke(None, cfg)

    _run_in_background(run_id, do_resume)


def resume_run(run_id: str) -> None:
    """Re-invokes an already-approved/paused run -- e.g. the background
    thread died with the previous Streamlit process but the checkpoint
    (and any applied approval) is still on disk."""
    cfg = thread_config(run_id)

    def do_resume() -> None:
        _graph().invoke(None, cfg)

    _run_in_background(run_id, do_resume)


def list_runs() -> list[dict]:
    """Cheap listing: reads study.json (always the first artifact written)
    for every run directory, without touching the checkpointer. Live
    stage/progress is fetched lazily via get_state only for the selected
    run, so this stays fast regardless of run count."""
    runs: list[dict] = []
    if not config.RUNS_DIR.is_dir():
        return runs
    for run_dir in sorted(config.RUNS_DIR.iterdir(), reverse=True):
        study_path = run_dir / "study.json"
        if not study_path.is_file():
            continue
        try:
            study = json.loads(study_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        runs.append({
            "run_id": run_dir.name,
            "user_goal": study.get("user_goal", ""),
            "created_at": study.get("created_at", ""),
            "has_final_report": (run_dir / "reports" / "final_report.md").is_file(),
        })
    return runs
