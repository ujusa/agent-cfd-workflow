"""Drives the actual Streamlit UI (streamlit_app.py) via Streamlit's
official no-browser test harness (streamlit.testing.v1.AppTest), proving
the widget wiring -- not just that the module imports -- works: start a
study, approve it, and confirm the final report renders. Docker/Bedrock
calls are faked (tests/fake_tools.py) so this stays hermetic.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import config
from tests.fake_tools import install as install_fake_tools

APP_PATH = Path(__file__).resolve().parent.parent / "streamlit_app.py"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    config.RUNS_DIR.mkdir()
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "checkpoints.sqlite")
    yield


def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError("condition not met within timeout")


def test_app_loads_with_no_runs_selected():
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Start a new study" in i.value for i in at.info)


def test_full_ui_flow_start_approve_complete(monkeypatch):
    install_fake_tools(monkeypatch)

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    assert not at.exception

    at.text_area(key="new_goal").input("Study inlet velocity effect on pressure drop").run()
    assert not at.exception

    start_button = next(b for b in at.button if b.label == "Start study")
    start_button.click().run()
    assert not at.exception

    # run_id is assigned to session_state synchronously by start_new_run;
    # the background thread writing its first artifact (study.json) is not.
    from app.ui_runner import get_state, is_running

    run_id = at.session_state["selected_run_id"]
    assert run_id

    _wait_until(lambda: get_state(run_id) is not None)
    _wait_until(lambda: not is_running(run_id))

    at.run()  # re-render now that the checkpoint shows human_approval
    assert not at.exception
    assert any("awaiting approval" in h.value for h in at.subheader)

    approve_button = next(b for b in at.button if "Approve and run" in b.label)
    approve_button.click().run()
    assert not at.exception

    _wait_until(lambda: not is_running(run_id), timeout=15.0)

    at.run()
    assert not at.exception

    final_state = get_state(run_id)
    assert final_state["current_stage"] == "completed"
    assert any("Final report" in h.value for h in at.subheader)
    assert any(b.label.startswith("Download") for b in at.download_button)
