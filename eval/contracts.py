"""Typed contracts shared by the F3/F4 evaluation runners."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GoldenCase(BaseModel):
    """One deterministically labelled F3/F4 evaluation scenario."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    source: Literal[
        "MENTOR_REMEDIATION", "BOUNDARY", "FAILURE_LIFECYCLE", "HOLDOUT"
    ]
    category: Literal[
        "F3_CLASSIFY", "F3_API", "F4_REPLAN", "F4_LIFECYCLE", "F4_SECURITY"
    ]
    input_snapshot: dict[str, Any]
    expected_events: list[str]
    expected_constraints: dict[str, Any]
    required_tools: list[str]
    forbidden_tools: list[str]
    expected_outcome: str
    expected_action: str | None
    expected_lifecycle: str | None
    ground_truth_method: str
    label_notes: str
    dataset_version: Literal["f3-f4-golden-v1"]


class MachineMetadata(BaseModel):
    """Stable machine details needed to interpret a local benchmark run."""

    model_config = ConfigDict(extra="forbid")

    platform: str
    python_version: str
    cpu_count: int | None


class EvaluationManifest(BaseModel):
    """Provenance captured once for every evaluation run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    commit_sha: str
    dirty_worktree: bool
    started_at: datetime
    machine: MachineMetadata
    dataset_version: str
    runner_version: str
    judge_model: str | None
    judge_prompt_version: str | None
    provider_modes: dict[str, str]
    diff_hash: str | None = None
    stages: dict[str, "EvaluationStage"] = Field(default_factory=dict)
    artifact_checksums: dict[str, str] = Field(default_factory=dict)


class EvaluationStage(BaseModel):
    """Durable status for a resumable evaluation stage."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_class: str | None = None
    error_message: str | None = None
