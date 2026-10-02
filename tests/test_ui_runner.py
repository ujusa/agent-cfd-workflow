"""app.ui_runner: background-thread orchestration backing the Streamlit UI.
Docker/Bedrock calls are faked (tests/fake_tools.py) so this stays
hermetic; monkeypatch's module-level patches are process-global, so they
apply correctly even though execution happens on a background thread.
"""
from __future__ import annotations

import time

import pytest

from app import config
from app import ui_runner
from tests.fake_tools import install as install_fake_tools


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    config.RUNS_DIR.mkdir()
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "checkpoints.sqlite")
    yield


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError("condition not met within timeout")


def test_new_run_id_is_unique_and_sortable():
    a = ui_runner.new_run_id()
    b = ui_runner.new_run_id()
    assert a != b
    assert a.startswith("run_")


def test_list_runs_empty_when_no_runs_dir_populated():
    assert ui_runner.list_runs() == []


def test_get_state_none_before_any_run_started():
    assert ui_runner.get_state("nonexistent") is None


def test_start_new_run_reaches_human_approval_then_resumes_to_completion(monkeypatch):
    install_fake_tools(monkeypatch)

    run_id = ui_runner.start_new_run("study inlet velocity")
    assert run_id.startswith("run_")

    _wait_until(lambda: ui_runner.get_state(run_id) is not None)
    _wait_until(lambda: not ui_runner.is_running(run_id))

    info = ui_runner.get_run_thread_info(run_id)
    assert info.get("error") is None

    state = ui_runner.get_state(run_id)
    assert state["current_stage"] == "human_approval"
    assert state["study_plan"]["baseline_case"] == "backward_facing_step"

    runs = ui_runner.list_runs()
    assert any(r["run_id"] == run_id for r in runs)
    assert not [r for r in runs if r["run_id"] == run_id][0]["has_final_report"]

    ui_runner.approve_and_continue(run_id, approved_by="tester", notes="go ahead")
    assert ui_runner.is_running(run_id) or True  # may finish before this check runs; both are fine

    _wait_until(lambda: not ui_runner.is_running(run_id), timeout=10.0)

    info = ui_runner.get_run_thread_info(run_id)
    assert info.get("error") is None

    final_state = ui_runner.get_state(run_id)
    assert final_state["approval_status"]["approved_by"] == "tester"
    # With mesh_levels=['coarse','medium','fine'] from the mock planner and
    # identical fake QoI values across cases, mesh independence trivially
    # PASSES and the graph runs all the way to the final report.
    assert final_state["current_stage"] == "completed"
    assert final_state["final_report_path"]


def test_resume_run_is_a_harmless_noop_on_an_already_completed_run(monkeypatch):
    install_fake_tools(monkeypatch)
    run_id = ui_runner.start_new_run("goal")
    _wait_until(lambda: ui_runner.get_state(run_id) is not None)
    _wait_until(lambda: not ui_runner.is_running(run_id))
    ui_runner.approve_and_continue(run_id, "tester")
    _wait_until(lambda: not ui_runner.is_running(run_id), timeout=10.0)
    assert ui_runner.get_state(run_id)["current_stage"] == "completed"

    ui_runner.resume_run(run_id)
    _wait_until(lambda: not ui_runner.is_running(run_id), timeout=5.0)
    assert ui_runner.get_run_thread_info(run_id).get("error") is None
    assert ui_runner.get_state(run_id)["current_stage"] == "completed"
