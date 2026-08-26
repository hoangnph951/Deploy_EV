# Feature 1 - OSRM Station Graph Implementation Log

Ngày cập nhật: 2026-08-22 (Asia/Saigon)

## Kết luận hiện tại

Phần code, schema, migration và automated acceptance cho hướng PostGIS +
self-hosted OSRM đã được triển khai. Rollout runtime vẫn là **NO-GO** vì máy hiện
tại chỉ cấp khoảng 3,95 GB RAM cho Docker; preprocessing bản đồ Việt Nam chưa
hoàn tất. `STATION_GRAPH_ENABLED=false` được giữ nguyên.

Không có OSRM graph version nào được tạo trong PostgreSQL và không có partial
OSRM graph nào có thể bị runtime đọc.

## Kiến trúc đã triển khai

1. VinFast bulk catalog là nguồn charging location canonical.
2. Graph builder chỉ đọc location lifecycle `active=true`, coordinate hợp lệ và
   quality `VERIFIED` hoặc `PARTIAL` của đúng active dataset version.
3. PostGIS chọn tối đa K candidate gần nhất theo không gian; SQLite dùng
   Haversine deterministic cho test/dev.
4. OSRM Table API tính road distance và duration cho một origin cùng tối đa K
   destination trong một request local.
5. Edge là directed, tối đa K outgoing edge/origin, do đó `edges <= N * K`.
6. Edge build vào graph version `BUILDING`. Runtime chỉ join graph version
   `ACTIVE`; activation diễn ra atomically sau khi đủ toàn bộ node.
7. Runtime station eligibility được kiểm tra riêng trước charging action. Trạng
   thái `BUSY` không làm topology mất edge; hard-unavailable status không được
   dùng làm charging stop.
8. Road invalidation dùng exact `routing_provider + profile + road_version +
   station_dataset_version`, không dùng runtime ACTIVE/BUSY status.

## Thay đổi chính

| Thành phần | File | Nội dung |
|---|---|---|
| Atomic schema | `migrations/versions/20260822_1700_add_atomic_station_graph_versions.py` | Tạo `station_graph_versions`, backfill 40 legacy edge vào version `FAILED`, thêm FK `graph_version_id` và unique theo version |
| ORM/domain | `src/packages/core/trips/infrastructure/models.py`, `domain/station_graph.py` | Model graph version và exact edge ownership |
| Repository | `infrastructure/station_graph_repository.py` | BUILDING/ACTIVE/SUPERSEDED/FAILED, atomic activation, active-only reads, K cap, optimistic checkpoint |
| Candidate query | `infrastructure/station_catalog_repository.py` | PostGIS spatial query và SQLite fallback, bind đúng dataset version |
| OSRM adapter | `infrastructure/osrm_routing.py` | Table/Route API, `[lng,lat]`, retry bounded, fail closed, không synthetic route |
| Graph builder | `application/station_graph_builder.py` | Một matrix call/origin, chunk resume, checkpoint, activate khi complete |
| Worker/runtime | `src/apps/worker/stations.py`, `api/dependencies.py` | Chọn OSRM cho station graph, đọc road version từ file, feature flag vẫn tắt |
| Deployment | `docker-compose.yml` | OSRM v26.6.5-debian, MLD, mmap, max table size 100, chỉ bind localhost |
| Bootstrap | `scripts/prepare_osrm_vietnam.ps1`, `docker/osmium/Dockerfile` | Download, checksum, car-profile prefilter, resumable tool-input checks, trial validation |

## Atomic/concurrency guarantees

- Runtime query bắt buộc graph version `ACTIVE` và source/destination location
  lifecycle còn active.
- Một graph build lỗi hoặc dừng giữa chunk vẫn ở `BUILDING`, không visible.
- Checkpoint mang expected previous counter/location. Worker stale bị reject,
  không thể double-increment `processed_node_count`.
- Matrix provider outage được re-raise; builder không checkpoint và không biến
  outage thành hàng loạt unreachable edge.
- Activation lock graph version, xác nhận active station dataset, node count và
  maximum out-degree trước khi supersede active version cũ trong cùng transaction.
- `ACTIVE -> BUSY` không đổi graph version/edge. Location lifecycle hoặc road
  snapshot mới tạo graph version mới.

## Migration evidence

- Backup trước migration:
  `data/rollout_backups/f1-pre-migration-20260822T150929+0700.json.gz`
- SHA-256 backup:
  `38e79b6413f785765fc93335941fd83357328a3b0b45b330d7e452f2df4b82b0`
- PostgreSQL head: `20260822_1700`.
- PostGIS: `3.3`; GIST location index có mặt.
- Current DB graph state: 1 `FAILED` legacy graph version, 40 legacy Goong
  edges, 0 OSRM graph version, 0 active graph version.
- Active canonical locations: 23.919.

## OSRM bootstrap evidence

### Input provenance

- Geofabrik source: `vietnam-latest.osm.pbf`, 327.024.801 bytes.
- Source SHA-256:
  `d05e060a187b9cc2fa0793e0ea34885ccd082759a58cd0fbf7f0f34b293b68a4`.
- Embedded OSM timestamp: `2026-08-21T20:21:11Z`.
- OSRM image: `ghcr.io/project-osrm/osrm-backend:v26.6.5-debian`.
- Image digest:
  `sha256:7e2d775e5dd1f6752f679621e79dcff3b6bc37266733c771a360af9b3d652205`.
- Osmium image is built locally from pinned Debian digest with
  `osmium-tool=1.15.0-1`.
- Car whitelist-filtered PBF: 199.198.238 bytes.
- Filtered SHA-256:
  `3ff19e09a8be80bdaec3b7533d73ab642bfe4e4e5dfd372461f88440358c9dab`.
- Expected road version after successful trial:
  `osrm-26.6.5-debian-driving-vietnam-3ff19e09a8be`.

### Attempts and blocker

1. The bare calendar tag `v26.6.5` was not available in GHCR. Registry
   validation found the correct official image tag `v26.6.5-debian`; it supports
   `--list-inputs`, `--trial` and `--mmap` and is the final deployment pin.
2. Full PBF extraction was killed by the Linux OOM killer at about 3,38 GiB RSS;
   Docker had only 3,95 GB total memory.
3. A broad `highway=*` filter still retained 30,8 million nodes and remained too
   close to the memory limit.
4. The final filter matches all 16 highway values in v26.6.5 `car.lua` plus
   ferry, shuttle train and turn restrictions. The exact filtered checksum is
   recorded above.
5. Resource diagnostics used v6.0.0 before the correct calendar-image suffix was
   discovered. Its whitelist extract retained 25.805.460 nodes and 2.767.856
   ways, then remained in obstacle collection for about 1 hour 34 minutes on the
   7,7 GB host. A temporary 2 GB swap file prevented OOM but did not reach the
   next phase inside the bounded rollout window. The exact container was stopped;
   the temporary swap was disabled and removed.
6. The final v26.6.5-debian routing input was prepared and checksummed with
   `-PrepareRoutingInputOnly`; preprocessing was intentionally not restarted on
   the resource-constrained host.

No `road-version.txt`, final MLD artifacts, running OSRM service, smoke request,
or OSRM graph DB version was produced. Resume on a builder host with materially
more RAM; recommended operational starting point is at least 6-8 GB available to
Docker and a host with at least 12 GB physical RAM.

## Automated acceptance evidence

| Check | Result |
|---|---:|
| Full backend suite | 135 passed, 5 expected xfailed |
| Focused formula/OSRM/graph/runtime suite | 13 passed |
| OSRM + atomic graph targeted suite | 11 passed |
| Repository-wide Ruff | PASS |
| Docker Compose config | PASS |
| PowerShell bootstrap parse | PASS |
| Alembic current | `20260822_1700 (head)` |
| Formula numerical golden tests | PASS |

Acceptance tests cover coordinate order, Table null/unreachable semantics,
provider failure without checkpoint, atomic visibility, chunk resume, stale
worker rejection, active lifecycle filtering, directed/K-bounded topology and
runtime status behavior.

## Resume commands

Run on a host with sufficient Docker memory:

```powershell
& .\scripts\prepare_osrm_vietnam.ps1
docker compose --profile routing up -d osrm
python -m src.apps.worker.stations build-station-graph --origin-limit 250
```

Repeat the worker command until `processed_node_count == expected_node_count`.
The builder resumes the same `BUILDING` version automatically. Verify the
checklist before changing `STATION_GRAPH_ENABLED`.

## Rollback and safety

- Keep `STATION_GRAPH_ENABLED=false` until a complete OSRM version is ACTIVE.
- Stop OSRM with `docker compose --profile routing stop osrm` if needed.
- Do not downgrade the migration while graph data exists; prefer a forward-fix.
- A failed/new road snapshot remains isolated in `BUILDING`/`FAILED`; the prior
  ACTIVE version is not replaced until atomic activation succeeds.

## Resume attempt - 2026-08-23

Docker Desktop was available on context `desktop-linux` with 12 CPUs and
`8173850624` bytes total memory (about 7.61 GiB). The pinned source and filtered
PBF were prepared by `scripts/prepare_osrm_vietnam.ps1`; the OSRM image was
pulled at digest `sha256:7e2d775e5dd1f6752f679621e79dcff3b6bc37266733c771a360af9b3d652205`.

The resumed `osrm-extract` parsed approximately 25.8 million nodes and 26.4
million edges and wrote partial `.osrm` files, but the Docker client later
reported `error waiting for container: unexpected EOF`. The script exited with
`osrm-extract failed`; no `road-version.txt` was written. Because the required
extract inputs are incomplete, partition/customize/trial, OSRM smoke, graph
build and activation were not run. The partial files are retained for the
script's normal resume/repair path and are not runtime-visible.

Database checks in the same attempt passed: Alembic `20260822_1700 (head)`,
PostGIS 3.3, required schema and GIST index. Repository-wide pytest passed with
168 tests. Operational rollout remains **NO-GO** until extraction and all later
gates complete on a stable builder with sufficient Docker memory.

## Resume attempt - 2026-08-23 (Docker OOM confirmation)

The Docker engine was restarted after the previous client-side `unexpected EOF`.
It came back with 8 CPUs and `10429358080` bytes memory (about 9.71 GiB).
`osrm-extract` was retried with 6 threads and then 4 threads. Both attempts
were killed by the Docker WSL Linux OOM killer during edge-expanded graph
generation. Kernel evidence recorded:

- 6-thread attempt: `osrm-extract` RSS about 9.2 GiB, killed by OOM killer.
- 4-thread attempt: `osrm-extract` RSS about 4.8 GiB, killed by OOM killer.

The filtered PBF and partial `.osrm` outputs remain non-runtime-visible;
`road-version.txt` was not created. Partition, customize, trial, OSRM Table
smoke, station graph build, and Phases I-Q were not run. The host requires at
least 12 GiB Docker memory (with swap enabled) before the next retry.

## Successful nationwide rollout - 2026-08-23

WSL/Docker was configured with 12 GB memory, 6 CPUs and 8 GB swap. The pinned
Vietnam preprocessing pipeline completed `osrm-extract`, `osrm-partition`,
`osrm-customize` and `osrm-routed --trial`. Extract peak memory was
`11819954176` bytes. The script trial syntax was corrected to pass an explicit
boolean (`--trial true`). The generated road version is
`osrm-26.6.5-debian-driving-vietnam-87db807f8d67`.

The local service started without a restart loop. A representative Table request
returned `code=Ok`, distance `5643.4 m` and duration `396.6 s`.

Graph version `09ac16c6-0d95-4f9f-9ae5-af3605293162` processed all 23,919
origins and atomically transitioned from `BUILDING` to `ACTIVE`. Final database
evidence: 946,138 directed edges, maximum out-degree 40, zero degree violations,
zero inactive/missing endpoints, and an exact road-version match. The legacy
Goong graph remains `FAILED` and runtime-invisible.

Operational fixes made during the build:

- graph queries load only the columns needed for topology;
- PostGIS nearest-neighbor selection uses deterministic KNN GiST ordering;
- candidate selection and edge read/write are batched per chunk;
- OSRM non-positive matrix cells are treated as individually unreachable;
- all changes preserve directed K=40 topology and atomic checkpoints.

Acceptance reruns: focused F1 15 passed, planner/API/persistence/cache 26 passed,
full backend 169 passed, Ruff passed, frontend typecheck/build passed.
