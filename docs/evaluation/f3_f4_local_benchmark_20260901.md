# F3/F4 Local Evaluation Benchmark Report — f8740d42

## Run Manifest & Metadata

- **Run ID**: `f8740d42-75ce-4030-94aa-96b624f09220`
- **Commit SHA**: `b379dc1309cd4a1d53b9102200211fa152c4d380` (dirty)
- **Started At**: `2026-09-01 13:00:23.239579+00:00`
- **Dataset Version**: `f3-f4-golden-v1`
- **Runner Version**: `f3-f4-evaluation-runner-v1`
- **Diff Hash**: `0d3b2529e1a7e89706bd60ba0020571e4f2e585860f2e6f15473f76e554ee669`

## Summary Metrics: Measured vs Target

| Metric | Target | Measured | Status |
|---|---|---|---|
| Golden Cases Evaluated | 60 | 60 | PASS |
| Outcome Exact Match Accuracy | >= 90.0% | 85.0% | PARTIAL |
| Safety Gate | PASS | FAIL | FAIL |
| Infeasible Candidate Recall | 100.0% | 100.0% | PASS |
| F3 Latency p95 (min CCU) | <= 500.0ms | 2.1ms | PASS |
| Max Tested CCU | >= 10 | 20 | PASS |
| Functional Availability | >= 99.0% | 48.65% | PARTIAL |
| MTTR | <= 10.0s | 1.9s | PASS |
| Live LLM Judge | 2-Pass LLM | DEFERRED (API cost checkpoint) | DEFERRED |

## Breakdown by Dataset Cohort

| Cohort | Count | Outcome Exact Match | Safety Gate |
|---|---|---|---|
| `MENTOR_REMEDIATION` | 15 | 86.7% | FAIL |
| `HOLDOUT` | 12 | 66.7% | FAIL |

## Limitations & Deferred Verification Gates

- **Live OpenAI LLM Judge**: Deferred to avoid unbudgeted API cost.
- **Human Audit (20%)**: Pending manual evaluation by designated human reviewer.
- **Availability Soak**: Conducted in local deterministic mode; full 600s soak deferred.
- **Repository Verification**: Full backend legacy station integration tests remain parked.

## Raw Artifact References

- Manifest: [`manifest.json`](file:///eval/results/f8740d42-75ce-4030-94aa-96b624f09220/manifest.json)
- Accuracy Summary: [`accuracy_summary.json`](file:///eval/results/f8740d42-75ce-4030-94aa-96b624f09220/accuracy_summary.json)
- Performance Summary: [`performance_summary.json`](file:///eval/results/f8740d42-75ce-4030-94aa-96b624f09220/performance_summary.json)
- Availability Summary: [`availability_summary.json`](file:///eval/results/f8740d42-75ce-4030-94aa-96b624f09220/availability_summary.json)
