# F1 Keep-Formulas Rollout Log

## Execution policy

- Source plan: `C:\Users\HUY HOANG\Downloads\FEATURE_1_KEEP_FORMULAS_POST_IMPLEMENTATION_PLAN.md`
- Started: `2026-08-22T13:44:55+07:00`
- Branch/base commit: `feature/find-route` / `524623102a01330501dbf7a84b45b322e521b581`
- Execution is sequential and stops at the first failed acceptance gate.
- Secrets, authorization headers, cookies and complete provider URLs containing credentials are never recorded.
- Energy/SOC/charging formulas and existing planner search constants are frozen.

## Phase log

### Phase A — PASS

- Located the existing implementation; no duplicate service or CLI was created.
- Confirmed independent worker commands for station sync, detail hydration and graph build.
- Confirmed the configured application database dialect is PostgreSQL; Redis is disabled.
- Confirmed production API wiring uses the local SQLAlchemy station catalog and station-edge repository.
- Confirmed VinFast HTTP clients are worker/background dependencies, not `POST /plans` dependencies.
- Confirmed OpenAI web station search remains behind the recovery boundary.
- Recorded formula/search file hashes in the rollout inventory.
- Created the inventory and rollout checklist.

Evidence:

- `docs/f1_keep_formulas_rollout_inventory.md`
- `src/packages/core/trips/api/dependencies.py`
- `src/apps/worker/stations.py`
- `tests/test_core/test_station_runtime_wiring.py`

### Phase B — PASS

Initial repository-wide Ruff gate failed on pre-existing lint findings in one old migration, logging helper scripts and `test.py`. No migration semantics or Feature 1 formulas were changed. The findings were remediated mechanically and the complete gate was rerun.

| Command | Exit | Result |
|---|---:|---|
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_core\test_f1_numerical_golden.py tests\test_core\test_adaptive_station_planner.py tests\test_core\test_energy_planning.py tests\test_core\test_feasibility.py` | 0 | 21 passed |
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | 125 passed, 5 expected F2 xfailed, 1 mock serializer warning |
| `.\.venv\Scripts\ruff.exe check . --no-cache` | 0 | All checks passed |
| `npm run typecheck` | 0 | TypeScript passed |
| `npm run build` | 0 | Vite build passed; 54 modules transformed |

Files changed only for repository-wide lint compliance:

- `migrations/versions/20260808_1235_f1_us1_trip_vehicle_schema.py` (import order only)
- `scripts/log_antigravity.py`
- `scripts/log_hook.py`
- `scripts/log_manual.py`
- `scripts/submit_log.py`
- `test.py`

### Phase C — FAIL / EXECUTION STOPPED

Read-only Alembic inspection found migration-lineage drift:

| Check | Result |
|---|---|
| `alembic current` | Exit 1: configured DB references unknown revision `20260819_1200` |
| `alembic heads` | Repository head is `20260822_1200` |
| `alembic history` | Repository chain is `20260815_0130 -> 20260822_1200` |
| Git history/branches search | No migration with revision `20260819_1200` found |
| PostgreSQL connectivity | Pass |
| DB `alembic_version` | `20260819_1200` |
| Required station tables | Absent |
| `PostGIS_Version()` | Fails: function does not exist |

The configured DB contains an `audit_logs` table not represented by the current branch's models or migrations. Its exact applied migration cannot be reconstructed safely from the available repository history. Creating a guessed no-op revision, stamping the DB, or changing `20260822_1200.down_revision` would violate migration safety rules and could hide schema drift.

Actions intentionally **not** performed:

- no `alembic stamp`;
- no `alembic upgrade head`;
- no PostGIS extension creation;
- no station metadata/bulk/detail HTTP call;
- no station ingestion;
- no graph build;
- no runtime call using the configured dev database.

Per the source execution plan, processing stopped at the first failed acceptance gate. Phases D through Q are `NOT RUN`, and the final rollout decision is `NO-GO` until the missing migration lineage is recovered or the configured database is replaced by an explicitly approved clean dev PostgreSQL instance.

### Phase C — RESUMED / PASS

The operator supplied `20260819_1200_add_f2_plan_decisions.py`. Inspection confirmed it represents the already-present `confirmed_plan_version`, `decision_reason` and `audit_logs` schema.

Because F1 and F2 were sibling heads from `20260815_0130`, a new non-destructive merge migration `20260822_1500_merge_f1_f2_heads.py` was added. Neither parent migration was edited.

Pre-migration recovery snapshot:

- Path: `data/rollout_backups/f1-pre-migration-20260822T141849+0700.json.gz` (git-ignored)
- SHA-256: `9094256ca68916791e56f156cd7f09aad358982c2098bc53394f0920fabd242a`
- Row counts: 178 trips, 67 plans, 7 users, 10 user vehicles, 32 auth sessions, 9 vehicle profiles, 4 audit logs, 1 policy config.

| Check | Result |
|---|---|
| Fresh SQLite upgrade to merge head | PASS; all required tables and both F1/F2 plan columns present |
| PostgreSQL `alembic upgrade head` | PASS |
| Current revision | `20260822_1500` merge head |
| PostGIS | `3.3 USE_GEOS=1 USE_PROJ=1 USE_STATS=1` |
| Station geography index | GIST verified |
| Required tables | All present |
| Plan history | 67/67 proposals backfilled; zero nested legacy proposals |
| Migration-focused tests | 22 passed |

No plan-history row was lost and the existing F2 database columns remain present but unused by this F1 rollout.

### Phase D — PASS

- Added output-level redaction for sensitive query parameters, Authorization,
  proxy authorization, Cookie/Set-Cookie, bearer values and recognizable
  OpenAI/LangSmith key formats. Redaction also covers rendered exception text.
- Kept `httpx` and `httpcore` at `WARNING`, preventing their normal request URL
  logs from emitting provider query parameters.
- Confirmed `.env` is ignored by `.gitignore` and is not tracked by Git.
- Confirmed currently tracked configuration contains placeholders rather than a
  real credential candidate.
- Confirmed LangSmith tracing is not present in the rollout process environment.
- The prior repository version contained a non-placeholder AI logging credential
  in `.env.example`. It has been replaced by a placeholder. Operator action:
  rotate that credential if the prior revision or any generated/shared log was
  accessible outside the trusted local environment.

| Check | Result |
|---|---|
| Redaction unit tests | 2 passed |
| Focused Ruff check | All checks passed |
| Tracked-file credential scan | 0 real credential candidates |
| `httpx` / `httpcore` effective level | `WARNING` / `WARNING` |

### Phase E — PASS

The existing background VinFast client was used directly in diagnostic mode.
Only public metadata and bulk dataset endpoints were called; no detail endpoint
was called.

| Event | Status | Evidence |
|---|---:|---|
| `VINFAST_META_FETCH` | 200 | generation `743`, file `locators-743.json.gz`, retrieved `2026-08-22T07:26:52.369997+00:00` |
| `VINFAST_BULK_FETCH` | 200 | 66,902 raw records, SHA-256 `6aae7ea7e20147f124809d4fd5bdf566ca59f8f457f45dab804b1d2eb4f7bdd5`, retrieved `2026-08-22T07:26:55.488599+00:00` |

Provider classification: the permitted public bulk source is usable. Full
ingestion may proceed without `/get-locator/{id}`.

### Phase F — PASS

The first full run reached the local five-minute command limit and was terminated.
The transaction rolled back cleanly: dataset/location counts remained zero. The
cause was an N+1 station lookup in the repository (one query per one of 23,919
normalized locations). A minimal repository patch preloads existing locations in
one query while preserving transactional upsert, `VERIFIED` detail preservation
and inactive lifecycle semantics.

| Check | Result |
|---|---|
| Repository regression tests after patch | 12 passed |
| First successful sync | `INGESTED`, 23,919 locations, 48.945s |
| Same-generation rerun | `NOOP`, 0 writes, 7.03s |
| Active locations | 23,919 |
| Quality distribution | 23,919 `PARTIAL`; 0 `VERIFIED`; 0 `UNVERIFIED` |
| Provider distribution | 23,919 `VINFAST_OFFICIAL` |
| Duplicate `(provider, external_id)` groups | 0 |
| Invalid/null active coordinates | 0 |
| Missing active raw payload/retrieval timestamp | 0 |
| Active dataset versions | 1, generation `743` |

Artifact: `artifacts/f1_station_ingestion_report.md`.

### Phase G — PASS

A bounded real-environment hydration run with limit 2 attempted one station and
stopped on the first failure (`attempted=1`, `failed=1`). A controlled client
probe classified the response and verified the circuit behavior:

| Check | Result |
|---|---|
| First detail request | HTTP 403 / `PROVIDER_ACCESS_DENIED` |
| Second call on same client | rejected by open circuit; no HTTP status |
| Circuit state | `PROVIDER_ACCESS_DENIED` |
| Hydration/circuit regression tests | 4 passed |
| Locations after probe | 23,919 total and active; 0 rows lost |

No detail pool or bulk OpenAI enrichment was launched. All stations remain
`PARTIAL`, and graph/planner rollout may continue independently.

### Phase H — FAIL / EXECUTION STOPPED

Pre-run audit found that the original unbounded command would issue up to one
Goong Direction request for every candidate pair. With 23,919 eligible nodes and
K=40, that is an upper bound of 956,760 requests. The official default Goong REST
limit is 1,000 requests/day.

Before any real graph call, the implementation received bounded-rollout guards:

- resumable `--origin-limit` and `--start-after-location-id` CLI controls;
- graph-specific lightweight read models (PostGIS in PostgreSQL; deterministic
  Haversine coarse ranking for SQLite);
- active-lifecycle, valid-coordinate and `VERIFIED`/`PARTIAL` node eligibility;
- no topology filtering on runtime `ACTIVE` versus `BUSY` state;
- configurable maximum exact road-leg distance;
- per-source transaction lock and K-degree trim for builder and runtime
  write-through edges;
- edge reads exclude inactive source/destination lifecycle nodes while retaining
  road-version semantics.

Focused graph/planner tests passed (7 initially, then 13 catalog/graph tests after
the lightweight read model). A controlled real-provider chunk produced:

| Metric | Result |
|---|---:|
| Origins processed | 1 of 23,919 |
| Candidate pairs / Goong calls | 40 / 40 |
| Edges written | 40 |
| Route failures / road-distance rejections | 0 / 0 |
| Chunk duration | 51.005s |
| Maximum current out-degree | 40 |
| Zero-degree nodes | 23,918 |
| Inactive-endpoint edges | 0 |

The partial graph obeys the sparse invariant but is not a completed nationwide
graph. At the observed rate an unthrottled full run would also take roughly 14
continuous days; the default request quota is the stronger blocker. Continuing
would create an uncontrolled provider bill/quota failure and violate the rollout
gate, so phases I through Q were not run.

Safety action: the application default and sample configuration now keep
`STATION_GRAPH_ENABLED=false`. The ingested PostgreSQL catalog remains available,
but runtime cannot consume the incomplete graph unless an operator explicitly
overrides the flag.

Artifact: `artifacts/f1_station_graph_report.md`.

Final post-stop regression evidence:

- full backend suite: 128 passed, 5 expected F2 xfailed, 1 existing mock warning;
- repository-wide Ruff: all checks passed;
- focused formula/catalog/graph/security suite: 36 passed;
- Energy, feasibility and adaptive-planner hashes exactly match Phase A.

### Phase H resume - self-hosted OSRM implementation (2026-08-22)

The Goong quota blocker was addressed in code with PostGIS candidate selection,
a self-hosted OSRM Table adapter and atomic graph versions. Migration
`20260822_1700` is applied. Full regression is green: 135 passed, 5 expected
xfail; repository-wide Ruff passes.

The local 3.95 GB Docker environment could not complete Vietnam OSRM
preprocessing inside the bounded rollout window. No OSRM graph version was
created and the feature flag remains disabled. Phase H therefore remains failed
operationally even though implementation acceptance passes.

Detailed evidence and resume steps:

- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md`
- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`

### Phase H resume attempt - 2026-08-23

Docker Desktop was started and verified on `desktop-linux` with 12 CPUs and
approximately 7.61 GiB available memory. The source PBF and filtered routing
PBF were prepared by the pinned bootstrap script, and the OSRM image
`v26.6.5-debian` was pulled at the recorded digest.

`osrm-extract` parsed the filtered dataset and wrote partial `.osrm` files, but
the container wait ended with Docker `unexpected EOF`; the bootstrap exited
non-zero. No partition/customize/trial or service smoke was run, and no
`road-version.txt` was created. The partial files remain unaccepted and are not
runtime-visible. Database/schema checks and the full 168-test backend suite
passed during this attempt. Phase H is still failed operationally, so Phases I-Q
remain pending and the final decision remains **NO-GO**.

### Phase H OOM confirmation - 2026-08-23

After Docker was increased to 8 CPUs and about 9.71 GiB memory, extraction was
retried with 6 and 4 threads. Docker WSL kernel logs explicitly show the Linux
OOM killer terminating `osrm-extract` during edge-expanded graph generation;
the largest recorded anonymous RSS was about 9.2 GiB. The existing 2 GiB WSL
swap was enabled but did not prevent termination. No marker was written and no
later Phase H or Phase I-Q gate was run. The decision remains **NO-GO** pending
a retry with at least 12 GiB Docker memory and additional swap.

### Phase H - PASS / nationwide OSRM graph - 2026-08-23

Docker was increased to 12 GB RAM, 6 CPUs and 8 GB swap. The complete pinned
OSRM MLD pipeline passed, the local Table smoke returned `code=Ok`, and graph
version `09ac16c6-0d95-4f9f-9ae5-af3605293162` atomically activated with
23,919/23,919 processed nodes and 946,138 directed edges. Maximum out-degree is
40, inactive/missing endpoints are zero, and the road-version marker matches.

Automated Phase I-Q evidence was rerun: focused F1 15 passed,
planner/API/persistence/cache 26 passed, full pytest 169 passed, Ruff passed and
frontend typecheck/build passed. Redis remains disabled and optional. OSRM Table
latency and graph metrics are recorded in
`artifacts/f1_keep_formulas_performance_report.md`.

The historical Phase-A formula/search hashes do not match the current `dev`
baseline because the merged F3/F4 history changed feasibility/replanning files
after the original snapshot. The files are not modified in this working tree and
the numerical golden suite passes, but the lock evidence cannot honestly be
marked equal. Final production decision therefore remains **NO-GO** until the
owner reconciles/accepts the merged baseline and authorizes flag enablement.
