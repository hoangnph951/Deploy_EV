# Feature 1 Station Graph Report

## Status

**PARTIAL / NO-GO** — the controlled real-provider chunk passed, but the
nationwide graph was not completed. Later rollout phases must remain disabled.

## Configuration

- Station dataset generation: `743`
- Routing provider: `GOONG_DIRECTIONS`
- Road version: `goong-car-v1`
- Maximum outgoing neighbors (K): `40`
- Coarse radius: `450 km`
- Maximum accepted road leg: `500 km`
- Eligible node policy: active lifecycle, valid coordinate, `VERIFIED` or
  `PARTIAL`; runtime `ACTIVE`/`BUSY` status is not part of topology.

## Controlled Chunk

- Origins processed: `1`
- Last processed location id: `1`
- Candidate pairs: `40`
- Goong Direction calls: `40`
- Cache hits: `0`
- Edges written: `40`
- Route failures: `0`
- Road-distance rejections: `0`
- Duration: `51.005s`

## Current Graph

| Metric | Value |
|---|---:|
| Eligible nodes | 23,919 |
| Current-version edges | 40 |
| Origins with edges | 1 |
| Average out-degree across all eligible nodes | 0.001672 |
| Median out-degree | 0 |
| Maximum out-degree | 40 |
| Zero-outdegree nodes | 23,918 |
| Edges touching inactive nodes | 0 |
| Invariant bound `N × K` | 956,760 |

The persisted partial graph satisfies `edges <= N × K` and `max degree <= K`,
but it is not structurally complete enough to enable nationwide planning.

## Safety and Scale Findings

- The worker now supports bounded/resumable chunks with `--origin-limit` and
  `--start-after-location-id`.
- Graph reads hide edges whose source or destination lifecycle is inactive.
- Edge upsert locks the source node and trims current road-version out-degree to
  K, including runtime write-through edges.
- The graph read-model uses PostGIS in PostgreSQL and deterministic Haversine
  coarse ranking in SQLite; exact persisted distance/duration comes from Goong.
- At the current one-Direction-call-per-pair implementation, a full dense upper
  bound is 956,760 provider requests. The official default Goong REST limit is
  1,000 requests/day, so an elevated quota or an approved matrix/batched graph
  strategy is required before the full build can pass.

Official provider references:

- [Goong API key rate limits](https://docs.goong.io/rest/api-key/)
- [Goong Distance Matrix API](https://docs.goong.io/rest/distance_matrix/)

## Resume Example

With an operator-approved request budget, the next bounded chunk is:

```powershell
.\.venv\Scripts\python.exe -m src.apps.worker.stations build-station-graph `
  --start-after-location-id 1 `
  --origin-limit 20
```

Do not run the unbounded command under the default provider quota.

## Self-hosted OSRM follow-up - 2026-08-22

The graph implementation now supports self-hosted OSRM Table requests and atomic
graph versions. The 40 legacy Goong edges were assigned to a `FAILED` version,
so runtime cannot consume this partial graph. Current PostgreSQL state is 0
ACTIVE graph versions and 0 OSRM graph versions.

Vietnam OSRM preprocessing did not complete on the current 3.95 GB Docker host;
therefore no local Table smoke request or nationwide build was launched. The
feature flag remains disabled. Detailed evidence and the remaining checklist are
in `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md` and
`docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`.

## Nationwide OSRM graph - 2026-08-23

The self-hosted OSRM rollout completed after Docker was configured with 12 GB
RAM and 8 GB swap. Graph version
`09ac16c6-0d95-4f9f-9ae5-af3605293162` is now `ACTIVE` for road version
`osrm-26.6.5-debian-driving-vietnam-87db807f8d67`.

| Metric | Value |
|---|---:|
| Eligible/processed nodes | 23,919 / 23,919 |
| Directed edges | 946,138 |
| Sparse upper bound | 956,760 |
| Maximum out-degree | 40 |
| Degree violations | 0 |
| Inactive/missing endpoints | 0 |

The legacy 40-edge Goong graph remains `FAILED`. Runtime enablement remains off
pending final owner approval and reconciliation of the historical formula/search
lock snapshot with the merged F3/F4 baseline.
