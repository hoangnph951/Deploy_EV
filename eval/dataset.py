"""Golden JSONL loading and run-manifest construction."""

import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from eval.contracts import EvaluationManifest, GoldenCase, MachineMetadata

RUNNER_VERSION = "f3-f4-evaluation-runner-v1"
REQUIRED_SOURCES = frozenset(
    {"MENTOR_REMEDIATION", "BOUNDARY", "FAILURE_LIFECYCLE", "HOLDOUT"}
)


def load_golden_cases(path: Path) -> list[GoldenCase]:
    """Load and validate a versioned golden JSONL dataset.

    Validation errors retain the source line number so a faulty record can be
    corrected without losing the rest of the dataset context.
    """

    cases: list[GoldenCase] = []
    case_ids: set[str] = set()

    with path.open(encoding="utf-8") as dataset:
        for line_number, raw_line in enumerate(dataset, start=1):
            if not raw_line.strip():
                continue

            try:
                record = json.loads(raw_line)
                case = GoldenCase.model_validate(record)
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(
                    f"{path}: line {line_number}: invalid golden case: {exc}"
                ) from exc

            if case.case_id in case_ids:
                raise ValueError(
                    f"{path}: line {line_number}: duplicate case_id {case.case_id!r}"
                )

            case_ids.add(case.case_id)
            cases.append(case)

    present_sources = {case.source for case in cases}
    missing_sources = sorted(REQUIRED_SOURCES - present_sources)
    if missing_sources:
        raise ValueError(
            f"{path}: dataset must include at least one case for each source; "
            f"missing: {', '.join(missing_sources)}"
        )

    return cases


def _run_git(args: list[str]) -> str:
    """Run git from the current repository and return stdout."""

    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        command = "git " + " ".join(args)
        raise RuntimeError(f"Unable to run {command} for evaluation manifest") from exc
    return result.stdout


def build_manifest(*, dataset_version: str, judge_model: str | None) -> EvaluationManifest:
    """Capture reproducibility metadata for a local benchmark run."""

    commit_sha = _run_git(["rev-parse", "HEAD"]).strip()
    if not commit_sha:
        raise RuntimeError("Unable to determine git commit SHA for evaluation manifest")

    worktree_status = _run_git(["status", "--porcelain"])
    dirty_worktree = bool(worktree_status.strip())
    diff_hash = None
    if dirty_worktree:
        tracked_diff = _run_git(["diff", "--binary", "HEAD"]) or ""
        diff_hash = sha256(
            (worktree_status + "\n" + tracked_diff).encode("utf-8")
        ).hexdigest()
    return EvaluationManifest(
        run_id=str(uuid4()),
        commit_sha=commit_sha,
        dirty_worktree=dirty_worktree,
        started_at=datetime.now(UTC),
        machine=MachineMetadata(
            platform=platform.platform(),
            python_version=sys.version,
            cpu_count=os.cpu_count(),
        ),
        dataset_version=dataset_version,
        runner_version=RUNNER_VERSION,
        judge_model=judge_model,
        judge_prompt_version=None,
        provider_modes={},
        diff_hash=diff_hash,
    )
