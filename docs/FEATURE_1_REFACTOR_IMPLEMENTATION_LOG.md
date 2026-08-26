# Feature 1 Variant A — Implementation Log

> Mục tiêu: productionize Feature 1 theo `FEATURE_1_REFACTOR_KEEP_FORMULAS.md`, không thay đổi công thức hoặc decision rule của planner.

## Thông tin thực thi

- Bắt đầu: 22/08/2026, timezone Asia/Saigon.
- Branch ban đầu: `feature/find-route`.
- Commit ban đầu: `5246231` (`refactor agent architecture`).
- Spec nguồn: `C:\Users\HUY HOANG\Downloads\FEATURE_1_REFACTOR_KEEP_FORMULAS.md`.
- SHA-256 spec: `C729A4C59CDE580A771AF33A9756FBC9261EF182AD5E344BEB8DF3FD60B7C71F`.
- File có sẵn chưa track được giữ nguyên: `docs/FEATURE_1_TECHNICAL_IMPLEMENTATION.md`.

## Numerical compatibility lock

Các thành phần sau bị đóng băng trong refactor:

- energy/SOC/charging formulas;
- safe range và minimum/maximum stops;
- corridor/detour constants;
- adaptive beam/branch/edge budgets;
- candidate và proposal ranking;
- feasibility/risk rules và raw-vs-rounded SOC semantics.

Mọi thay đổi liên quan chỉ được chấp nhận khi golden tests giữ nguyên output.

## Baseline trước thay đổi

| Lệnh | Kết quả |
|---|---|
| `python -m pytest -q` | Toàn suite vượt timeout 180 giây trong lần chạy đầu; sẽ chạy theo batch để có kết quả đầy đủ |
| `python -m ruff check src tests --no-cache` | Fail 9 lỗi có thể auto-fix: 6 import-order, 3 unused imports |
| `npm run typecheck && npm run build` | Batch đầu bị timeout cùng pytest; sẽ chạy lại độc lập |

## Nhật ký milestone

### M0 — Khảo sát và baseline

- Đã đọc toàn bộ spec và xác nhận không có `AGENTS.md` trong repo.
- Xác nhận stack: FastAPI, SQLAlchemy/Alembic, PostgreSQL/SQLite test, React/Vite.
- Xác nhận chưa có Redis/PostGIS helper dependency; implementation phải giữ SQLite test compatibility.
- Xác nhận planner hiện đọc trực tiếp `VinFastStationDataService` ở production và cache route/station detail trong process.
- Xác nhận `plan_versions` đang nhúng proposal trong `assumptions`.
- Xác nhận công thức hiện tập trung trong `energy_tool.py` và không được sửa.

### M1 — Numerical golden lock

- Thêm golden fixture VF6 Plus cố định cho effective consumption, energy từng leg, SOC points, target SOC, charge duration, feasibility và risk score.
- Mở rộng adaptive-planner test để khóa exact station chain, final SOC và total charge time.
- Không sửa `energy_tool.py`, `feasibility_tool.py` hoặc các hằng số adaptive planner.

### M2 — Provider semantics và circuit breaker

- Chuẩn hóa `StationProviderError` với `code`, HTTP status, retryability và `Retry-After`.
- Phân loại 401/403 thành `PROVIDER_ACCESS_DENIED`, 429 thành `PROVIDER_RATE_LIMITED`, 404 theo entity và 5xx/timeout là transient có retry hữu hạn.
- Warm-up 401/403 dừng detail pool; detail probe đầu tiên 401/403 mở provider-level circuit và dừng các request còn lại.
- Circuit có thể chia sẻ qua `CacheBackend` tại key `provider-circuit:vinfast-detail`; cache lỗi thì breaker process-local vẫn fail-safe.
- Không thêm browser spoofing hoặc anti-bot bypass. Secret mẫu trong `.env.example` đã được thay bằng placeholder.

### M3 — PostgreSQL/PostGIS station catalog và background ingestion

- Thêm migration head `20260822_1200` cho dataset versions, locations/PostGIS geography, EVSE, connectors, external evidence, station edges, planning runs và normalized plan proposal.
- `StationIngestionService` thực hiện generation no-op, checksum, transactional upsert, inactivate missing records và giữ ACTIVE last-known-good khi upstream fail.
- Bulk record đi vào DB với `PARTIAL`; chỉ detail có connector + usable power + timestamp trong freshness window mới thành `VERIFIED`.
- `StationDetailHydrator` chạy background, dùng detail cache key theo provider/external-id/dataset-generation, hạ detail quá tuổi thành `PARTIAL` và dừng ngay khi provider circuit mở.
- CLI idempotent: `sync-stations`, `hydrate-stations`, `build-station-graph`.

### M4 — Planner chỉ đọc local catalog

- Production dependency không còn wire `VinFastStationDataService` vào request path.
- `LocalStationCatalogService` chỉ query DB, giữ nguyên sampled-polyline, Haversine coarse detour, candidate order và logical budgets 24 → 48 → 96.
- Chỉ `VERIFIED` được dùng cho primary charging commitment; `PARTIAL` không được fabricate connector/power.
- Dataset quá hard max age trả station-data unavailable, không bị diễn giải thành `INFEASIBLE`.
- OpenAI web candidate vẫn `UNVERIFIED`, chỉ dùng recovery, được lưu audit evidence nhưng không promote canonical station.

### M5 — Shared cache và station graph

- Thêm `CacheBackend` với InMemory/Redis implementations, TTL, delete và distributed-lock boundary; business logic không import Redis.
- Route cache key canonical `route:v1:{provider}:{origin6}:{destination6}:{ordered_waypoints_hash}`, TTL 300 giây; cache hit giữ nguyên source `retrieved_at`.
- Redis lỗi fail-open về provider/DB path, không trở thành trip infeasible.
- Graph lưu directed exact routing facts theo provider/profile/road version; builder lấy sparse K-nearest bằng PostGIS `ST_DWithin` ở PostgreSQL và deterministic spatial fallback ở SQLite.
- Runtime chỉ dùng graph cho station → station; origin/destination tiếp tục gọi routing provider. Cache miss write-through exact edge.

### M6 — Planning run và persistence

- Tách `PlanningRunService.create/execute` khỏi HTTP route; synchronous contract hiện tại giữ nguyên nhưng execution boundary sẵn sàng chuyển worker.
- Trip lifecycle: `DRAFT → PLANNING → PLANNED` hoặc `PLANNING_FAILED`.
- Proposal lưu ở column riêng; read còn fallback legacy nested proposal trong một release.
- Một planning result lưu đủ tối đa ba ranked alternatives trong cùng transaction; conditional proposal lưu status `CONDITIONAL`.
- Version allocation khóa trip row trên PostgreSQL, dùng `BEGIN IMMEDIATE` trên SQLite và retry unique conflict; không còn `len(existing)+1` ở production repository.
- Sửa branch rate-limit unreachable: 429/budget trả `ACTION_REQUIRED`, provider outage không rơi xuống `INFEASIBLE`.

### M7 — Policy, provenance và frontend

- `AssumptionSnapshot` có stale/deviation thresholds, planner/energy versions, dataset generation, routing provider và road version.
- Default stale threshold vẫn 24 giờ; adaptive planner truyền policy field xuống local materialization nên golden behavior không đổi.
- Plan provenance có category cho route, station dataset/detail, weather, elevation, vehicle, policy, planner và energy model; cache phục vụ thêm `served_at` nhưng không reset source `retrieved_at`.
- Data Trust render trực tiếp `plan.provenance`, tính tuổi/freshness và hiển thị link/version/generation.
- UI gọi `getTripPlans()`, phục hồi latest alternatives từ DB, lưu current trip trong session và có plan-history panel. Persisted conditional plan render read-only; không thêm Confirm/Reject.

### M8 — Observability và quality gates

- Structured planning logs có trip/run/trace, provider, graph version, dataset generation, energy model và policy version; không log API key.
- Thêm registry cho duration, route requests/cache hits, station queries/detail requests/cache hits, graph hits/misses, dataset age/generation, edge validations và planner outcomes.
- Ruff toàn backend/test/migration về 0 lỗi.
- Migration fresh upgrade, downgrade một revision và re-upgrade thành công trên SQLite verification DB.
- Frontend TypeScript typecheck và production build đều pass.

## Lệnh kiểm thử theo milestone

Phần này được cập nhật sau mỗi milestone; mỗi entry phải ghi command, exit code và kết quả tóm tắt.

| Milestone | Lệnh | Exit | Kết quả |
|---|---|---:|---|
| M1 | `python -m pytest -q tests/test_core/test_f1_numerical_golden.py tests/test_core/test_adaptive_station_planner.py` | 0 | 4 passed |
| M2–M4 | provider/catalog/local-planner focused batches | 0 | 26 passed, sau đó 37 passed ở regression batch policy/planner/API |
| M5 | cache/graph/adaptive focused batches | 0 | route cache, Redis fail-open, graph exact parity đều pass |
| M6 | `python -m pytest -q tests/test_core/test_plan_persistence.py tests/test_api/test_planning.py` | 0 | atomic concurrency, alternatives, conditional, lifecycle pass |
| M7 | `npm run typecheck` | 0 | TypeScript 0 lỗi |
| M7 | `npm run build` | 0 | Vite production build thành công |
| M8 | `python -m ruff check src tests migrations/versions/20260822_1200_f1_variant_a_production_schema.py` | 0 | All checks passed |
| M8 | Alembic fresh upgrade → downgrade `20260815_0130` → upgrade head | 0 | schema round-trip pass; 7 bảng mới + normalized proposal columns verified |
| M8 | `python -m pytest -q` | 0 | 119 passed, 5 xfailed F2, 1 warning từ mock OpenAI serializer |

## File thay đổi

Phần này được cập nhật liên tục với mục đích của từng file.

- Schema/domain/repository: migration `20260822_1200`, `models.py`, station catalog/graph domains và SQLAlchemy repositories.
- Ingestion/runtime: `station_ingestion_service.py`, `vinfast_locator_client.py`, `local_station_catalog_service.py`, worker CLI.
- Cache/graph: `cache_backend.py`, `station_graph_builder.py`, `station_graph_repository.py`, adaptive planner graph read/write-through.
- Planning persistence: `planning_run_service.py`, `service.py`, trip repository, contracts và API trace wiring.
- Policy/provenance/UI: assumptions service, planning proposal node, frontend types/App/Data Trust/history styles.
- Tests mới: numerical golden, catalog, runtime wiring, cache, graph, persistence và provider-circuit cases.

## Quyết định và sai khác có chủ ý

Phần này ghi lại mọi quyết định cần diễn giải so với spec, đặc biệt cho SQLite/PostGIS, Redis optional và synchronous planning-run execution.

- PostgreSQL production dùng `GEOGRAPHY(POINT,4326)`, GIST và `ST_DWithin`; SQLite test dùng WKT/text + Haversine fallback để CI deterministic.
- Redis là optional rollout flag. CI hiện dùng InMemory và fake Redis client; không có live Redis service trong repo để chạy integration container.
- Final-plan cache chủ ý không triển khai vì key cần đủ vehicle/policy/station/road/environment versions; route/detail cache đã đủ phạm vi Variant A.
- Endpoint planning vẫn synchronous theo spec, nhưng mọi lần chạy đều được persist qua `PlanningRunService.execute(run_id)`.
- Frontend chưa thêm unit-test framework vì package hiện không có Vitest/Jest; verification dùng TypeScript typecheck + production build và API persistence tests.
- Không triển khai F2 Confirm/Reject/Activate; các xfail F2 giữ nguyên.

## Trạng thái Definition of Done

- [x] `POST /plans` không wire hoặc gọi VinFast warm-up/detail/bulk HTTP.
- [x] VinFast 401/403 mở provider circuit và chặn request storm; 429 có cooldown riêng.
- [x] Station catalog/EVSE/connectors/dataset version persisted trong PostgreSQL/PostGIS schema.
- [x] `VERIFIED/PARTIAL/UNVERIFIED` và hard freshness semantics được áp dụng fail-closed.
- [x] OpenAI chỉ là recovery/evidence; plan dùng web candidate vẫn `CONDITIONAL` và persisted.
- [x] Redis shared cache optional; cache outage fail-open.
- [x] Sparse directed/versioned station graph có exact-provider parity và write-through.
- [x] Công thức, constants và adaptive search widths giữ nguyên; numerical/planner golden pass.
- [x] Proposal tách assumptions; alternatives/conditional persisted; version atomic.
- [x] Planning run và trip lifecycle persisted.
- [x] Policy snapshot/provenance đầy đủ; Data Trust/history/alternatives đọc từ backend data.
- [x] Rate-limit/provider outage semantics không bị biến thành infeasible.
- [x] Ruff, backend suite, frontend typecheck/build và migration round-trip pass.
- [x] Không triển khai nhầm F2 semantics.

## Việc cần làm khi rollout production

1. Chạy Alembic migration trên staging PostgreSQL có PostGIS và xác nhận GIST/partial unique indexes.
2. Chạy `sync-stations`, sau đó `hydrate-stations` bằng nguồn mà đội có quyền truy cập.
3. Kiểm tra dataset generation/freshness và số lượng `VERIFIED` trước khi bật `STATION_CATALOG_DB_ENABLED`.
4. Build graph ở shadow mode, so sánh edge với live Goong rồi mới bật `STATION_GRAPH_ENABLED`.
5. Kết nối Redis staging, quan sát fail-open/circuit sharing rồi mới bật `REDIS_CACHE_ENABLED`.

## M9 — Final hardening audit (tiếp tục ngày 22/08/2026)

Sau khi đối chiếu lại toàn bộ Definition of Done với spec, audit cuối đã bổ sung và xác minh các điểm sau:

- Sửa `planning_runs.result_code`: proposal chứa `STATION_BUSY` hoặc `UNVERIFIED_STATION_DATA` luôn được ghi là `CONDITIONAL`, kể cả khi proposal không đi qua OpenAI recovery mode.
- Sửa spatial fallback trên SQLite: bounding box chỉ dùng để lấy candidate thô; kết quả cuối bắt buộc lọc lại bằng Haversine theo đúng `radius_km`, tránh đưa các điểm nằm ngoài bán kính ở góc bounding box vào sparse graph.
- Sửa provider circuit cooldown: `Retry-After`/cooldown của 429 không còn bị nâng sai lên access-denied cooldown 300 giây; 401/403 và 429 giữ semantics/cooldown độc lập.
- Thêm regression cho `VinFastLocatorClient` background: 403 non-retryable và chặn request lặp; 429 giữ `Retry-After` và chặn call tiếp theo trong cooldown.
- Thêm regression chứng minh ACTIVE last-known-good còn fresh vẫn được planner đọc từ local catalog sau khi lần refresh kế tiếp nhận 403.
- Thêm API regression chứng minh station-data outage trả `ACTION_REQUIRED`/`STATION_DATA`, không bị diễn giải thành `INFEASIBLE`.
- Thêm regression cho exact-radius SQLite và conditional planning-run result.
- Xác minh worker CLI expose đủ ba command `sync-stations`, `hydrate-stations`, `build-station-graph` mà không thực hiện network call trong bước kiểm tra parser.

### Verification cuối

| Lệnh | Exit | Kết quả |
|---|---:|---|
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | 125 passed, 5 xfailed F2 giữ nguyên, 1 warning từ mock OpenAI serializer |
| `.\.venv\Scripts\ruff.exe check src tests migrations\versions\20260822_1200_f1_variant_a_production_schema.py --no-cache` | 0 | All checks passed |
| `npm run typecheck` | 0 | TypeScript 0 lỗi |
| `npm run build` | 0 | Vite production build thành công, 54 modules transformed |
| `git diff --check` | 0 | Không có whitespace error; chỉ có cảnh báo LF/CRLF của Git trên Windows |
| worker CLI parser smoke test | 0 | Hiển thị đủ 3 background commands |

Các bước còn lại trong mục rollout production vẫn là xác minh môi trường ngoài repo: PostgreSQL/PostGIS staging, live Redis và upstream mà đội có quyền truy cập. Chúng không được giả lập hoặc gọi từ test suite local.
