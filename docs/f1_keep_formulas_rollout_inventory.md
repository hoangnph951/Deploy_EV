# F1 Keep-Formulas Rollout Inventory

## Environment snapshot

- Audited at: `2026-08-22T13:44:55+07:00`
- Branch: `feature/find-route`
- Base commit: `524623102a01330501dbf7a84b45b322e521b581`
- Application database dialect: `postgresql`
- Database host configured: yes (host/value intentionally redacted)
- Redis enabled: no
- Station catalog enabled: yes
- Station graph enabled: yes
- OpenAI recovery enabled: yes
- OpenAI and Goong credentials configured: yes (values intentionally not inspected or logged)

## Implementation inventory

| Capability | Implementation |
|---|---|
| Station ingestion command | `.\.venv\Scripts\python.exe -m src.apps.worker.stations sync-stations` |
| Detail hydration command | `.\.venv\Scripts\python.exe -m src.apps.worker.stations hydrate-stations --limit <N>` |
| Graph builder command | `.\.venv\Scripts\python.exe -m src.apps.worker.stations build-station-graph` |
| Alembic commands | `.\.venv\Scripts\alembic.exe current/heads/history/upgrade head` |
| Database dialect | PostgreSQL in the configured environment; SQLite remains the deterministic automated-test dialect |
| Station source | Permitted VinFast public locator metadata + bulk dataset; detail endpoint is optional background enrichment |
| Station catalog repository | `SqlAlchemyStationCatalogRepository` |
| Station ingestion service | `StationIngestionService` |
| VinFast upstream client | `VinFastLocatorClient` (worker/background only) |
| Provider circuit breaker | `ProviderCircuitBreaker`, optionally shared through `CacheBackend` |
| Runtime station provider | `LocalStationCatalogService`, optionally wrapped by recovery-only `FallbackStationDataService` |
| OpenAI recovery | `OpenAIWebStationDataService`; candidates remain `UNVERIFIED` and trip-specific |
| Station graph repository | `SqlAlchemyStationEdgeRepository` |
| Graph builder | `StationGraphBuilder`, directed sparse K-nearest graph |
| Routing cache | `GoongRoutingProvider` through `CacheBackend`; canonical route key and 300-second TTL |
| Redis | Optional; currently disabled |
| Planning execution | `PlanningRunService` + existing deterministic orchestration/runtime |
| Plan persistence | Atomic `save_plan_group`, normalized proposal column, ranked alternatives |
| Worker entrypoint | `src/apps/worker/stations.py` |

## Feature flags

- `STATION_CATALOG_DB_ENABLED=true`
- `STATION_GRAPH_ENABLED=true`
- `REDIS_CACHE_ENABLED=false`
- `PERSIST_ALL_PROPOSALS_ENABLED=true`
- `OPENAI_STATION_FALLBACK_ENABLED` is supported and requires a configured OpenAI key.
- `OPENAI_RECOVERY_ENABLED=true`

Post-stop safety override: after Phase H produced only a partial graph, the
application default and `.env.example` were changed to
`STATION_GRAPH_ENABLED=false`. The earlier values above remain the Phase A audit
snapshot.

## Hot-path call graph

```text
POST /api/v1/trips/{trip_id}/plans
  -> TripService.generate_trip_plan
  -> PlanningRunService.execute
  -> PlanningOrchestrator / PlanningRuntime
  -> GoongRoutingProvider
  -> OpenMeteoEnvironmentProvider
  -> LocalStationCatalogService
  -> SqlAlchemyStationCatalogRepository
  -> SqlAlchemyStationEdgeRepository
  -> existing AdaptiveStationPlanner / EnergyTool / FeasibilityTool
```

`VinFastLocatorClient` is instantiated only by the worker entrypoint. Production API dependency wiring instantiates `LocalStationCatalogService`; it does not instantiate `VinFastStationDataService` or `VinFastLocatorClient`.

OpenAI station search is exposed through the recovery half of `FallbackStationDataService`; it is not the canonical station repository and does not perform nationwide ingestion.

## Numerical/search lock hashes

These hashes are recorded before rollout actions and must match at the end:

| File | SHA-256 |
|---|---|
| `energy_tool.py` | `548AB5447AEE7415A4C6CBEC38C7A59D11C0792F71D76E3A76DB300E5C9D5D11` |
| `feasibility_tool.py` | `BDB6334B1FF088BC939ACF67A2CC7587028092B2DBBF40EBF70C6CEF8D8396AA` |
| `adaptive_station_planner.py` | `B8196EED62A6D366C3E8236BF8C9B7485BE44A31267FC2F1E89C76A3CDDA59FE` |

## Phase A acceptance

- [x] Runtime planner has zero VinFast detail HTTP dependency in production wiring.
- [x] OpenAI web search remains recovery-only.
- [x] Energy/SOC/charging files were not modified during Phase A.
- [x] Independent idempotent ingestion and graph-builder commands already exist.
- [x] API compatibility is re-verified by the Phase B baseline suite.
