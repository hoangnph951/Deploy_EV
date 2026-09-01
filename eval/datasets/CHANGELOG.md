# Golden dataset changelog

## f3-f4-golden-v1 — 2026-09-01

This immutable version contains 60 deterministic cases in four cohorts:
`MENTOR_REMEDIATION` (15), `BOUNDARY` (21),
`FAILURE_LIFECYCLE` (12), and `HOLDOUT` (12).

The mentor-remediation source is frozen to these exact IDs:

- P210-F3-EDGE-002
- P210-F3-EDGE-003
- P210-F3-HAPPY-004
- P210-F3-EDGE-005
- P210-F3-EDGE-006
- P210-F4-HAPPY-001
- P210-F4-HAPPY-002
- P210-F4-EDGE-003
- P210-F4-UNHAPPY-005
- P210-F4-HAPPY-006
- P210-F4-EDGE-007
- P210-F4-SEC-008
- P210-F4-AI-009
- P210-F4-AI-904
- P210-F4-AI-905

Labels come only from executable deterministic contracts. F3 classification is
labelled by `MonitoringEvaluator.classify`: thresholds are strict `>` at
2.0 km, 5.0 percent SOC deficit, and 60 seconds, so equality is `NORMAL`.
F4 feasibility, lifecycle, and safety labels reference exact existing test
functions. Provider failure is insufficient evidence, proven infeasibility is
a distinct typed result, and stale/provider/security cases fail closed without
candidate mutation. No LLM was used to assign feasibility or safety labels.

Holdout freeze timestamp: 2026-09-01T00:00:00+07:00

Dataset SHA-256: `9d8d7f1c944c7bf22d1cdcb9ea062e5341ea72f3c65e4da59ba9555e06a09c99`

The hash binds the accepted v1 JSONL bytes after semantic-oracle review, with
line endings canonicalized to LF for cross-platform checkout stability. Tests
recompute it independently so an in-place corpus edit fails validation. The
semantic-oracle correction removed three unobservable provider metadata
claims and aligns the proven-infeasible reason code with the service output.

Holdout fingerprints are canonical JSON of `category + input_snapshot`.
Holdouts remain separate from remediation and boundary inputs. Any label,
input, cohort, or oracle change requires a new v2 dataset and changelog entry;
this v1 file must not be edited in place after release.
