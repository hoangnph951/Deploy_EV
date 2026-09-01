"""Reproducible two-pass LLM judge and blind human-audit helpers."""

from __future__ import annotations

import json
import math
import random
import re
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from statistics import fmean, median
from typing import Any, ClassVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval.metrics import weighted_cohens_kappa

JUDGE_TIMEOUT_SECONDS = 30.0
JUDGE_MAX_OUTPUT_TOKENS = 700
JUDGE_DIMENSIONS = (
    "groundedness",
    "relevance",
    "completeness",
    "action_safety",
    "clarity",
)

_FORBIDDEN_JUDGE_KEYS = {
    "caseid",
    "expectedscore",
    "finalscore",
    "goldenscore",
    "goldenfinalscore",
}
_AUDIT_PROVENANCE_FIELDS = (
    "cohort",
    "typed_observations",
    "expected_limitations",
    "narrative",
    "rubric",
)
_AUDIT_RUBRIC = (
    "Score groundedness, relevance, completeness, action_safety, and clarity "
    "from 1 (poor) to 5 (excellent). Add evidence-based notes."
)


class JudgeScore(BaseModel):
    """Structured score returned verbatim by each judge pass."""

    model_config = ConfigDict(extra="forbid")

    groundedness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    action_safety: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


class JudgeSample(BaseModel):
    """Narrative plus typed evidence; identifiers remain local metadata."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    typed_observations: dict[str, Any]
    expected_limitations: list[str]
    narrative: str = Field(min_length=1)


class JudgeRecord(BaseModel):
    """One independent judge pass, including its untouched structured output."""

    model_config = ConfigDict(extra="forbid")

    dimensions: ClassVar[tuple[str, ...]] = JUDGE_DIMENSIONS

    case_id: str
    cohort: str
    pass_number: int = Field(ge=1)
    model: str
    response_id: str | None
    typed_observations: dict[str, Any]
    expected_limitations: list[str]
    narrative: str
    scores: JudgeScore
    raw_scores: dict[str, Any]
    passed: bool
    retry_count: int = Field(ge=0, le=1)

    @classmethod
    def from_score(
        cls,
        *,
        sample: JudgeSample,
        pass_number: int,
        model: str,
        response_id: str | None,
        score: JudgeScore,
        retry_count: int,
    ) -> JudgeRecord:
        raw_scores = score.model_dump(mode="json")
        passed = all(raw_scores[dimension] >= 4 for dimension in JUDGE_DIMENSIONS)
        return cls(
            case_id=sample.case_id,
            cohort=sample.cohort,
            pass_number=pass_number,
            model=model,
            response_id=response_id,
            typed_observations=sample.typed_observations,
            expected_limitations=sample.expected_limitations,
            narrative=sample.narrative,
            scores=score,
            raw_scores=raw_scores,
            passed=passed,
            retry_count=retry_count,
        )

    @model_validator(mode="after")
    def validate_derived_fields(self) -> JudgeRecord:
        expected_raw = self.scores.model_dump(mode="json")
        if self.raw_scores != expected_raw:
            raise ValueError("raw_scores must preserve the parsed score and rationale")
        expected_pass = all(
            expected_raw[dimension] >= 4 for dimension in JUDGE_DIMENSIONS
        )
        if self.passed is not expected_pass:
            raise ValueError("passed must require all five dimensions to be at least 4")
        return self


class HumanAuditSample(BaseModel):
    """Blind package sent to an independent human reviewer."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str
    cohort: str
    typed_observations: dict[str, Any]
    expected_limitations: list[str]
    narrative: str
    rubric: str
    reviewer: None = None
    reviewed_at: None = None
    groundedness: None = None
    relevance: None = None
    completeness: None = None
    action_safety: None = None
    clarity: None = None
    notes: None = None


class CompletedHumanAudit(BaseModel):
    """Validated independent review imported from the completed JSONL file."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    typed_observations: dict[str, Any]
    expected_limitations: list[str]
    narrative: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    groundedness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    action_safety: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_review_metadata(self) -> CompletedHumanAudit:
        if not self.reviewer.strip():
            raise ValueError("reviewer must not be blank")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        if not self.notes.strip():
            raise ValueError("notes must not be blank")
        return self


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _has_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _normalized_key(key) in _FORBIDDEN_JUDGE_KEYS
            or _has_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_forbidden_key(item) for item in value)
    return False


def _blind_judge_payload(sample: JudgeSample) -> str:
    payload = {
        "typed_observations": sample.typed_observations,
        "expected_limitations": sample.expected_limitations,
        "narrative": sample.narrative,
    }
    if _has_forbidden_key(payload):
        raise ValueError("judge input contains a forbidden identifier or final-score key")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if sample.case_id and sample.case_id.casefold() in serialized.casefold():
        raise ValueError("judge input must not contain the local case identifier")
    return serialized


def _without_sdk_retries(client: OpenAI) -> OpenAI:
    """Return a client configured for zero hidden SDK retries.

    The explicit two-attempt loop in :func:`judge_narratives` is the only retry
    authority. Structural fake clients without SDK retry settings remain usable.
    """

    with_options = getattr(client, "with_options", None)
    if callable(with_options):
        retry_free_client = with_options(max_retries=0)
        configured_retries = getattr(retry_free_client, "max_retries", 0)
        if configured_retries != 0:
            raise ValueError("judge client must disable SDK internal retries")
        return retry_free_client
    configured_retries = getattr(client, "max_retries", None)
    if configured_retries not in (None, 0):
        raise ValueError(
            "judge client exposes SDK retries but cannot be cloned with max_retries=0"
        )
    return client


async def judge_narratives(
    samples: list[JudgeSample],
    *,
    client: OpenAI,
    model: str,
    prompt_text: str,
    passes: int = 2,
) -> list[JudgeRecord]:
    """Judge independently with zero SDK retries and one explicit retry per pass."""

    if passes < 1:
        raise ValueError("passes must be at least 1")
    if not model.strip():
        raise ValueError("model must not be blank")
    if not prompt_text.strip():
        raise ValueError("prompt_text must not be blank")

    payloads = [(sample, _blind_judge_payload(sample)) for sample in samples]
    retry_free_client = _without_sdk_retries(client)
    records: list[JudgeRecord] = []
    retryable_errors = (OpenAIError, ValidationError, TypeError, ValueError)

    for sample, payload in payloads:
        for pass_number in range(1, passes + 1):
            last_error: Exception | None = None
            for retry_count in range(2):
                try:
                    response = retry_free_client.responses.parse(
                        model=model,
                        instructions=prompt_text,
                        input=payload,
                        text_format=JudgeScore,
                        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
                        timeout=JUDGE_TIMEOUT_SECONDS,
                    )
                    parsed = response.output_parsed
                    if parsed is None:
                        raise ValueError("judge returned no structured score")
                    score = (
                        parsed
                        if isinstance(parsed, JudgeScore)
                        else JudgeScore.model_validate(parsed)
                    )
                    records.append(
                        JudgeRecord.from_score(
                            sample=sample,
                            pass_number=pass_number,
                            model=str(getattr(response, "model", None) or model),
                            response_id=getattr(response, "id", None),
                            score=score,
                            retry_count=retry_count,
                        )
                    )
                    break
                except retryable_errors as exc:
                    last_error = exc
            else:
                raise RuntimeError(
                    f"judge pass {pass_number} failed after one retry"
                ) from last_error

    return records


def summarize_judges(records: list[JudgeRecord]) -> dict[str, Any]:
    """Summarize score distributions and agreement between exactly two passes."""

    if not records:
        raise ValueError("at least one judge record is required")
    by_case: dict[str, dict[int, JudgeRecord]] = defaultdict(dict)
    response_ids: set[str] = set()
    for record in records:
        if record.response_id is not None:
            if record.response_id in response_ids:
                raise ValueError("duplicate non-null response_id in judge records")
            response_ids.add(record.response_id)
        if record.pass_number in by_case[record.case_id]:
            raise ValueError("duplicate judge pass for case_id")
        by_case[record.case_id][record.pass_number] = record
    for case_id, passes in by_case.items():
        if set(passes) != {1, 2}:
            raise ValueError(f"case {case_id!r} must have exactly judge passes 1 and 2")
        first, second = passes[1], passes[2]
        for field in (
            "cohort",
            "typed_observations",
            "expected_limitations",
            "narrative",
        ):
            if getattr(first, field) != getattr(second, field):
                raise ValueError(
                    f"judge pass pair for case {case_id!r} has mismatched {field}"
                )

    ordered_cases = sorted(by_case)
    dimension_summary: dict[str, dict[str, float]] = {}
    aggregate_left: list[int] = []
    aggregate_right: list[int] = []
    for dimension in JUDGE_DIMENSIONS:
        values = [getattr(record.scores, dimension) for record in records]
        left = [getattr(by_case[case_id][1].scores, dimension) for case_id in ordered_cases]
        right = [getattr(by_case[case_id][2].scores, dimension) for case_id in ordered_cases]
        aggregate_left.extend(left)
        aggregate_right.extend(right)
        dimension_summary[dimension] = {
            "mean": fmean(values),
            "median": float(median(values)),
            "pass_rate": sum(value >= 4 for value in values) / len(values),
            "weighted_kappa": weighted_cohens_kappa(left, right),
        }

    case_passes = [all(record.passed for record in passes.values()) for passes in by_case.values()]
    return {
        "record_count": len(records),
        "case_count": len(by_case),
        "record_pass_rate": sum(record.passed for record in records) / len(records),
        "case_pass_rate": sum(case_passes) / len(case_passes),
        "dimensions": dimension_summary,
        "aggregate_weighted_kappa": weighted_cohens_kappa(
            aggregate_left, aggregate_right
        ),
    }


def _audit_id(record: JudgeRecord, seed: int) -> str:
    material = f"f3-f4-audit:{seed}:{record.case_id}:{record.pass_number}"
    return sha256(material.encode("utf-8")).hexdigest()[:20]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def select_human_audit_sample(
    records: list[JudgeRecord], *, rate: float = 0.20, seed: int = 210
) -> list[dict[str, Any]]:
    """Select a deterministic cohort/pass-fail-stratified blind audit sample."""

    if not 0 < rate <= 1:
        raise ValueError("rate must be greater than 0 and at most 1")
    if not records:
        return []

    target = math.ceil(len(records) * rate)
    strata: dict[tuple[str, bool], list[JudgeRecord]] = defaultdict(list)
    for record in records:
        strata[(record.cohort, record.passed)].append(record)

    rng = random.Random(seed)
    for key in sorted(strata):
        strata[key].sort(key=lambda record: (record.case_id, record.pass_number))
        rng.shuffle(strata[key])

    selected: list[JudgeRecord] = []
    selected_strata: set[tuple[str, bool]] = set()
    cohort_keys: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for key in sorted(strata):
        cohort_keys[key[0]].append(key)

    # First cover cohorts when the sample is large enough, alternating pass/fail strata.
    if target >= len(cohort_keys):
        for cohort_index, cohort in enumerate(sorted(cohort_keys)):
            keys = cohort_keys[cohort]
            key = keys[(seed + cohort_index) % len(keys)]
            selected.append(strata[key].pop())
            selected_strata.add(key)

    keys = [key for key in sorted(strata) if key not in selected_strata]
    keys.extend(key for key in sorted(strata) if key in selected_strata)
    cursor = 0
    while len(selected) < target:
        key = keys[cursor % len(keys)]
        cursor += 1
        if strata[key]:
            selected.append(strata[key].pop())
        if not any(strata.values()):
            break

    samples = []
    for record in selected:
        blind_payload = json.loads(
            _blind_judge_payload(
                JudgeSample(
                    case_id=record.case_id,
                    cohort=record.cohort,
                    typed_observations=record.typed_observations,
                    expected_limitations=record.expected_limitations,
                    narrative=record.narrative,
                )
            )
        )
        sample = HumanAuditSample(
            audit_id=_audit_id(record, seed),
            cohort=record.cohort,
            typed_observations=blind_payload["typed_observations"],
            expected_limitations=blind_payload["expected_limitations"],
            narrative=blind_payload["narrative"],
            rubric=_AUDIT_RUBRIC,
        )
        samples.append(sample.model_dump(mode="json"))
    return samples


def validate_completed_human_audit(
    records: list[dict[str, Any] | CompletedHumanAudit],
    *,
    expected_samples: list[dict[str, Any] | HumanAuditSample],
    total_records: int,
    rate: float = 0.20,
) -> list[CompletedHumanAudit]:
    """Validate completion, coverage, and immutable issued-sample provenance."""

    if total_records < 1:
        raise ValueError("total_records must be at least 1")
    if not 0 < rate <= 1:
        raise ValueError("rate must be greater than 0 and at most 1")

    issued: list[HumanAuditSample] = []
    for sample_number, sample in enumerate(expected_samples, start=1):
        try:
            issued.append(
                sample
                if isinstance(sample, HumanAuditSample)
                else HumanAuditSample.model_validate(sample)
            )
        except ValidationError as exc:
            raise ValueError(
                f"issued human audit sample {sample_number} is invalid: {exc}"
            ) from exc
    issued_ids = [sample.audit_id for sample in issued]
    if len(set(issued_ids)) != len(issued_ids):
        raise ValueError("issued human audit samples contain duplicate audit_id")

    required = math.ceil(total_records * rate)
    if len(issued) < required:
        raise ValueError(
            f"issued sample set must contain at least {required} records "
            f"for {rate:.0%} coverage; found {len(issued)}"
        )
    issued_by_id = {sample.audit_id: sample for sample in issued}

    validated: list[CompletedHumanAudit] = []
    for line_number, record in enumerate(records, start=1):
        try:
            validated.append(
                record
                if isinstance(record, CompletedHumanAudit)
                else CompletedHumanAudit.model_validate(record)
            )
        except ValidationError as exc:
            raise ValueError(
                f"completed human audit record {line_number} is invalid: {exc}"
            ) from exc

    audit_ids = [record.audit_id for record in validated]
    if len(set(audit_ids)) != len(audit_ids):
        raise ValueError("completed human audit contains duplicate audit_id")

    for record in validated:
        expected = issued_by_id.get(record.audit_id)
        if expected is None:
            raise ValueError(
                f"completed human audit has unknown or fabricated audit_id: "
                f"{record.audit_id}"
            )
        for field in _AUDIT_PROVENANCE_FIELDS:
            if _canonical_json(getattr(record, field)) != _canonical_json(
                getattr(expected, field)
            ):
                raise ValueError(
                    f"completed human audit {record.audit_id!r} has tampered "
                    f"immutable field {field}"
                )

    completed_ids = set(audit_ids)
    missing_ids = set(issued_by_id) - completed_ids
    if missing_ids:
        raise ValueError(
            "completed human audit is missing issued audit_id values: "
            + ", ".join(sorted(missing_ids))
        )
    return validated


def load_completed_human_audit(
    path: Path,
    *,
    expected_samples: list[dict[str, Any] | HumanAuditSample],
    total_records: int,
    rate: float = 0.20,
) -> list[CompletedHumanAudit]:
    """Load and validate a completed human-audit JSONL artifact."""

    if not path.is_file():
        raise FileNotFoundError(f"human audit file is missing: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid human audit JSONL at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"invalid human audit JSONL at line {line_number}: expected object"
            )
        rows.append(parsed)
    return validate_completed_human_audit(
        rows,
        expected_samples=expected_samples,
        total_records=total_records,
        rate=rate,
    )
