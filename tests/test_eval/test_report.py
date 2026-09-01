"""Unit tests for F3/F4 evaluation report generation and CLI orchestrator."""


from eval.report import (
    load_artifact,
    render_markdown_report,
    resolve_run_id,
    save_current_run_id,
    write_artifact,
)


def test_save_and_resolve_current_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr("eval.report.RESULTS_DIR", tmp_path)
    save_current_run_id("test-run-123")
    assert resolve_run_id("current") == "test-run-123"
    assert resolve_run_id("explicit-run-456") == "explicit-run-456"


def test_write_and_load_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("eval.report.RESULTS_DIR", tmp_path)
    save_current_run_id("run-xyz")

    data = {"metric": "accuracy", "value": 0.95}
    written_path = write_artifact("run-xyz", "summary.json", data)
    assert written_path.exists()

    loaded = load_artifact("run-xyz", "summary.json")
    assert loaded == data

    loaded_via_current = load_artifact("current", "summary.json")
    assert loaded_via_current == data


def test_render_markdown_report():
    manifest = {
        "run_id": "test-run-789",
        "commit_sha": "2eeda96",
        "dirty_worktree": False,
        "started_at": "2026-09-01T12:00:00Z",
        "dataset_version": "f3-f4-golden-v1",
        "runner_version": "0.1.0",
    }
    accuracy_summary = {
        "case_count": 60,
        "exact_match": {"outcome": 0.92},
        "safety_gate_passed": True,
        "infeasible": {"recall": 1.0},
        "cohorts": {
            "MENTOR_REMEDIATION": {
                "case_count": 20,
                "exact_match": {"outcome": 0.95},
                "safety_gate_passed": True,
            },
            "HOLDOUT": {
                "case_count": 40,
                "exact_match": {"outcome": 0.90},
                "safety_gate_passed": True,
            },
        },
    }
    load_summary = {
        "workloads": [
            {"workload": "F3_TICK", "concurrency": 1, "p95_ms": 120.5},
            {"workload": "F4_DETERMINISTIC", "concurrency": 20, "p95_ms": 150.0},
        ]
    }
    availability_summary = {
        "availability_percent": 99.5,
        "mttr_seconds": 2.1,
    }

    report = render_markdown_report(
        manifest=manifest,
        accuracy_summary=accuracy_summary,
        load_summary=load_summary,
        availability_summary=availability_summary,
    )

    assert "# F3/F4 Local Evaluation Benchmark Report" in report
    assert "test-run-789" in report
    assert "92.0%" in report
    assert "120.5ms" in report
    assert "99.50%" in report
    assert "MENTOR_REMEDIATION" in report
    assert "HOLDOUT" in report
