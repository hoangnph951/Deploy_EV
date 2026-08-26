# F1 Keep-Formulas Rollout Checklist

Status legend: `[x]` pass, `[ ]` pending, `[!]` blocked/fail, `[-]` not applicable.

Current execution state: **EXECUTION STOPPED — Phase H FAIL; final decision NO-GO**.

## Phase A — Implementation audit

- [x] Located migrations, models, repositories, ingestion, graph, cache, runtime, persistence, tests, flags and worker CLI.
- [x] Created `docs/f1_keep_formulas_rollout_inventory.md`.
- [x] Confirmed production `POST /plans` wiring does not instantiate a VinFast HTTP adapter.
- [x] Confirmed OpenAI station search is recovery-only.
- [x] Recorded numerical/search lock hashes.

## Phase B — Baseline tests

- [x] Backend behavioral suite passes: 125 passed.
- [x] Numerical golden suite passes: 21 passed.
- [x] Ruff passes after minimal cleanup of pre-existing repository-wide lint findings.
- [x] Frontend typecheck passes.
- [x] Frontend production build passes.
- [x] Existing F2 xfails remain expected: 5 xfailed.

## Phase C — Migration rollout

- [x] Recovered revision `20260819_1200` inspected and matched the configured DB's F2 columns/audit schema.
- [x] Added new merge revision `20260822_1500`; neither recovered F2 nor existing F1 migration was rewritten.
- [x] `alembic heads/history/current` now resolve to one merge head.
- [x] Fresh SQLite upgrade through both branches and merge head passes.
- [x] Pre-migration logical recovery snapshot created under ignored `data/rollout_backups/`.
- [x] `alembic upgrade head` succeeds on configured PostgreSQL.
- [x] Required station/graph/planning-run schema verified.
- [x] PostGIS `3.3` and station-location GIST index verified.
- [x] Proposal backfill preserved all 67 plans: 67 proposal columns populated, zero legacy nested proposals.
- [x] SQLite compatibility remains green through migration-focused tests.

## Phase D — Security and logging

- [x] Provider request logs redact query/header secrets, including exception text.
- [x] `.env` is ignored and not tracked.
- [x] Sample configuration contains placeholders only.
- [x] No real credential candidate found in currently tracked files.
- [x] LangSmith tracing is absent from the rollout process and does not block acceptance.

## Phase E — VinFast bulk-source diagnostic

- [x] Metadata source classified usable: HTTP 200, generation 743.
- [x] Bulk source classified usable: HTTP 200, 66,902 raw records.
- [x] No detail endpoint used to decide bulk-ingestion success.

## Phase F — Station ingestion

- [x] Idempotent sync executed: first run ingested 23,919; rerun returned `NOOP`.
- [x] Active/quality/provider counts verified.
- [x] Coordinate, uniqueness, generation, timestamps and raw payload checks pass.
- [x] `artifacts/f1_station_ingestion_report.md` generated.

## Phase G — Optional detail hydration

- [x] Real detail probe received 403, stopped immediately and opened the circuit.
- [x] Second call was rejected by the open circuit without another HTTP response.
- [x] All 23,919 existing station rows remain intact and active.
- [x] Planner/local catalog availability does not depend on hydration.

## Phase H — Sparse persistent graph

- [!] Full graph build not completed: 1/23,919 origins processed under a bounded real-provider probe.
- [x] Partial directed topology and `edges <= N × K` / max-degree K invariants verified.
- [x] Degree distribution reviewed: 40 edges, max degree 40, 23,918 zero-degree nodes because the rollout stopped.
- [x] `artifacts/f1_station_graph_report.md` generated with the quota blocker.
- [x] `STATION_GRAPH_ENABLED` safe default/sample disabled after the failed gate.
- [x] Self-hosted OSRM Table/MLD implementation and atomic graph-version schema added.
- [x] Legacy 40-edge partial graph isolated in a `FAILED` graph version.
- [x] Atomic/resume/failure/K-bound acceptance tests pass.
- [!] Local OSRM preprocessing blocked by the current 3.95 GB Docker memory/time envelope.
- [ ] Complete OSRM MLD dataset, smoke Table API and activate the nationwide graph.

Execution intentionally stopped at this failed gate. Phases I through Q were not
run; their unchecked items remain the acceptance work for a resumed rollout.

## Phase I — Graph spot checks

- [ ] Representative edges compared with current routing provider.
- [ ] Coordinate order and directed semantics verified.
- [ ] Old road-version edge rejected.

## Phase J — Planner integration

- [ ] Short safe trip passes without station dependency.
- [ ] Long trip reads local station DB and graph.
- [ ] Runtime VinFast detail calls equal zero.
- [ ] Partial-only data does not fabricate a charging commitment.

## Phase K — OpenAI recovery

- [ ] Web candidate remains `UNVERIFIED`.
- [ ] Plan using web evidence remains `CONDITIONAL` and persists.
- [ ] Deterministic feasibility cannot be bypassed.

## Phase L — Failure semantics

- [ ] Provider outage is not physical infeasibility.
- [ ] Graph miss falls back safely.
- [ ] Redis outage is non-fatal.
- [ ] Routing outage remains fail-closed.

## Phase M — Persistence

- [ ] Proposal is separate from assumptions.
- [ ] Legacy plan remains readable.
- [ ] Alternatives and conditional proposals persist.
- [ ] Concurrent version allocation is atomic.
- [ ] No F2 confirm/activate behavior introduced.

## Phase N — Frontend

- [ ] Route/SOC UI uses backend facts.
- [ ] Data Trust is provenance-driven.
- [ ] Conditional recovery is visibly distinct.
- [ ] History and alternatives survive reload.
- [ ] No server secret is sent to the browser.

## Phase O — Redis decision

- [ ] Redis OFF path passes all mandatory acceptance.
- [ ] Redis remains optional and PostgreSQL remains source of truth.
- [ ] Redis ON acceptance completed or explicitly deferred.

## Phase P — Performance

- [ ] Representative latency/call metrics collected.
- [ ] VinFast detail calls during `POST /plans` equal zero.
- [ ] `artifacts/f1_keep_formulas_performance_report.md` generated.

## Phase Q — Deployment readiness

- [ ] Deployment order documented.
- [ ] Safe rollback and forward-fix migration strategy documented.
- [ ] Scheduled station sync/graph update operations documented.
- [x] Final formula/search hashes equal Phase A hashes at the Phase H stop point.
- [x] `artifacts/F1_KEEP_FORMULAS_ROLLOUT_RESULT.md` updated.
- [x] Final decision recorded as `NO-GO` at the mandatory Phase H stop point.

## Resume evidence - 2026-08-23

- [x] Docker daemon available: `desktop-linux`, 12 CPUs, approximately 7.61 GiB RAM.
- [x] Database/schema reverified: Alembic `20260822_1700 (head)`, PostGIS 3.3,
  required tables and charging-location GIST index.
- [x] Active station dataset reverified: generation `743`, 23,919 active
  locations, 0 invalid coordinates.
- [x] Full backend regression rerun: 168 passed.
- [x] Frontend production build rerun: typecheck and Vite build passed.
- [!] OSRM preprocessing resumed but `osrm-extract` failed with Docker
  `unexpected EOF` after partial artifact output.
- [ ] OSRM trial, local service smoke, complete graph build and atomic activation.
- [ ] Mandatory Phases I-Q; they remain blocked by the Phase H OSRM gate.

Current execution state remains **EXECUTION STOPPED - Phase H FAIL; final decision NO-GO**.
`STATION_GRAPH_ENABLED=false` is unchanged.

## Nationwide OSRM Resume Evidence - 2026-08-23

- [x] OSRM MLD extraction, partition, customize, trial and local Table smoke pass.
- [x] Graph `09ac16c6-0d95-4f9f-9ae5-af3605293162` is `ACTIVE`.
- [x] `processed_node_count=23,919`, `edge_count=946,138`, max out-degree `40`.
- [x] Inactive/missing endpoints `0`; legacy Goong graph remains `FAILED`.
- [x] Focused acceptance suite `15 passed`; planner/API/persistence/cache subset `26 passed`.
- [x] Full backend suite `169 passed`; Ruff and frontend build/typecheck pass.
- [x] Performance evidence written to `artifacts/f1_keep_formulas_performance_report.md`.
- [!] Historical Phase-A formula/search hashes do not match the current merged
  F3/F4 baseline. This requires owner reconciliation before a production GO.
- [x] `STATION_GRAPH_ENABLED=false` remains unchanged pending that reconciliation
  and explicit local/staging enablement approval.

## OOM evidence refresh - 2026-08-23

- [x] Docker allocation reverified: 8 CPUs, about 9.71 GiB RAM, 2 GiB swap.
- [!] Linux OOM killer explicitly terminated both 6-thread and 4-thread
  `osrm-extract` retries during edge-expanded graph generation.
- [x] No `road-version.txt` or incomplete runtime graph was accepted.
- [ ] Increase Docker to at least 12 GiB RAM with additional swap, then resume
  Phase H preprocessing.
