import json
import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from eval.judge import (
    CompletedHumanAudit,
    JudgeRecord,
    JudgeSample,
    JudgeScore,
    judge_narratives,
    load_completed_human_audit,
    select_human_audit_sample,
    summarize_judges,
    validate_completed_human_audit,
)

DIMENSIONS = (
    "groundedness",
    "relevance",
    "completeness",
    "action_safety",
    "clarity",
)


def _score(value: int, *, rationale: str = "Evidence-backed assessment.") -> JudgeScore:
    return JudgeScore(
        groundedness=value,
        relevance=value,
        completeness=value,
        action_safety=value,
        clarity=value,
        rationale=rationale,
    )


def _sample(case_id: str = "P210-SECRET-CASE") -> JudgeSample:
    return JudgeSample(
        case_id=case_id,
        cohort="HOLDOUT",
        typed_observations={
            "outcome": "INSUFFICIENT_EVIDENCE",
            "selected_tools": ["inspect_route"],
            "provider_mode": "LIVE",
        },
        expected_limitations=["Do not claim deterministic feasibility."],
        narrative="The route evidence is incomplete, so new evidence is required.",
    )


class _FakeResponses:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(
            id=f"response-{len(self.calls)}",
            model="returned-judge-model",
            output_parsed=result,
        )


class _FakeClient:
    def __init__(self, results):
        self.responses = _FakeResponses(results)


class _CloneableFakeClient(_FakeClient):
    def __init__(self, results):
        super().__init__(results)
        self.max_retries = 2
        self.with_options_calls = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        clone = SimpleNamespace(max_retries=kwargs["max_retries"])
        clone.responses = self.responses
        return clone


@pytest.mark.asyncio
async def test_judge_uses_two_independent_structured_passes_and_blind_input():
    first = _score(5, rationale="First raw rationale")
    second = _score(4, rationale="Second raw rationale")
    client = _FakeClient([first, second])

    records = await judge_narratives(
        [_sample()], client=client, model="requested-model", prompt_text="rubric"
    )

    assert [record.pass_number for record in records] == [1, 2]
    assert [record.scores.rationale for record in records] == [
        "First raw rationale",
        "Second raw rationale",
    ]
    assert all(record.raw_scores == record.scores.model_dump() for record in records)
    assert all(record.model == "returned-judge-model" for record in records)
    assert all(record.retry_count == 0 for record in records)
    assert len(client.responses.calls) == 2
    assert all(call["text_format"] is JudgeScore for call in client.responses.calls)
    assert all(call["timeout"] > 0 for call in client.responses.calls)
    assert all("previous_response_id" not in call for call in client.responses.calls)
    for call in client.responses.calls:
        payload = json.loads(call["input"])
        serialized = json.dumps(payload)
        assert "P210-SECRET-CASE" not in serialized
        assert "case_id" not in serialized
        assert "golden_final_score" not in serialized
        assert set(payload) == {
            "typed_observations",
            "expected_limitations",
            "narrative",
        }


@pytest.mark.asyncio
async def test_judge_retries_a_transport_or_schema_error_at_most_once():
    client = _FakeClient([ValueError("schema mismatch"), _score(4), _score(5)])

    records = await judge_narratives(
        [_sample()], client=client, model="judge", prompt_text="rubric"
    )

    assert len(client.responses.calls) == 3
    assert [record.retry_count for record in records] == [1, 0]

    failing_client = _FakeClient([ValueError("first"), ValueError("second")])
    with pytest.raises(RuntimeError, match="failed after one retry"):
        await judge_narratives(
            [_sample()],
            client=failing_client,
            model="judge",
            prompt_text="rubric",
            passes=1,
        )
    assert len(failing_client.responses.calls) == 2


@pytest.mark.asyncio
async def test_judge_disables_sdk_internal_retries_before_its_single_retry_loop():
    client = _CloneableFakeClient([ValueError("first"), ValueError("second")])

    with pytest.raises(RuntimeError, match="failed after one retry"):
        await judge_narratives(
            [_sample()],
            client=client,
            model="judge",
            prompt_text="rubric",
            passes=1,
        )

    assert client.with_options_calls == [{"max_retries": 0}]
    assert len(client.responses.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_key",
    ["caseId", "CASE-ID", "Case_Id", "goldenFinalScore", "GOLDEN-final_score"],
)
async def test_judge_normalizes_forbidden_key_spellings(forbidden_key: str):
    sample = _sample().model_copy(
        update={"typed_observations": {"nested": {forbidden_key: "hidden"}}}
    )
    client = _FakeClient([])

    with pytest.raises(ValueError, match="forbidden identifier or final-score key"):
        await judge_narratives(
            [sample], client=client, model="judge", prompt_text="rubric"
        )

    assert client.responses.calls == []


@pytest.mark.asyncio
async def test_judge_casefolds_case_identifier_occurrence_before_sending():
    sample = _sample("P210-MiXeD-CaSe").model_copy(
        update={"narrative": "The opaque reference p210-mixed-case must stay local."}
    )
    client = _FakeClient([])

    with pytest.raises(ValueError, match="local case identifier"):
        await judge_narratives(
            [sample], client=client, model="judge", prompt_text="rubric"
        )

    assert client.responses.calls == []


def test_score_validation_and_pass_require_all_five_dimensions_at_least_four():
    with pytest.raises(ValidationError):
        _score(6)

    passing = JudgeRecord.from_score(
        sample=_sample("passing"),
        pass_number=1,
        model="judge",
        response_id="response-pass",
        score=_score(4),
        retry_count=0,
    )
    failing_score = _score(4).model_copy(update={"clarity": 3})
    failing = JudgeRecord.from_score(
        sample=_sample("failing"),
        pass_number=1,
        model="judge",
        response_id="response-fail",
        score=failing_score,
        retry_count=0,
    )

    assert passing.passed is True
    assert failing.passed is False


def _record(
    case_id: str,
    cohort: str,
    pass_number: int,
    values: tuple[int, int, int, int, int],
) -> JudgeRecord:
    score = JudgeScore(
        **dict(zip(DIMENSIONS, values, strict=True)),
        rationale=f"raw-{case_id}-{pass_number}",
    )
    return JudgeRecord.from_score(
        sample=_sample(case_id).model_copy(update={"cohort": cohort}),
        pass_number=pass_number,
        model="judge",
        response_id=f"response-{case_id}-{pass_number}",
        score=score,
        retry_count=0,
    )


def test_summary_reports_dimension_and_aggregate_weighted_kappa():
    records = [
        _record("a", "MENTOR_REMEDIATION", 1, (1, 2, 3, 4, 5)),
        _record("a", "MENTOR_REMEDIATION", 2, (1, 2, 3, 4, 5)),
        _record("b", "HOLDOUT", 1, (5, 4, 3, 2, 1)),
        _record("b", "HOLDOUT", 2, (5, 4, 3, 2, 1)),
    ]

    summary = summarize_judges(records)

    assert summary["record_count"] == 4
    assert summary["case_count"] == 2
    assert summary["dimensions"]["groundedness"]["weighted_kappa"] == 1.0
    assert summary["dimensions"]["clarity"]["weighted_kappa"] == 1.0
    assert summary["aggregate_weighted_kappa"] == 1.0
    assert summary["record_pass_rate"] == 0.0
    assert summary["case_pass_rate"] == 0.0


def test_summary_rejects_duplicate_non_null_response_ids():
    first = _record("duplicate-response", "HOLDOUT", 1, (4, 4, 4, 4, 4))
    second = _record("duplicate-response", "HOLDOUT", 2, (4, 4, 4, 4, 4))
    second = second.model_copy(update={"response_id": first.response_id})

    with pytest.raises(ValueError, match="duplicate non-null response_id"):
        summarize_judges([first, second])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("cohort", "BOUNDARY"),
        ("typed_observations", {"outcome": "TAMPERED"}),
        ("expected_limitations", ["Tampered limitation"]),
        ("narrative", "Tampered narrative"),
    ],
)
def test_summary_rejects_mismatched_sample_provenance_between_passes(
    field: str, replacement
):
    first = _record("paired-case", "HOLDOUT", 1, (4, 4, 4, 4, 4))
    second = _record("paired-case", "HOLDOUT", 2, (4, 4, 4, 4, 4))
    second = second.model_copy(update={field: replacement})

    with pytest.raises(ValueError, match=f"mismatched {field}"):
        summarize_judges([first, second])


def test_human_audit_sample_is_deterministic_stratified_blind_and_ceil_twenty_percent():
    cohorts = ["MENTOR_REMEDIATION", "BOUNDARY", "FAILURE_LIFECYCLE", "HOLDOUT"]
    records = []
    for index in range(21):
        value = 5 if index % 2 == 0 else 3
        records.append(
            _record(
                f"case-{index:02d}",
                cohorts[index % len(cohorts)],
                1,
                (value, value, value, value, value),
            )
        )

    first = select_human_audit_sample(records, seed=210)
    second = select_human_audit_sample(records, seed=210)

    assert first == second
    assert len(first) == math.ceil(len(records) * 0.20)
    assert {item["cohort"] for item in first} == set(cohorts)
    serialized = json.dumps(first)
    assert "case-" not in serialized
    assert "raw_scores" not in serialized
    assert "rationale" not in serialized
    assert '"passed"' not in serialized
    assert all(item["reviewer"] is None for item in first)
    assert all(item["reviewed_at"] is None for item in first)
    assert all(item["notes"] is None for item in first)
    assert all(item[dimension] is None for item in first for dimension in DIMENSIONS)


def test_human_audit_sampling_covers_pass_and_fail_strata_when_capacity_allows():
    records = []
    for index in range(6):
        value = 5 if index < 3 else 3
        record = _record(
            f"stratum-{index}",
            "HOLDOUT",
            1,
            (value, value, value, value, value),
        )
        marker = "pass" if record.passed else "fail"
        records.append(
            record.model_copy(update={"typed_observations": {"marker": marker}})
        )

    selected = select_human_audit_sample(records)

    assert len(selected) == 2
    assert {item["typed_observations"]["marker"] for item in selected} == {
        "pass",
        "fail",
    }


def _complete_sample(sample: dict) -> dict:
    return {
        **sample,
        "reviewer": "Independent Reviewer",
        "reviewed_at": datetime(2026, 9, 1, 10, 0, tzinfo=UTC).isoformat(),
        "groundedness": 4,
        "relevance": 4,
        "completeness": 4,
        "action_safety": 5,
        "clarity": 4,
        "notes": "Checked against the blind evidence package.",
    }


def _issued_samples(total_records: int = 10) -> list[dict]:
    records = [
        _record(f"audit-source-{index}", "HOLDOUT", 1, (4, 4, 4, 4, 4))
        for index in range(total_records)
    ]
    return select_human_audit_sample(records)


def test_completed_human_audit_requires_reviewer_timestamp_scores_notes_and_coverage():
    issued = _issued_samples()
    completed = [_complete_sample(sample) for sample in issued]

    validated = validate_completed_human_audit(
        completed, expected_samples=issued, total_records=10
    )

    assert all(isinstance(record, CompletedHumanAudit) for record in validated)

    for missing in ("reviewer", "reviewed_at", *DIMENSIONS, "notes"):
        one_issued = _issued_samples(total_records=1)
        incomplete = _complete_sample(one_issued[0])
        del incomplete[missing]
        with pytest.raises(ValueError, match=missing):
            validate_completed_human_audit(
                [incomplete], expected_samples=one_issued, total_records=1
            )

    with pytest.raises(ValueError, match="missing issued audit_id"):
        validate_completed_human_audit(
            completed[:1], expected_samples=issued, total_records=10
        )


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("cohort", "BOUNDARY"),
        ("typed_observations", {"outcome": "TAMPERED"}),
        ("expected_limitations", ["Tampered limitation"]),
        ("narrative", "Tampered narrative"),
        ("rubric", "Tampered rubric"),
    ],
)
def test_completed_human_audit_rejects_tampered_provenance(field: str, tampered):
    issued = _issued_samples(total_records=1)
    completed = _complete_sample(issued[0])
    completed[field] = tampered

    with pytest.raises(ValueError, match=f"tampered immutable field {field}"):
        validate_completed_human_audit(
            [completed], expected_samples=issued, total_records=1
        )


def test_completed_human_audit_rejects_fabricated_ids_and_underissued_samples():
    issued = _issued_samples(total_records=1)
    fabricated = _complete_sample(issued[0])
    fabricated["audit_id"] = "fabricated-audit-id"

    with pytest.raises(ValueError, match="unknown or fabricated audit_id"):
        validate_completed_human_audit(
            [fabricated], expected_samples=issued, total_records=1
        )

    with pytest.raises(ValueError, match="issued sample set must contain at least 2"):
        validate_completed_human_audit(
            [_complete_sample(issued[0])],
            expected_samples=issued,
            total_records=10,
        )


def test_completed_human_audit_loader_rejects_missing_file_and_reads_jsonl(tmp_path: Path):
    path = tmp_path / "human_audit_completed.jsonl"
    issued = _issued_samples(total_records=1)
    with pytest.raises(FileNotFoundError, match="human audit file is missing"):
        load_completed_human_audit(
            path, expected_samples=issued, total_records=1
        )

    path.write_text(
        json.dumps(_complete_sample(issued[0])) + "\n", encoding="utf-8"
    )

    completed = load_completed_human_audit(
        path, expected_samples=issued, total_records=1
    )

    assert completed[0].reviewer == "Independent Reviewer"
