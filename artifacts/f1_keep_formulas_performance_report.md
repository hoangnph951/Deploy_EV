# F1 Performance Evidence

## Execution

- Date: 2026-08-23, Asia/Saigon
- Docker allocation: 12 GB RAM, 6 CPUs, 8 GB swap
- OSRM image: `ghcr.io/project-osrm/osrm-backend:v26.6.5-debian`
- OSRM road version: `osrm-26.6.5-debian-driving-vietnam-87db807f8d67`

## OSRM Table smoke

Ten identical local Table requests returned `code=Ok` with non-null distance and
duration (`5643.4 m`, `396.6 s`). Client latency was average `11.19 ms`, P95
`93.49 ms` (the first request included warm-up). The service stayed healthy.

## Nationwide graph build

- Graph version: `09ac16c6-0d95-4f9f-9ae5-af3605293162`
- Eligible/processed origins: `23,919 / 23,919`
- Directed edges: `946,138`
- Maximum out-degree: `40`
- Matrix calls: one local OSRM Table request per origin
- Provider detail calls: `0`
- Status transition: `BUILDING -> ACTIVE` atomically

The worker used 250-origin chunks with batched PostGIS KNN candidate selection
and edge persistence. No concurrent graph workers were used.

## Planner performance gate

The repository-wide suite (`169 passed`) and planner/API/persistence/cache subset
(`26 passed`) passed. A live `POST /plans` benchmark with
`STATION_GRAPH_ENABLED=true` remains deferred because the safe runtime flag is
disabled pending owner reconciliation of the stale Phase-A formula/search lock
hashes against the merged F3/F4 baseline.
