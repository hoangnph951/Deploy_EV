# FEATURE 1 — FULL REFACTOR / PRODUCTIONIZATION SPEC
## Variant A — Giữ nguyên toàn bộ công thức và hành vi tính toán hiện tại

> **Cập nhật 22/08/2026 sau log 403 VinFast:** Variant A đã được sửa để `POST /plans` không gọi VinFast warm-up/detail endpoint; station data được phục vụ từ local PostgreSQL/PostGIS, OpenAI web search chỉ là recovery `CONDITIONAL`, và 401/403 kích hoạt provider-level circuit breaker.
> Mục tiêu: refactor Feature 1 hiện tại thành kiến trúc có dữ liệu trạm sạc lưu cục bộ, PostGIS, graph/cache dùng chung giữa nhiều replica, background ingestion/graph build và provenance đầy đủ **mà không làm thay đổi kết quả số học hiện tại**.
>
> File này là implementation spec dành cho Codex. Hãy đọc repo hiện tại trước khi sửa code. Không giả định line number cố định. Tôn trọng architecture/ports hiện có.
>
> Phạm vi vẫn là F1. Không triển khai Confirm/Reject/Activate của F2.

---

# 0. Nguyên tắc bắt buộc

## 0.1. Numerical compatibility lock

KHÔNG được thay đổi bất kỳ công thức/hằng số/decision rule hiện có nào liên quan đến:

- temperature factor;
- payload factor;
- weather factor;
- elevation energy/regen;
- effective consumption;
- energy per leg;
- SOC drop/arrival;
- target departure SOC;
- charging power và charging time;
- safe range;
- minimumStops/maxStops;
- corridor profiles;
- detour coarse estimate;
- beam width / branch width / edge validation limit;
- candidate ranking;
- feasibility hard constraints;
- soft-risk points;
- BALANCED / FASTEST / SAFEST ranking heuristic;
- reserve boundary semantics;
- raw SOC vs rounded SOC semantics.

Các test golden phải chứng minh output số học trước/sau refactor giống nhau trong cùng fixture.

Nếu cần sửa bug kỹ thuật nhưng bug fix có khả năng thay output planning, phải:
1. thêm test reproducing bug;
2. tách bug fix thành commit rõ ràng;
3. không trộn vào refactor cache/DB.

## 0.2. LLM boundary

Giữ nguyên nguyên tắc:

```text
LLM = recovery/ranking/explanation
Deterministic tools = route facts, station filtering, energy, SOC, safety
```

LLM không được:
- tự tạo route;
- tự suy đoán SOC;
- bypass feasibility;
- nâng plan `INFEASIBLE` thành feasible;
- diễn giải `ACTIVE/BUSY` thành số cổng đang trống.

## 0.3. Fail closed

Nếu không chứng minh được route/station/SOC safety:
- không tạo synthetic production route;
- không tạo synthetic charging station;
- không persist plan như plan có thể dùng;
- trả đúng business/provider outcome hiện tại.

## 0.4. Source legality

Chỉ sử dụng endpoint/dataset công khai hoặc được nhóm có quyền truy cập.
Không reverse-engineer authentication/private API.
Respect rate limit, cache headers và điều khoản nguồn.

---

# 1. Vấn đề kiến trúc hiện tại cần sửa

Feature hiện tại đã có các boundary tốt, nhưng còn các vấn đề production:

1. station dataset chỉ nằm process-local và được refresh từ VinFast locator trong runtime;
2. station detail cache process-local 300 giây;
3. route cache process-local 300 giây;
4. nhiều replica không dùng chung station snapshot/cache;
5. planner có thể gọi lại route `station -> station` rất nhiều lần;
8. chưa có persistent station catalog;
9. chưa có station connectivity graph;
10. stale dataset fallback không có max-age cứng;
11. chưa phân biệt rõ station `VERIFIED` / `PARTIAL` / `UNVERIFIED`;
12. OpenAI web search hiện là recovery đúng hướng nhưng cần được giữ tách biệt khỏi canonical station catalog;
13. plan persistence trộn `proposal` vào `assumptions`;
14. conditional plan/candidates không được lưu;
15. version allocation chưa atomic;
16. Trip status chưa phản ánh planning lifecycle;
17. provenance UI chưa driven bởi `plan.provenance`;
18. policy threshold chưa nối hoàn chỉnh;
19. synchronous request có thể giữ connection lâu;
20. lint gate đang đỏ;
21. station progress/corridor filtering hiện dựa sampled polyline và Haversine, nhưng trong variant A **không được thay thuật toán đó trong default path** vì phải giữ numerical/search parity.

---

# 2. Kiến trúc đích

```text
React/Vite
   |
FastAPI
   |
TripService
   |
PlanningOrchestrator
   |
LangGraph adapter
   |
PlanningRuntime
   +--------------------+
   |                    |
RoutingProvider      StationRepository
   |                    |
Goong             PostgreSQL/PostGIS
   |                    |
RouteCache         Station catalog
Redis              EVSE/connectors
   |               Station snapshot/version
   |
StationEdgeCache/GraphRepository
   |
PostgreSQL station_edges
   |
EnergyTool / FeasibilityTool / SafePlanRanker
   |
Plan persistence

Background workers:
- StationIngestionJob
- StationDetailHydrationJob
- StationGraphBuilderJob
- CacheRefresh/Invalidation
```

Runtime planner vẫn sử dụng adaptive beam search hiện tại.
Graph/cache chỉ thay thế những network calls có kết quả tương đương; không thay logic search.

---

# 3. Database schema mới

Tạo Alembic migration mới. Không sửa migration cũ.

## 3.1. `charging_dataset_versions`

```text
id UUID/BigInt PK
provider                  VARCHAR NOT NULL
generation                VARCHAR NULL
source_url                TEXT NOT NULL
source_last_modified_at   TIMESTAMPTZ NULL
retrieved_at              TIMESTAMPTZ NOT NULL
valid_until               TIMESTAMPTZ NULL
checksum                   VARCHAR NULL
status                     VARCHAR NOT NULL
metadata_json              JSONB NULL
```

`status`:
- ACTIVE
- SUPERSEDED
- FAILED

Chỉ một ACTIVE version/provider.

## 3.2. `charging_locations`

```text
id                       BIGSERIAL PK
provider                 VARCHAR NOT NULL
external_id              VARCHAR NOT NULL
dataset_version_id       FK charging_dataset_versions
name                     TEXT NOT NULL
address                  TEXT NULL
category_slug            VARCHAR NULL
access_type              VARCHAR NULL
charging_publish         BOOLEAN NOT NULL
station_status           VARCHAR NULL
latitude                 DOUBLE PRECISION NOT NULL
longitude                DOUBLE PRECISION NOT NULL
location                 GEOGRAPHY(POINT, 4326) NOT NULL
source_url               TEXT NULL
source_updated_at        TIMESTAMPTZ NULL
retrieved_at             TIMESTAMPTZ NOT NULL
raw_payload              JSONB NULL
active                   BOOLEAN NOT NULL DEFAULT TRUE
created_at               TIMESTAMPTZ NOT NULL
updated_at               TIMESTAMPTZ NOT NULL
```

Unique:

```text
(provider, external_id)
```

Indexes:
- GIST(location)
- provider
- active
- station_status

## 3.3. `charging_evses`

```text
id
location_id FK
external_evse_id NULL
depot_status NULL
status NULL
retrieved_at
source_updated_at
raw_payload JSONB NULL
```

## 3.4. `charging_connectors`

```text
id
evse_id FK
connector_type
normalized_connector
max_electric_power_kw
raw_payload JSONB NULL
```

Không tạo field `available_ports` nếu upstream không thực sự cung cấp realtime availability.

## 3.5. Station data quality

Thêm vào `charging_locations`:

```text
detail_quality VARCHAR NOT NULL
```

Allowed values:

```text
VERIFIED
PARTIAL
UNVERIFIED
```

Semantics:

- `VERIFIED`: location + connector + usable charging power đã được xác minh từ nguồn được policy tin cậy và còn trong freshness window;
- `PARTIAL`: location đã biết nhưng thiếu hoặc quá cũ connector/power/technical detail;
- `UNVERIFIED`: dữ liệu đến từ recovery/web evidence hoặc nguồn chưa đủ trust để đi vào primary plan.

Không tự động suy diễn:

```text
VinFast location -> CCS2
VinFast location -> 150 kW
BUSY -> 0 available ports
port_count -> available_ports
```

Nếu upstream không cung cấp port-level realtime availability:

```text
available_ports = NULL
```

## 3.6. `station_external_evidence`

Lưu evidence phục vụ recovery/enrichment nhưng không tự động biến thành canonical verified data.

```text
id
location_id NULL
provider
field_name
field_value_json
source_url
retrieved_at
source_updated_at NULL
verification_status
raw_evidence JSONB NULL
```

`verification_status`:

```text
UNVERIFIED
CORROBORATED
REJECTED
```

OpenAI web-search result có thể được lưu ở đây, nhưng **không được tự động promote station thành `VERIFIED`**.

## 3.7. `station_edges`

Persistent precomputed routing facts.

```text
id BIGSERIAL PK
from_location_id FK
to_location_id FK
routing_provider VARCHAR NOT NULL
routing_profile VARCHAR NOT NULL
road_version VARCHAR NOT NULL
distance_km DOUBLE PRECISION NOT NULL
duration_minutes DOUBLE PRECISION NOT NULL
geometry_polyline TEXT NULL
provider_source_url TEXT NULL
provider_retrieved_at TIMESTAMPTZ NOT NULL
computed_at TIMESTAMPTZ NOT NULL
valid_until TIMESTAMPTZ NULL
```

Unique:

```text
(from_location_id, to_location_id, routing_provider, road_version)
```

Edge có hướng. Không giả định A->B == B->A.

Không lưu:
- reachable;
- required SOC;
- energy kWh;
- safety;
vì các giá trị đó phụ thuộc vehicle/SOC/environment.

## 3.6. Tách `plan_versions.proposal`

Thêm column:

```text
proposal JSONB
```

Giữ `assumptions` chỉ chứa AssumptionSnapshot.

Migration:
- copy `assumptions["proposal"]` sang `proposal`;
- remove nested proposal sau khi verify;
- repository mới đọc `proposal`.

Backward-compatible read trong một release:
- ưu tiên column `proposal`;
- nếu NULL thì đọc legacy nested field.

Sau một release mới có thể bỏ legacy fallback.

## 3.7. Planning run

Tạo:

```text
planning_runs
-------------
id
trip_id
status
started_at
finished_at
trace_id
request_snapshot JSONB
result_code
error_code
error_detail JSONB
```

Status:
- QUEUED
- RUNNING
- SUCCEEDED
- FAILED

Trong Variant A có thể vẫn giữ endpoint synchronous, nhưng run phải được persist để sau này chuyển async không phá domain model.

---

# 4. Station ingestion architecture

## 4.1. Tạo ports

Trong core/application, tạo protocol:

```python
class StationCatalogRepository(Protocol):
    def get_dataset_version(...) -> ...
    def query_locations_for_planning(...) -> ...
    def get_location_detail(...) -> ...
    def upsert_dataset(...) -> ...
```

Infrastructure:
- `SqlAlchemyStationCatalogRepository`

Không để planner gọi thẳng VinFast HTTP adapter.

## 4.2. Tách upstream adapter và local repository

Hiện `VinFastStationDataService` đang vừa:
- download;
- cache;
- filter;
- detail fetch;
- normalize.

Tách thành:

```text
VinFastLocatorClient
    -> chỉ HTTP + parse provider response
    -> chỉ được gọi bởi ingestion/background job

StationIngestionService
    -> normalize + upsert DB
    -> duy trì last-known-good snapshot

SqlAlchemyStationCatalogRepository
    -> planner reads local DB only

StationDetailHydrator
    -> background enrichment only
    -> KHÔNG được gọi bên trong POST /plans

OpenAIWebStationDataService
    -> recovery cho một trip cụ thể
    -> KHÔNG phải canonical station catalog
```

**Hard rule:**

```text
POST /api/v1/trips/{id}/plans
MUST NOT call:
- VinFast locator warm-up page
- /vn_vi/get-locator/{entity_id}
- whole VinFast bulk download
```

Planner request chỉ được đọc local station catalog + cache/graph.

## 4.3. Bulk sync

Job:

```text
read locators-meta.json
  -> compare generation with ACTIVE DB version
  -> if same: no-op
  -> if changed:
       download bulk file
       validate
       checksum
       transaction:
          insert new dataset version
          upsert locations
          mark missing old locations inactive
          activate new version
       enqueue optional detail hydration for changed/new stations
       enqueue graph invalidation/update
```

Bulk location records được lưu ngay cả khi chưa có detail:

```text
location/name/status known
connector/power unknown
=> detail_quality = PARTIAL
```

Không để planner download whole bulk dataset.

## 4.4. Max stale age / last-known-good

Thêm settings:

```text
STATION_DATASET_REFRESH_SECONDS
STATION_DATASET_MAX_STALE_SECONDS
STATION_DETAIL_REFRESH_SECONDS
STATION_DETAIL_MAX_STALE_SECONDS
```

Nếu refresh upstream lỗi:
- giữ nguyên ACTIVE last-known-good snapshot;
- nếu dataset age <= max stale: planner tiếp tục dùng theo policy;
- nếu technical detail age vượt threshold: hạ `VERIFIED -> PARTIAL`, không giả dữ liệu còn fresh;
- nếu toàn bộ usable station data vượt hard max age: station data state = unavailable/recovery-required;
- **không** kết luận `INFEASIBLE` chỉ vì upstream đang lỗi.

Phân biệt:

```text
UNKNOWN / DATA_UNAVAILABLE != NO_STATION_EXISTS
```

## 4.5. Detail hydration — background only

Detail endpoint `/vn_vi/get-locator/{entity_id}` là optional enrichment source, không phải runtime dependency.

Queue có thể ưu tiên:
1. new station;
2. changed station;
3. frequently-used corridors;
4. detail sắp hết freshness;
5. admin-requested verification.

Không có read-through detail trong planning request.

Nếu detail hydration thành công:
- upsert EVSE/connectors;
- cập nhật source timestamps;
- recompute `detail_quality`.

Nếu detail hydration thất bại:
- giữ last-known-good technical detail;
- hạ quality theo freshness policy nếu cần;
- không xóa station chỉ vì provider tạm lỗi.

## 4.6. Provider access denied / circuit breaker

Phân loại HTTP:

```text
401/403 -> PROVIDER_ACCESS_DENIED, non-retryable trong cùng attempt
429     -> PROVIDER_RATE_LIMITED, honor Retry-After/cooldown
5xx     -> transient provider error, bounded retry
timeout -> bounded retry
404     -> entity-specific missing/not-found
```

Observed production behavior cho thấy warm-up page và hàng loạt detail URL có thể cùng trả 403.
Vì vậy:

```text
warm-up 401/403
    -> DO NOT launch detail pool

hoặc nếu warm-up là optional:
first detail probe 401/403
    -> open provider-level circuit
    -> stop remaining detail requests
```

Circuit là provider-level, không phải station-level.

Redis/shared state đề xuất:

```text
provider-circuit:vinfast-detail
```

Value:

```json
{
  "state": "OPEN",
  "reason": "ACCESS_DENIED",
  "opened_at": "...",
  "retry_after": "..."
}
```

Không dùng browser spoofing/anti-bot bypass làm production dependency.
Chỉ dùng endpoint/dataset mà nhóm có quyền truy cập.

## 4.7. OpenAI web search recovery

Giữ behavior F1 hiện tại nhưng làm boundary rõ hơn:

```text
Primary path:
local StationCatalogRepository
    -> VERIFIED stations
    -> deterministic planner

Nếu không chứng minh được safe primary plan vì thiếu usable station data:
recovery node
    -> OpenAIWebStationDataService
    -> structured web candidate
    -> source URL validation
    -> geocode
    -> corridor filter
    -> Goong route-check
    -> energy/SOC
    -> feasibility
```

OpenAI candidate:

```text
source = OPENAI_WEB_SEARCH
detail_quality = UNVERIFIED
freshness = STALE/UNKNOWN theo current contract
```

Nếu dùng candidate này:
- outcome vẫn là `CONDITIONAL`;
- không được trả normal `PLAN_CREATED` chỉ nhờ LLM data;
- LLM không được bypass safety gate.

OpenAI web search **không dùng để crawl toàn bộ Việt Nam và populate canonical DB**.
Có thể lưu evidence vào `station_external_evidence` để audit/review.

## 4.8. Primary planner eligibility

Default:

```text
VERIFIED   -> eligible primary planner
PARTIAL    -> not eligible for primary charging commitment;
              may participate only in recovery/enrichment workflow
UNVERIFIED -> recovery only; CONDITIONAL if final plan uses it
```

Global connectivity graph có thể chứa `VERIFIED` + `PARTIAL` nodes vì edge chỉ biểu diễn road connectivity.
Nhưng Charging Planner phải kiểm tra technical eligibility trước khi tạo charging action.

## 4.9. Preserve current detail-budget semantics without network calls

Variant A phải giữ search behavior càng sát current implementation càng tốt.

Các logical budgets hiện tại như:

```text
24 -> 48 -> 96 detail backfill
target 12 candidates/window
```

không còn điều khiển HTTP detail calls trong `/plans`.
Thay vào đó chúng điều khiển **số station records được materialize/consider từ local catalog theo cùng ranking/order**.

Mục tiêu:
- cùng fixture station snapshot -> cùng candidate selection;
- không đổi beam-search shape;
- không phát sinh VinFast HTTP request trong planning.

## 4.10. Normalization

Giữ nguyên normalization hiện có:

```text
COMBO / CCS -> CCS2
62196_T2 / TYPE_2 -> TYPE2
```

Giữ nguyên filter status/connector/power đối với station đã có technical detail.
Station thiếu technical detail được lưu `PARTIAL`, không fabricate connector/power.

---

# 5. Redis/shared cache

Tạo abstraction:

```python
class CacheBackend(Protocol):
    get(...)
    set(...)
    delete(...)
    lock(...)
```

Implement:
- `InMemoryCacheBackend` test/local
- `RedisCacheBackend` production

Không để business logic import redis trực tiếp.

## 5.1. Route cache key

Key canonical:

```text
route:v1:{provider}:{origin6}:{destination6}:{ordered_waypoints_hash}
```

Value chứa đúng `RouteData` hiện tại.

TTL mặc định giữ 300 giây để parity.

## 5.2. Station detail cache

Key:

```text
station-detail:v1:{provider}:{external_id}:{dataset_generation}
```

TTL giữ 300 giây nếu cần parity cho background hydrator.

**Planning request không dùng cache miss để gọi VinFast detail.**
Source of truth runtime là DB; Redis chỉ acceleration cho dữ liệu đã được ingest/hydrate.

## 5.3. Planning request cache

Không cache final plan nếu request chứa station freshness có thể thay đổi mà key không version.
Nếu cache final plan, key phải chứa:

```text
origin bucket
destination bucket
initial SOC
vehicle profile version
policy version
station dataset generation
routing provider/road version
environment snapshot bucket
planner algorithm version
```

Variant A có thể bỏ qua final-plan cache nếu phức tạp.

---

# 6. Station connectivity graph

## 6.1. Mục tiêu

Giảm repeated routing call cho station-to-station legs đã từng/đã được precompute.

Graph không thay search algorithm hiện tại.

## 6.2. Graph builder

Tạo:

```text
src/packages/core/trips/infrastructure/station_graph_repository.py
src/packages/core/trips/application/station_graph_builder.py
```

Protocol:

```python
class StationEdgeRepository(Protocol):
    def get_edge(from_id, to_id, routing_provider, road_version): ...
    def upsert_edge(edge): ...
    def neighbors(location_id, ...): ...
```

Builder:
1. lấy active public charging locations;
2. dùng PostGIS coarse spatial neighborhood;
3. chỉ xét sparse K neighbors / max radius;
4. route-check bằng configured routing provider;
5. persist directed edge.

Config:

```text
STATION_GRAPH_ENABLED=true
STATION_GRAPH_MAX_NEIGHBORS=40
STATION_GRAPH_COARSE_RADIUS_KM=450
STATION_GRAPH_EDGE_MAX_AGE_SECONDS
STATION_GRAPH_ROAD_VERSION
```

Không build all-pairs.

## 6.3. Runtime use

Trong adaptive planner, khi cần verify `current station -> candidate station`:

```text
if both endpoints are persisted stations:
    try station_edges current road version
    if edge fresh:
        materialize RouteData-equivalent facts from edge
    else:
        call RoutingProvider and write-through edge
else:
    call RoutingProvider
```

Origin/destination không phải station:
- dùng RoutingProvider như hiện tại.

## 6.4. Exact parity

Station edge phải lưu giá trị từ cùng routing provider/profile.
Nếu graph edge khác provider/profile/road version:
- không được dùng thay exact route check.

---

# 7. Planner behavior — GIỮ NGUYÊN

Không thay adaptive planner algorithm.

Giữ:
- direct-trip-first;
- same search profiles;
- same corridor values;
- same coarse Haversine formula;
- same sampled polyline method;
- same logical detail/backfill budgets nhưng áp trên local catalog, không phải HTTP detail calls;
- same candidate ranking;
- same top-3 validation;
- same branch width 2;
- same beam width 4;
- same max 60 validations/profile;
- same 100% search departure assumption;
- same exact final simulation;
- same proposal ranking.

Chỉ thay source:

```text
BEFORE:
planner -> VinFast runtime dataset/detail HTTP

AFTER:
planner -> local StationCatalogRepository
        -> VERIFIED primary candidates
        -> PARTIAL/UNVERIFIED chỉ qua recovery policy
        -> NO VinFast detail HTTP in request
```

Nếu primary catalog không đủ dữ liệu để chứng minh plan:
- chạy OpenAI web-search recovery hiện có;
- verify bằng deterministic pipeline;
- plan dùng web candidate vẫn `CONDITIONAL`.

Graph edge cache chỉ thay network call bằng cached route facts tương đương.

---

# 8. Energy/SOC/charging formulas — FREEZE

Copy current formulas unchanged into tests and documentation.

## 8.1. Temperature

```text
kT = 1 + min(0.20, abs(T - 22) * 0.004)
```

## 8.2. Payload

```text
k_payload = max(0.9, 1 + ((payload - 150) / 100) * 0.02)
```

## 8.3. Weather

```text
k_weather =
  1
  + min(0.08, precipitation * 0.01)
  + min(0.12, wind_speed * 0.003)
```

## 8.4. Elevation

```text
m = max(500, curb_weight + payload)

Wh_up =
  (m * 9.80665 * elevation_gain)
  / (3600 * 0.85)

Wh_regen =
  (m * 9.80665 * elevation_loss)
  / 3600
  * 0.60

Wh_elevation_per_km =
  max(0, Wh_up - Wh_regen)
  / max(1, route_distance_km)
```

## 8.5. Effective consumption

```text
effective =
  baseline_wh_per_km
  * kT
  * k_payload
  * k_weather
  + Wh_elevation_per_km
```

## 8.6. Energy/SOC

```text
E_leg_kWh =
  distance_leg_km * effective_wh_per_km / 1000

SOC_arrival =
  SOC_start
  - E_leg_kWh / max(10, usable_capacity_kWh) * 100
```

## 8.7. Required/target SOC

```text
SOC_required_next =
  distance_next
  * effective_consumption
  / (1000 * max(10, usable_capacity))
  * 100
  + reserve
  + 3

SOC_departure =
  min(100, max(SOC_arrival, 80, SOC_required_next))
```

## 8.8. Charging

```text
P_effective =
  max(1, min(P_station, P_vehicle) * 0.85)

E_added =
  (SOC_departure - SOC_arrival) / 100
  * max(10, usable_capacity)

t_charge_min =
  E_added / P_effective * 60
```

## 8.9. Risk

Giữ nguyên:
- STALE +35/stop
- BUSY +20/stop
- UNVERIFIED +40/stop
- thin final SOC +25
- cap 100
- current level boundaries.

---

# 9. Policy snapshot fixes không đổi formula

Mở rộng `AssumptionSnapshot` để chứa:
- `stale_station_hours_threshold`;
- `route_deviation_km_threshold`;
- `planner_algorithm_version`;
- `energy_model_version`;
- `station_dataset_generation`;
- `routing_provider`;
- `road_version`.

Giá trị hiện tại vẫn giữ nguyên.

Thay hard-coded 24h bằng policy field **chỉ nếu default field = 24 và golden tests chứng minh parity**.

---

# 10. Persistence fixes

## 10.1. Atomic plan version

Không dùng:

```python
len(existing_versions) + 1
```

Dùng transaction + DB allocation.

Một cách:
- `SELECT MAX(version) ... FOR UPDATE` trong transaction;
hoặc
- dedicated sequence per trip pattern;
hoặc
- retry unique-conflict có kiểm soát.

Viết concurrency test.

## 10.2. Persist alternatives

F1 tạo tối đa 3 proposals.
Persist tất cả proposals của planning run, không chỉ selected.

Thêm fields:

```text
plan_versions
-------------
planning_run_id
rank
strategy
is_primary
proposal JSONB
status
```

Không implement user confirmation.

## 10.3. Conditional plan

Persist conditional proposal với status riêng:

```text
CONDITIONAL
```

Nhưng không biến nó thành confirmable F2 state.

## 10.4. Trip lifecycle

F1 states:

```text
DRAFT
PLANNING
PLANNED
PLANNING_FAILED
```

Không thêm CONFIRMED/ACTIVE vì thuộc F2.

---

# 11. Provenance

Mở rộng provenance:

```text
ROUTE
STATION_DATASET
STATION_DETAIL
WEATHER
ELEVATION
VEHICLE_PROFILE
POLICY_CONFIG
PLANNER_ALGORITHM
ENERGY_MODEL
```

Mỗi plan phải chứa:
- source;
- source URL nếu có;
- retrieved_at;
- source_updated_at nếu có;
- version/generation.

Không fake source timestamp.

Khi Redis/DB cache hit:
- `retrieved_at` trong provenance phải là thời điểm HTTP source thực sự được fetch nếu contract muốn source retrieval time;
- có thể thêm `served_at` nếu cần.
Không reset `retrieved_at=now` chỉ vì parse cache.

---

# 12. Frontend

## 12.1. Data Trust panel

Loại bỏ hard-code source labels.

Render trực tiếp từ:

```text
plan.provenance
```

Hiển thị:
- source;
- age;
- version/generation;
- FRESH/STALE/UNVERIFIED;
- link nếu có.

## 12.2. Plan history

Nối `getTripPlans()` vào UI.

F1 chỉ đọc history, không confirm.

## 12.3. Alternatives

Khi reload page:
- alternatives phải lấy từ persisted plan versions;
- không phụ thuộc local state của response đầu tiên.

## 12.4. Conditional

Render persisted conditional plan.
Không tạo action Confirm; chỉ giữ recovery messaging của F1.

---

# 13. Async-ready planning

Variant A chưa bắt buộc đổi HTTP contract sang async.

Nhưng code phải tách:

```python
PlanningRunService.execute(run_id)
```

ra khỏi HTTP route.

Endpoint hiện tại có thể:
1. create PlanningRun;
2. gọi service synchronous;
3. return như contract hiện tại.

Sau này F2/production có thể chuyển worker queue không rewrite planner.

---

# 14. Error semantics fixes

Sửa technical debt rate-limit unreachable.

Viết explicit decision table:

```text
provider unavailable              -> 503 khi không có business recovery
rate limited                      -> ACTION_REQUIRED
routing budget exhausted          -> ACTION_REQUIRED
station data stale > hard max age -> provider unavailable/recovery
no safe chain with valid data     -> INFEASIBLE
```

Không biến provider outage thành `INFEASIBLE`.

---

# 15. File-level implementation guide

Codex phải inspect repo rồi sửa theo boundary hiện tại.

Dự kiến:

```text
src/packages/core/trips/infrastructure/models.py
src/packages/core/trips/infrastructure/sqlalchemy_repository.py
src/packages/core/trips/infrastructure/station_service.py
src/packages/core/trips/infrastructure/routing.py
src/packages/core/trips/infrastructure/station_graph_repository.py       NEW
src/packages/core/trips/application/station_ingestion_service.py         NEW
src/packages/core/trips/application/station_graph_builder.py             NEW
src/packages/core/trips/application/planning_run_service.py              NEW
src/packages/core/trips/api/dependencies.py
src/packages/agent/planning/runtime.py
src/packages/agent/planning/tools/adaptive_station_planner.py
src/packages/contracts/trips.py
src/apps/api/routes/trips.py
src/apps/web/src/lib/types.ts
src/apps/web/src/lib/api.ts
src/apps/web/src/App.tsx
src/apps/web/src/components/DashboardPanels.tsx
```

Background entrypoints có thể đặt:

```text
src/apps/worker/
```

hoặc theo convention repo hiện tại.

Không tạo framework queue mới nếu repo chưa có.
Có thể bắt đầu bằng CLI/background command idempotent:

```text
python -m ... sync-stations
python -m ... build-station-graph
```

---

# 16. Tests bắt buộc

## 16.1. Numerical golden tests

Trước refactor:
- capture deterministic fixture outputs cho:
  - effective consumption;
  - route energy;
  - SOC points;
  - charging time;
  - target SOC;
  - feasibility;
  - risk score;
  - selected station chain;
  - proposal ordering.

Sau refactor:
- same inputs => same values.

Tolerance:
- dùng tolerance hiện tại;
- không nới tolerance để che regression.

## 16.2. Station ingestion / provider access

Test:
- new generation;
- same generation no-op;
- changed station update;
- station removed -> inactive;
- malformed bulk rejected transactionally;
- failed refresh uses local snapshot within max age;
- stale beyond max age returns provider-unavailable state;
- detail upsert;
- connector normalization;
- warm-up 403 -> không launch detail pool;
- first detail 403 -> provider circuit open;
- 403 là non-retryable trong cùng attempt;
- 429 giữ semantics riêng với cooldown;
- planner request không gọi VinFast detail endpoint;
- local last-known-good còn fresh -> planning không 503 chỉ vì upstream 403;
- unknown station data != INFEASIBLE;
- OpenAI recovery candidate không được promote `VERIFIED`;
- plan dùng OpenAI candidate vẫn `CONDITIONAL`;
- idempotent rerun.

## 16.3. Graph

Test:
- directed edges;
- no all-pairs explosion;
- current version cache hit;
- old road version ignored;
- route provider mismatch ignored;
- write-through on miss;
- origin/destination still call routing provider;
- graph cache does not change planner outcome.

## 16.4. Persistence

Test:
- proposal separate from assumptions;
- all alternatives persisted;
- conditional persisted;
- concurrent plan version allocation;
- legacy proposal read compatibility.

## 16.5. Redis

Test both:
- InMemory backend;
- Redis integration if CI service available.

Failure Redis:
- planner continues using DB/provider path;
- cache outage must not become trip infeasible.

## 16.6. UI

Add:
- component/unit tests if current stack supports;
- provenance-driven Data Trust;
- plan history;
- alternatives survive reload.

## 16.7. Existing suite

Must finish:
- all current F1 behavioral tests pass;
- existing F2 xfail unchanged;
- `npm run typecheck` pass;
- frontend build pass;
- Ruff 0 errors.

---

# 17. Observability

Add structured metrics/logging:

```text
planning_run_duration_ms
routing_requests_total
routing_cache_hits_total
station_catalog_queries_total
station_detail_upstream_requests_total
station_detail_cache_hits_total
station_graph_hits_total
station_graph_misses_total
station_dataset_age_seconds
station_dataset_generation
planner_edge_validations_total
planner_outcome_total{outcome}
```

Log:
- trip_id;
- planning_run_id;
- trace_id;
- provider;
- graph version;
- station dataset generation;
- energy model version;
- policy version.

Không log API key.

---

# 18. Rollout flags

Thêm:

```text
STATION_CATALOG_DB_ENABLED
STATION_GRAPH_ENABLED
REDIS_CACHE_ENABLED
PERSIST_ALL_PROPOSALS_ENABLED
```

Rollout:
1. deploy schema;
2. run station ingestion;
3. shadow-read DB catalog, compare runtime provider results;
4. enable DB catalog;
5. build station graph;
6. shadow graph hit vs live Goong route values;
7. enable graph acceleration;
8. enable Redis;
9. remove process-local-only dependency after soak.

---

# 19. Definition of Done

Variant A hoàn thành khi:

- [ ] `POST /plans` không gọi VinFast warm-up/detail endpoint;
- [ ] VinFast 401/403 mở provider circuit và không gây request storm;
- [ ] planner không còn phải download toàn bộ VinFast locator dataset cho mỗi process lifecycle/request;
- [ ] station catalog persisted trong PostgreSQL/PostGIS;
- [ ] station có `VERIFIED/PARTIAL/UNVERIFIED` semantics;
- [ ] OpenAI web search chỉ là recovery, không phải canonical station source;
- [ ] plan dùng OpenAI web candidate vẫn `CONDITIONAL`;
- [ ] dataset có generation/version/freshness;
- [ ] EVSE/connectors persisted;
- [ ] shared Redis cache optional;
- [ ] sparse station graph persisted;
- [ ] graph is directed/versioned;
- [ ] graph hit thay network call nhưng không thay result;
- [ ] all current formulas unchanged;
- [ ] golden numerical tests pass;
- [ ] adaptive beam search output parity pass trên fixtures;
- [ ] plan proposal tách khỏi assumptions;
- [ ] alternatives + conditional persisted;
- [ ] atomic version allocation;
- [ ] policy snapshot đầy đủ;
- [ ] provenance UI driven by backend data;
- [ ] provider outage không bị diễn giải sai thành infeasible;
- [ ] lint/typecheck/tests green;
- [ ] F2 semantics không bị triển khai nhầm.

---

# 20. Codex execution order

Thực hiện theo commit nhỏ:

1. `test: capture F1 numerical and planner golden behavior`
2. `fix: redact secrets and classify VinFast 401/403/429`
3. `feat: add provider-level circuit breaker and stop 403 request storms`
4. `db: add charging catalog, data-quality and dataset-version schema`
5. `feat: implement station ingestion and local repository`
6. `feat: wire planner to local station catalog with NO runtime VinFast detail calls`
7. `feat: preserve OpenAI recovery as CONDITIONAL-only path`
8. `db: add station_edges and graph repository`
9. `feat: add station route edge read-through cache (Goong only)`
10. `feat: add Redis cache abstraction`
11. `db: normalize plan proposal persistence and planning runs`
12. `fix: atomic versioning and F1 failure semantics`
13. `feat: provenance-driven frontend and persisted alternatives`
14. `chore: observability, flags, lint and docs`

Sau mỗi commit:
- chạy F1 test suite;
- chạy numerical golden tests;
- không tiếp tục nếu parity bị phá.

---

# 21. Non-goals của Variant A

Không làm trong variant này:

- charging curve;
- taper theo SOC;
- queue prediction;
- realtime port availability giả;
- per-segment weather;
- per-segment speed consumption;
- multi-objective label-setting;
- A* SOC state graph;
- minimum-charge optimization thay vì 80%;
- thay đổi risk formula;
- thay đổi energy formula;
- thay đổi current planner search widths.

Các thay đổi trên thuộc Variant B.
