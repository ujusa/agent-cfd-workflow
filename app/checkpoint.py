from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app import config

_SETUP_DONE: set[str] = set()
_SETUP_LOCK = threading.Lock()


def build_checkpointer(db_path: Path | None = None) -> SqliteSaver:
    path = db_path or config.CHECKPOINT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    saver = SqliteSaver(conn)

    key = str(path.resolve())
    with _SETUP_LOCK:
        if key not in _SETUP_DONE:
            saver.setup()
            _SETUP_DONE.add(key)
    return saver


def thread_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}
