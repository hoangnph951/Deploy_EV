# F1 Keep-Formulas Rollout Result

## Environment

- Executed: `2026-08-22`, timezone `Asia/Saigon`
- Branch / base commit: `feature/find-route` / `524623102a01330501dbf7a84b45b322e521b581`
- Database: configured PostgreSQL (connection details redacted)
- Alembic revision: `20260822_1500` merge head
- PostGIS: `3.3 USE_GEOS=1 USE_PROJ=1 USE_STATS=1`
- Station dataset generation: `743`
- Graph road version: `goong-car-v1` (partial graph only; runtime flag disabled)
- Redis: disabled
- OpenAI recovery: enabled/configured; not invoked during this rollout

## Phase Results

| Phase | Status | Evidence |
|---|---|---|
| A — Implementation audit | PASS | Inventory and hot-path boundary verified; formula/search hashes locked |
| B — Baseline regression | PASS | 125 passed, 5 expected xfailed; 21 numerical; Ruff/typecheck/build green |
| C — Migration rollout | PASS | Recovered F2 revision, added merge head, backed up DB, upgraded PostgreSQL, verified PostGIS/schema/backfill |
| D — Security/logging | PASS | Output-level secret redaction; `.env` ignored; tracked scan found 0 real credential candidates |
| E — Bulk-source diagnostic | PASS | Metadata/bulk HTTP 200; generation 743; 66,902 raw records; no detail call |
| F — Station ingestion | PASS | 23,919 locations ingested; second run `NOOP`; DB acceptance queries green |
| G — Optional hydration | PASS | First real detail probe 403; circuit opened; second call blocked; rows retained |
| H — Persistent graph | FAIL | Only a bounded 1-origin/40-edge chunk built; full graph exceeds default provider quota |
| I — Graph spot checks | NOT RUN | Mandatory stop at Phase H |
| J — Planner integration | NOT RUN | Mandatory stop at Phase H |
| K — OpenAI recovery | NOT RUN | Mandatory stop at Phase H |
| L — Failure semantics | NOT RUN | Mandatory stop at Phase H |
| M — Persistence | NOT RUN | Mandatory stop at Phase H |
| N — Frontend acceptance | NOT RUN | Mandatory stop at Phase H; baseline build/typecheck remain green |
| O — Redis decision | NOT RUN | Redis remains disabled |
| P — Performance | NOT RUN | Representative planner benchmark not permitted after Phase H failure |
| Q — Deployment readiness | NOT RUN | Graph gate blocks enablement/deployment |

## Station Dataset

- Raw records: `66,902`
- Normalized/active locations: `23,919` / `23,919`
- `VERIFIED`: `0`
- `PARTIAL`: `23,919`
- `UNVERIFIED`: `0`
- Duplicate provider/external-id groups: `0`
- Invalid/null active coordinates: `0`
- Missing active raw payload/retrieval timestamp: `0`
- Ingestion report: `artifacts/f1_station_ingestion_report.md`

## Graph

- Eligible nodes: `23,919`
- Current-version edges: `40`
- Average out-degree: `0.001672`
- Median out-degree: `0`
- Maximum out-degree: `40`
- Zero-degree nodes: `23,918`
- Controlled build duration: `51.005s` for one origin
- Goong calls / failures: `40` / `0`
- Sparse bound: `40 <= 23,919 × 40`
- Graph report: `artifacts/f1_station_graph_report.md`

The partial graph is correctly directed, versioned and degree-bounded, but it is
not complete enough to enable the graph planner.

## Runtime

- VinFast detail calls per real `/plans`: not measured because execution stopped
  before Phase J; static wiring and automated tests show no runtime dependency.
- Route calls: `40` during the controlled graph chunk.
- Graph hits/misses: not measured through a real plan request.
- OpenAI recovery calls: `0` during rollout.

## Regression

- Final full pytest: `128 passed, 5 expected F2 xfailed, 1 existing mock warning`
- Focused post-change suite: `36 passed`
- Ruff: all checks passed
- Frontend typecheck: passed at Phase B
- Frontend production build: passed at Phase B; 54 modules transformed
- Numerical golden tests: passed
- Formula/search hashes: unchanged from Phase A

## Changes Made During Rollout

- Added safe migration merge revision and PostgreSQL logical backup/schema checks.
- Added secret-redacting logging formatter and tests.
- Removed the station-ingestion N+1 query; first real sync dropped from timeout to
  48.945 seconds and same-generation rerun is a 7.03-second `NOOP`.
- Added graph lifecycle/coordinate/quality eligibility, maximum road-leg policy,
  lightweight PostgreSQL/SQLite graph read models, resumable chunk controls and
  transactional K-degree enforcement.
- Changed the safe default/sample `STATION_GRAPH_ENABLED` value to `false` after
  the partial graph failed the rollout gate.

No Energy/SOC/charging/risk formula or planner beam/search constant changed.

## Blocking Issues

1. A complete current-version graph has not been built: only 40 edges from one of
   23,919 eligible origins exist.
2. The current one-Direction-call-per-pair design has an upper bound of 956,760
   calls at K=40. The official default Goong REST quota is 1,000 requests/day.
3. Continuing the unbounded worker would be an uncontrolled quota/cost operation.
   Resume requires an operator-approved elevated quota/budget, or an approved
   Goong Distance Matrix/batched implementation and connectivity acceptance.
4. All canonical stations remain `PARTIAL` because the technical-detail endpoint
   returns 403. This does not block graph topology, but the real planner acceptance
   in Phases J/K remains unverified and must not be declared production-ready.

## Self-hosted OSRM follow-up - 2026-08-22

PostGIS + self-hosted OSRM was implemented to remove the external per-edge API
quota blocker. The code now uses one local Table request per origin and atomic
graph versions. Migration head is `20260822_1700`; full backend regression is
135 passed with 5 expected xfails and Ruff passes.

Production enablement remains blocked: the current Docker environment has about
3.95 GB RAM and did not complete the Vietnam `osrm-extract` phase. No OSRM graph
version or active graph was created, and `STATION_GRAPH_ENABLED=false` remains
the safe setting. See `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md` and
`docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`.

## Final Decision

**NO-GO**

Phases A–G passed. The rollout stopped at the first failed acceptance gate,
Phase H, as required. Keep station graph enablement off until the nationwide graph
is completed and Phases I–Q are executed.

## Latest execution evidence - 2026-08-23

- Docker Desktop context: `desktop-linux`, 12 CPUs, approximately 7.61 GiB total memory.
- Source and car-routing filtered PBF were prepared by the pinned bootstrap script.
- `osrm-extract` reached partial graph serialization, then failed with Docker
  `unexpected EOF`; `road-version.txt` was not created.
- Alembic current: `20260822_1700 (head)`; PostGIS 3.3 and the charging-location
  GIST index verified.
- Full backend regression: 168 passed.
- No OSRM service, Table smoke response, station graph build, ACTIVE graph, or
  Phase I-Q acceptance was claimed.

The latest decision is still **NO-GO**. Keep `STATION_GRAPH_ENABLED=false` and
resume preprocessing on a stable host with more Docker memory; do not use the
partial `.osrm` files as a routing or graph-build input.

### OOM evidence refresh - 2026-08-23

- Docker allocation: 8 CPUs, about 9.71 GiB RAM, 2 GiB active swap.
- Retries with 6 and 4 extraction threads were terminated by the Docker WSL
  Linux OOM killer during edge-expanded graph generation.
- Peak recorded `osrm-extract` anonymous RSS was about 9.2 GiB.
- `road-version.txt` remains absent; service, graph build, and Phases I-Q were
  not run.

Final decision remains **NO-GO** until preprocessing passes with a larger Docker
memory/swap allocation.

## Successful nationwide OSRM build - 2026-08-23

- Docker: 12 GB RAM, 6 CPUs, 8 GB swap.
- OSRM preprocessing/trial/service/Table smoke: PASS.
- Road version: `osrm-26.6.5-debian-driving-vietnam-87db807f8d67`.
- Graph: `09ac16c6-0d95-4f9f-9ae5-af3605293162`, `ACTIVE`.
- Nodes: 23,919/23,919; directed edges: 946,138.
- Maximum out-degree: 40; degree violations: 0.
- Inactive/missing endpoints: 0.
- Legacy Goong graph: `FAILED` and runtime-invisible.
- Tests: focused F1 15 passed; planner/API/persistence/cache 26 passed; full
  backend 169 passed; Ruff passed; frontend typecheck/build passed.

### Latest decision

**NO-GO for production enablement.** The operational OSRM/graph blocker is
resolved, but historical Phase-A formula/search lock hashes do not match the
current merged F3/F4 baseline. The numerical tests pass and those files are not
dirty, but owner reconciliation and explicit local/staging flag approval are
still required. `STATION_GRAPH_ENABLED=false` remains unchanged.
