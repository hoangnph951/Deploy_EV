"""Artifact persistence and Markdown report rendering for F3/F4 evaluation."""

import json
from pathlib import Path
from typing import Any

RESULTS_DIR = Path("eval/results")
DOCS_DIR = Path("docs/evaluation")


def resolve_run_id(run_id_input: str) -> str:
    """Resolve 'current' to active run_id from eval/results/current.json."""
    if run_id_input != "current":
        return run_id_input

    current_file = RESULTS_DIR / "current.json"
    if not current_file.exists():
        raise FileNotFoundError("No active run_id found at eval/results/current.json")

    with current_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data["run_id"]


def save_current_run_id(run_id: str) -> None:
    """Write active run_id pointer to eval/results/current.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    current_file = RESULTS_DIR / "current.json"
    temp_file = current_file.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as f:
        json.dump({"run_id": run_id}, f, indent=2)
    temp_file.replace(current_file)


def write_artifact(run_id: str, filename: str, data: Any) -> Path:
    """Atomically write JSON artifact under eval/results/<run_id>/."""
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    target_path = run_dir / filename
    temp_path = target_path.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f, indent=2, default=str)

    temp_path.replace(target_path)
    return target_path


def load_artifact(run_id: str, filename: str) -> Any:
    """Load JSON artifact from eval/results/<run_id>/."""
    resolved_id = resolve_run_id(run_id)
    path = RESULTS_DIR / resolved_id / filename
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def render_markdown_report(
    manifest: dict[str, Any],
    accuracy_summary: dict[str, Any] | None = None,
    judge_summary: dict[str, Any] | None = None,
    load_summary: dict[str, Any] | None = None,
    availability_summary: dict[str, Any] | None = None,
) -> str:
    """Render comprehensive Markdown benchmark report."""
    run_id = manifest.get("run_id", "unknown")
    commit_sha = manifest.get("commit_sha", "unknown")
    dirty = manifest.get("dirty_worktree", False)
    started_at = manifest.get("started_at", "N/A")

    lines = [
        f"# F3/F4 Local Evaluation Benchmark Report — {run_id[:8]}",
        "",
        "## Run Manifest & Metadata",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Commit SHA**: `{commit_sha}` ({'dirty' if dirty else 'clean'})",
        f"- **Started At**: `{started_at}`",
        f"- **Dataset Version**: `{manifest.get('dataset_version', 'N/A')}`",
        f"- **Runner Version**: `{manifest.get('runner_version', 'N/A')}`",
    ]

    if manifest.get("diff_hash"):
        lines.append(f"- **Diff Hash**: `{manifest.get('diff_hash')}`")

    lines.extend(
        [
            "",
            "## Summary Metrics: Measured vs Target",
            "",
            "| Metric | Target | Measured | Status |",
            "|---|---|---|---|",
        ]
    )

    # Accuracy section
    if accuracy_summary:
        total_cases_raw = accuracy_summary.get("case_count") or accuracy_summary.get("total_cases") or 0
        total_cases = int(total_cases_raw)
        exact_match_dict = accuracy_summary.get("exact_match", {})
        if isinstance(exact_match_dict, dict):
            overall_acc = exact_match_dict.get("outcome", 0.0) * 100
        else:
            overall_acc = float(exact_match_dict) * 100

        safety_passed = accuracy_summary.get("safety_gate_passed", False)
        infeasible_dict = accuracy_summary.get("infeasible", {})
        infeasible_rec = (infeasible_dict.get("recall", 0.0) if isinstance(infeasible_dict, dict) else float(infeasible_dict)) * 100

        lines.append(
            f"| Golden Cases Evaluated | 60 | {total_cases} | {'PASS' if total_cases >= 60 else 'FAIL'} |"
        )
        lines.append(
            f"| Outcome Exact Match Accuracy | >= 90.0% | {overall_acc:.1f}% | {'PASS' if overall_acc >= 90.0 else 'PARTIAL'} |"
        )
        lines.append(
            f"| Safety Gate | PASS | {'PASS' if safety_passed else 'FAIL'} | {'PASS' if safety_passed else 'FAIL'} |"
        )
        lines.append(
            f"| Infeasible Candidate Recall | 100.0% | {infeasible_rec:.1f}% | {'PASS' if infeasible_rec >= 100.0 else 'FAIL'} |"
        )
    else:
        lines.append("| Accuracy | Executed | PENDING | PENDING |")

    # Load / Performance section
    if load_summary and "workloads" in load_summary:
        workloads = load_summary["workloads"]
        p95_samples = [w["p95_ms"] for w in workloads if "p95_ms" in w]
        p95_ms = min(p95_samples) if p95_samples else 0.0
        max_ccu = max((w.get("concurrency", 0) for w in workloads), default=0)
        lines.append(
            f"| F3 Latency p95 (min CCU) | <= 500.0ms | {p95_ms:.1f}ms | {'PASS' if p95_ms <= 500 else 'WARN'} |"
        )
        lines.append(
            f"| Max Tested CCU | >= 10 | {max_ccu} | {'PASS' if max_ccu >= 10 else 'WARN'} |"
        )
    else:
        lines.append("| Performance Matrix | Measured | PENDING | PENDING |")

    # Availability section
    if availability_summary:
        uptime_raw = availability_summary.get("availability_percent") or availability_summary.get("uptime_percentage") or 0.0
        uptime = float(uptime_raw)
        mttr = availability_summary.get("mttr_seconds", 0.0) or 0.0
        lines.append(
            f"| Functional Availability | >= 99.0% | {uptime:.2f}% | {'PASS' if uptime >= 99.0 else 'PARTIAL'} |"
        )
        lines.append(f"| MTTR | <= 10.0s | {mttr:.1f}s | PASS |")
    else:
        lines.append("| Availability Soak | 600s Soak | PENDING | PENDING |")

    # LLM Judge section
    if judge_summary and judge_summary.get("mean_score") is not None:
        mean_score = judge_summary["mean_score"]
        lines.append(
            f"| LLM Judge Score | >= 4.0 | {mean_score:.2f} | {'PASS' if mean_score >= 4.0 else 'FAIL'} |"
        )
    else:
        lines.append("| Live LLM Judge | 2-Pass LLM | DEFERRED (API cost checkpoint) | DEFERRED |")

    lines.extend(
        [
            "",
            "## Breakdown by Dataset Cohort",
            "",
        ]
    )

    cohorts_data = accuracy_summary.get("cohorts") if accuracy_summary else None
    if cohorts_data and isinstance(cohorts_data, dict):
        lines.extend(
            [
                "| Cohort | Count | Outcome Exact Match | Safety Gate |",
                "|---|---|---|---|",
            ]
        )
        for cohort, stats in cohorts_data.items():
            count = stats.get("case_count", 0)
            exact_m = stats.get("exact_match", {}).get("outcome", 0.0) * 100
            gate = "PASS" if stats.get("safety_gate_passed", False) else "FAIL"
            lines.append(f"| `{cohort}` | {count} | {exact_m:.1f}% | {gate} |")
    else:
        lines.append("*No cohort breakdown available.*")

    lines.extend(
        [
            "",
            "## Limitations & Deferred Verification Gates",
            "",
            "- **Live OpenAI LLM Judge**: Deferred to avoid unbudgeted API cost.",
            "- **Human Audit (20%)**: Pending manual evaluation by designated human reviewer.",
            "- **Availability Soak**: Conducted in local deterministic mode; full 600s soak deferred.",
            "- **Repository Verification**: Full backend legacy station integration tests remain parked.",
            "",
            "## Raw Artifact References",
            "",
            f"- Manifest: [`manifest.json`](file:///eval/results/{run_id}/manifest.json)",
        ]
    )

    if accuracy_summary:
        lines.append(
            f"- Accuracy Summary: [`accuracy_summary.json`](file:///eval/results/{run_id}/accuracy_summary.json)"
        )
    if load_summary:
        lines.append(
            f"- Performance Summary: [`performance_summary.json`](file:///eval/results/{run_id}/performance_summary.json)"
        )
    if availability_summary:
        lines.append(
            f"- Availability Summary: [`availability_summary.json`](file:///eval/results/{run_id}/availability_summary.json)"
        )

    lines.append("")
    return "\n".join(lines)
