"""CLI Entry point for F3/F4 Evaluation Benchmark execution."""

import argparse
import asyncio
from pathlib import Path

from eval.adapters import run_accuracy_cases
from eval.availability_runner import LocalApiProcess, run_availability_soak
from eval.dataset import build_manifest, load_golden_cases
from eval.load_runner import run_performance_matrix
from eval.local_app import SupervisorMode, create_evaluation_harness
from eval.metrics import build_accuracy_summary
from eval.report import (
    load_artifact,
    render_markdown_report,
    resolve_run_id,
    save_current_run_id,
    write_artifact,
)


async def run_accuracy(dataset_path: str, supervisor_mode: SupervisorMode) -> None:
    cases = load_golden_cases(Path(dataset_path))
    manifest = build_manifest(
        dataset_version=cases[0].dataset_version if cases else "f3-f4-golden-v1",
        judge_model=None,
    )
    manifest.provider_modes["supervisor"] = supervisor_mode
    run_id = manifest.run_id
    save_current_run_id(run_id)

    # Save initial manifest
    write_artifact(run_id, "manifest.json", manifest.model_dump())

    harness = create_evaluation_harness(
        Path(f"eval/results/{run_id}/accuracy_app.db"),
        supervisor_mode=supervisor_mode,
    )
    try:
        predictions = await run_accuracy_cases(cases, harness)
        summary = build_accuracy_summary(cases, predictions)

        write_artifact(
            run_id,
            "predictions.json",
            [p.model_dump() for p in predictions],
        )
        write_artifact(run_id, "accuracy_summary.json", summary)
        print(f"[ACCURACY] Completed {len(predictions)} cases. Run ID: {run_id}")
    finally:
        harness.close(remove_database=True)


async def run_judge(run_id_arg: str, model_from_settings: bool) -> None:
    run_id = resolve_run_id(run_id_arg)
    # Live LLM judge is deferred in local offline mode per execution budget
    summary = {
        "status": "DEFERRED",
        "reason": "Live OpenAI LLM judge deferred to save API costs",
        "mean_score": None,
        "human_audit_sample_size": 0,
    }
    write_artifact(run_id, "judge_summary.json", summary)
    print(f"[JUDGE] Deferred LLM judge for run ID: {run_id}")


async def run_performance(run_id_arg: str, base_url: str | None) -> None:
    run_id = resolve_run_id(run_id_arg)
    manifest_data = load_artifact(run_id, "manifest.json")
    from eval.contracts import EvaluationManifest

    manifest = EvaluationManifest.model_validate(manifest_data)

    target_url = base_url or "http://127.0.0.1:8123"
    local_process = None
    if not base_url:
        local_process = LocalApiProcess(
            run_directory=Path(f"eval/results/{run_id}/perf_app"),
            port=8123,
            supervisor_mode="fallback",
        )
        await local_process.start()
        await local_process.wait_ready(timeout_seconds=15.0)

    try:
        samples, summary = await run_performance_matrix(target_url, manifest)
        write_artifact(
            run_id,
            "performance_samples.json",
            [s.model_dump() for s in samples],
        )
        write_artifact(run_id, "performance_summary.json", summary)
        print(f"[PERFORMANCE] Completed matrix benchmark. Run ID: {run_id}")
    finally:
        if local_process:
            await local_process.stop()


async def run_availability(run_id_arg: str, duration_seconds: int) -> None:
    run_id = resolve_run_id(run_id_arg)
    process = LocalApiProcess(
        run_directory=Path(f"eval/results/{run_id}/avail_app"),
        port=8124,
        supervisor_mode="fallback",
    )
    await process.start()
    await process.wait_ready(timeout_seconds=15.0)

    try:
        samples, summary = await run_availability_soak(
            process,
            duration_seconds=duration_seconds,
            request_interval_seconds=0.1,
        )
        write_artifact(
            run_id,
            "availability_samples.json",
            [s.model_dump() for s in samples],
        )
        write_artifact(
            run_id,
            "availability_summary.json",
            summary.model_dump(),
        )
        print(f"[AVAILABILITY] Completed soak ({duration_seconds}s). Run ID: {run_id}")
    finally:
        await process.stop()


def run_report(run_id_arg: str, output_path: str | None) -> None:
    run_id = resolve_run_id(run_id_arg)
    manifest = load_artifact(run_id, "manifest.json")

    accuracy_summary = None
    try:
        accuracy_summary = load_artifact(run_id, "accuracy_summary.json")
    except FileNotFoundError:
        pass

    judge_summary = None
    try:
        judge_summary = load_artifact(run_id, "judge_summary.json")
    except FileNotFoundError:
        pass

    load_summary = None
    try:
        load_summary = load_artifact(run_id, "performance_summary.json")
    except FileNotFoundError:
        pass

    availability_summary = None
    try:
        availability_summary = load_artifact(run_id, "availability_summary.json")
    except FileNotFoundError:
        pass

    report_content = render_markdown_report(
        manifest=manifest,
        accuracy_summary=accuracy_summary,
        judge_summary=judge_summary,
        load_summary=load_summary,
        availability_summary=availability_summary,
    )

    out_file = Path(output_path) if output_path else Path("docs/evaluation/f3_f4_local_benchmark_20260901.md")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"[REPORT] Rendered markdown report to: {out_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="F3/F4 Local Evaluation Benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Accuracy subcommand
    acc_parser = subparsers.add_parser("accuracy", help="Run golden case accuracy stage")
    acc_parser.add_argument("--dataset", default="eval/datasets/f3_f4_golden_v1.jsonl", help="Dataset path")
    acc_parser.add_argument("--mode", default="fallback", choices=["fallback", "live"], help="Supervisor mode")

    # Judge subcommand
    judge_parser = subparsers.add_parser("judge", help="Run LLM judge stage")
    judge_parser.add_argument("--run-id", default="current", help="Run ID or 'current'")
    judge_parser.add_argument("--model-from-settings", action="store_true", help="Use model from settings")

    # Performance subcommand
    perf_parser = subparsers.add_parser("performance", help="Run local load/concurrency benchmark")
    perf_parser.add_argument("--run-id", default="current", help="Run ID or 'current'")
    perf_parser.add_argument("--managed-local-api", action="store_true", help="Start managed local uvicorn")
    perf_parser.add_argument("--base-url", default=None, help="Base URL if server is already running")

    # Availability subcommand
    avail_parser = subparsers.add_parser("availability", help="Run availability soak stage")
    avail_parser.add_argument("--run-id", default="current", help="Run ID or 'current'")
    avail_parser.add_argument("--duration-seconds", type=int, default=10, help="Soak duration in seconds")

    # Report subcommand
    rep_parser = subparsers.add_parser("report", help="Render markdown benchmark report")
    rep_parser.add_argument("--run-id", default="current", help="Run ID or 'current'")
    rep_parser.add_argument("--output", default=None, help="Output markdown path")

    args = parser.parse_args()

    if args.command == "accuracy":
        asyncio.run(run_accuracy(args.dataset, args.mode))
    elif args.command == "judge":
        asyncio.run(run_judge(args.run_id, args.model_from_settings))
    elif args.command == "performance":
        asyncio.run(run_performance(args.run_id, args.base_url))
    elif args.command == "availability":
        asyncio.run(run_availability(args.run_id, args.duration_seconds))
    elif args.command == "report":
        run_report(args.run_id, args.output)


if __name__ == "__main__":
    main()
