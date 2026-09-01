import json
from pathlib import Path

import pytest

from eval.dataset import build_manifest, load_golden_cases

GOLDEN_V1 = Path(__file__).resolve().parents[2] / "eval" / "datasets" / "f3_f4_golden_v1.jsonl"


def _case(case_id: str, source: str, **overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "case_id": case_id,
        "source": source,
        "category": "F3_CLASSIFY",
        "input_snapshot": {},
        "expected_events": [],
        "expected_constraints": {},
        "required_tools": [],
        "forbidden_tools": [],
        "expected_outcome": "NO_ACTION",
        "expected_action": None,
        "expected_lifecycle": None,
        "ground_truth_method": "deterministic-oracle",
        "label_notes": "Fixture case.",
        "dataset_version": "f3-f4-golden-v1",
    }
    case.update(overrides)
    return case


def _write_cases(tmp_path, cases: list[dict[str, object]]):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
    )
    return dataset


def _one_case_per_source(**overrides: object) -> list[dict[str, object]]:
    sources = [
        "MENTOR_REMEDIATION",
        "BOUNDARY",
        "FAILURE_LIFECYCLE",
        "HOLDOUT",
    ]
    return [
        _case(f"case-{index}", source, **(overrides if index == 1 else {}))
        for index, source in enumerate(sources, start=1)
    ]


def test_loader_rejects_duplicate_case_ids(tmp_path):
    cases = _one_case_per_source()
    cases[-1]["case_id"] = cases[0]["case_id"]

    with pytest.raises(ValueError, match=r"line 4.*duplicate case_id.*case-1"):
        load_golden_cases(_write_cases(tmp_path, cases))


def test_loader_rejects_unknown_dataset_version(tmp_path):
    cases = _one_case_per_source(dataset_version="f3-f4-golden-v2")

    with pytest.raises(ValueError, match=r"(?s)line 1.*dataset_version"):
        load_golden_cases(_write_cases(tmp_path, cases))


@pytest.mark.parametrize("missing_field", ["ground_truth_method", "label_notes"])
def test_loader_requires_ground_truth_method_and_label_notes(tmp_path, missing_field):
    cases = _one_case_per_source()
    del cases[0][missing_field]

    with pytest.raises(ValueError, match=rf"(?s)line 1.*{missing_field}"):
        load_golden_cases(_write_cases(tmp_path, cases))


def test_manifest_records_sha_machine_and_dirty_state(monkeypatch):
    def fake_git(args: list[str]) -> str:
        if args == ["rev-parse", "HEAD"]:
            return "abc123\n"
        if args == ["status", "--porcelain"]:
            return " M changed.py\n"
        if args == ["diff", "--binary", "HEAD"]:
            return "diff --git a/changed.py b/changed.py\n"
        raise AssertionError(f"Unexpected git command: {args}")

    monkeypatch.setattr("eval.dataset._run_git", fake_git)
    monkeypatch.setattr("eval.dataset.platform.platform", lambda: "TestOS-1")
    monkeypatch.setattr("eval.dataset.sys.version", "Python test")
    monkeypatch.setattr("eval.dataset.os.cpu_count", lambda: 8)

    manifest = build_manifest(
        dataset_version="f3-f4-golden-v1", judge_model="gpt-test"
    )

    assert manifest.commit_sha == "abc123"
    assert manifest.dirty_worktree is True
    assert manifest.machine.platform == "TestOS-1"
    assert manifest.machine.python_version == "Python test"
    assert manifest.machine.cpu_count == 8
    assert manifest.dataset_version == "f3-f4-golden-v1"
    assert manifest.judge_model == "gpt-test"
    assert manifest.diff_hash is not None
    assert len(manifest.diff_hash) == 64


def test_golden_v1_has_at_least_60_cases():
    cases = load_golden_cases(GOLDEN_V1)

    assert len(cases) >= 60
    assert {case.dataset_version for case in cases} == {"f3-f4-golden-v1"}
