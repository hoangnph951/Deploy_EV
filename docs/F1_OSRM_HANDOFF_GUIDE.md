# Feature 1 — Hướng dẫn tiếp quản rollout OSRM station graph

Ngày bàn giao: 2026-08-22 (Asia/Saigon)

## 1. Mục tiêu của tài liệu

Tài liệu này dành cho người tiếp quản phần rollout còn lại của Feature 1 trên một
máy có cấu hình mạnh hơn. Phần code, schema, migration, OSRM adapter, graph
builder và automated tests đã được triển khai. Công việc còn lại chủ yếu là:

1. Chuẩn bị dữ liệu routing OSRM cho Việt Nam.
2. Khởi động và smoke-test OSRM local.
3. Build đầy đủ sparse station graph vào PostgreSQL/PostGIS.
4. Chạy acceptance test còn lại từ Phase I đến Phase Q.
5. Chỉ bật feature flag sau khi tất cả gate bắt buộc đã pass.

Không viết lại implementation và không chạy lại toàn bộ kế hoạch từ đầu. Hãy giữ
nguyên những mục đã đánh dấu `[x]` trong checklist và tiếp tục các mục `[ ]`.

Nếu dùng Codex để chạy phần còn lại, hãy đưa Codex file
`docs/F1_OSRM_CODEX_CONTINUATION_PROMPT.md` và yêu cầu thực hiện đầy đủ theo file.

## 2. Trạng thái tại thời điểm bàn giao

- Alembic head đã được áp dụng trên database dùng khi rollout:
  `20260822_1700`.
- PostGIS 3.3 và GIST index đã được kiểm tra.
- Database dùng khi rollout có 23.919 charging location active hợp lệ.
- Một graph version legacy đang ở trạng thái `FAILED`, chứa 40 edge Goong từ lần
  probe cũ; graph này không visible với runtime.
- Chưa có OSRM graph version `ACTIVE`.
- Chưa tạo đủ OSRM MLD artifacts và chưa có `data/osrm/road-version.txt`.
- `STATION_GRAPH_ENABLED=false` và phải tiếp tục giữ nguyên cho đến cuối rollout.
- Full backend suite gần nhất: 135 passed, 5 expected xfailed.
- Focused formula/OSRM/graph/runtime suite gần nhất: 13 passed.
- Quyết định hiện tại: **NO-GO cho production enablement**.

Các số liệu 23.919 station và trạng thái database nêu trên chỉ đúng với database
đã dùng trong lần rollout trước. Nếu người tiếp quản dùng database mới thì phải
chạy migration và station ingestion trước khi build graph.

## 3. Tài liệu nên đọc để hiểu bối cảnh và tiến độ

Đọc theo thứ tự sau:

| Ưu tiên | Tài liệu | Mục đích |
|---:|---|---|
| 1 | `docs/F1_OSRM_HANDOFF_GUIDE.md` | Điểm bắt đầu và thứ tự thao tác dành cho người tiếp quản |
| 2 | `docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md` | Nguồn sự thật cho phần OSRM đã xong và các gate còn pending |
| 3 | `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md` | Kiến trúc, migration evidence, các lần preprocessing thất bại và nguyên nhân thiếu RAM |
| 4 | `docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md` | Checklist rollout tổng thể; Phase I đến Phase Q vẫn cần thực hiện |
| 5 | `docs/F1_KEEP_FORMULAS_ROLLOUT_LOG.md` | Evidence chi tiết của Phase A đến Phase H |
| 6 | `docs/FEATURE_1_REFACTOR_KEEP_FORMULAS.md` | Cách Feature 1 lấy dữ liệu trạm, lập graph và tính toán kế hoạch |
| 7 | `docs/FEATURE_1_REFACTOR_IMPLEMENTATION_LOG.md` | Lịch sử refactor và các test đã chạy |
| 8 | `docs/f1_keep_formulas_rollout_inventory.md` | Inventory code, schema, flag, worker và dependency liên quan |
| 9 | `artifacts/F1_KEEP_FORMULAS_ROLLOUT_RESULT.md` | Kết luận rollout hiện tại và quyết định NO-GO |
| 10 | `artifacts/f1_station_ingestion_report.md` | Evidence station ingestion 23.919 location |
| 11 | `artifacts/f1_station_graph_report.md` | Evidence graph probe cũ và quota blocker của external provider |

Các source file quan trọng khi cần đọc code:

| Thành phần | File |
|---|---|
| Worker CLI | `src/apps/worker/stations.py` |
| Graph builder | `src/packages/core/trips/application/station_graph_builder.py` |
| Atomic graph repository | `src/packages/core/trips/infrastructure/station_graph_repository.py` |
| Candidate query PostGIS/SQLite | `src/packages/core/trips/infrastructure/station_catalog_repository.py` |
| OSRM Table/Route adapter | `src/packages/core/trips/infrastructure/osrm_routing.py` |
| Graph domain | `src/packages/core/trips/domain/station_graph.py` |
| ORM models | `src/packages/core/trips/infrastructure/models.py` |
| Runtime wiring/feature flag | `src/packages/core/trips/api/dependencies.py` |
| Settings và road-version resolution | `src/apps/api/bootstrap/config.py` |
| Atomic schema migration | `migrations/versions/20260822_1700_add_atomic_station_graph_versions.py` |
| OSRM bootstrap | `scripts/prepare_osrm_vietnam.ps1` |
| Osmium image | `docker/osmium/Dockerfile` |
| OSRM service | `docker-compose.yml` |

## 4. Điều kiện máy tiếp quản

- Windows PowerShell, Docker Desktop và Docker Compose.
- Python 3.11 trở lên.
- Khuyến nghị máy có ít nhất 12 GB RAM vật lý và cấp 6–8 GB RAM trở lên cho
  Docker. Càng nhiều RAM càng tốt cho `osrm-extract`.
- Đủ dung lượng trống cho PBF nguồn, PBF đã filter và toàn bộ OSRM MLD artifacts.
- Có Internet để tải PBF từ Geofabrik và pull/build Docker images.
- Có kết nối đến PostgreSQL/PostGIS chứa station dataset, hoặc có quyền tạo một
  database mới và chạy station ingestion.

Không dùng GitHub để truyền `.env`, database backup, PBF hoặc OSRM artifacts.
Credential phải được gửi qua kênh riêng hoặc secret manager.

## 5. Chuẩn bị repository và môi trường

Clone đúng nhánh bàn giao rồi tạo virtual environment:

```powershell
git clone <repository-url>
cd P-210
git switch <handoff-branch>

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Thay `<handoff-branch>` bằng tên nhánh thực tế mà người bàn giao đã push, ví dụ
`feature/f1-osrm-handoff`.

Điền credential thật vào `.env`, tối thiểu kiểm tra các biến sau:

```dotenv
DATABASE_URL=<postgresql-postgis-connection-string>
STATION_GRAPH_ENABLED=false
STATION_GRAPH_ROUTING_PROVIDER=osrm
STATION_GRAPH_MAX_NEIGHBORS=40
STATION_GRAPH_BUILD_ORIGIN_LIMIT=250
OSRM_BASE_URL=http://127.0.0.1:5000
OSRM_PROFILE=driving
OSRM_ROAD_VERSION_FILE=data/osrm/road-version.txt
REDIS_CACHE_ENABLED=false
```

Không commit `.env`. `STATION_GRAPH_ENABLED` phải vẫn là `false` ở bước này.

Chạy kiểm tra source trước khi rollout:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_core/test_f1_numerical_golden.py `
  tests/test_core/test_osrm_routing.py `
  tests/test_core/test_station_graph_repository.py `
  tests/test_core/test_station_runtime_wiring.py

.\.venv\Scripts\python.exe -m alembic heads
docker compose config
```

Nếu focused tests không pass thì dừng rollout và sửa lỗi môi trường/code trước.

## 6. Chuẩn bị database và station dataset

### Trường hợp A — dùng chung database đã rollout

Chạy:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe scripts\verify_f1_rollout_schema.py
```

Revision mong đợi là `20260822_1700 (head)`. Xác nhận station dataset active vẫn
có dữ liệu và không có migration mới chưa áp dụng.

### Trường hợp B — dùng database mới

Chạy migration và station sync:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.apps.worker.stations sync-stations
.\.venv\Scripts\python.exe scripts\verify_f1_rollout_schema.py
```

Không giả định database mới cũng có đúng 23.919 station; `expected_node_count` sẽ
được chốt từ active station dataset thực tế khi graph version được tạo.

Không chạy detail hydration như một điều kiện của graph build. Detail endpoint đã
từng trả 403 và local station catalog không phụ thuộc vào hydration.

## 7. Preprocess dữ liệu OSRM

Đảm bảo Docker Desktop đang chạy, sau đó thực hiện:

```powershell
& .\scripts\prepare_osrm_vietnam.ps1
```

Script sẽ:

1. Tải có resume `vietnam-latest.osm.pbf` từ Geofabrik.
2. Build local osmium image và tạo car-routing-only PBF.
3. Chạy `osrm-extract`.
4. Chạy `osrm-partition`.
5. Chạy `osrm-customize`.
6. Chạy `osrm-routed --trial`.
7. Chỉ sau khi trial pass mới ghi `data/osrm/road-version.txt`.

Không được tự tạo hoặc sửa `road-version.txt`. Road version phải gắn với checksum
của exact filtered PBF. Script có phase-resume; nếu bị dừng, chạy lại chính lệnh
trên để nó kiểm tra artifact hiện có và tiếp tục.

Không build station graph nếu `road-version.txt` chưa tồn tại hoặc trial chưa
pass, kể cả khi code có fallback configuration value.

## 8. Khởi động và smoke-test OSRM

```powershell
docker compose --profile routing up -d osrm
docker compose --profile routing ps
docker compose --profile routing logs --tail 100 osrm
```

Smoke-test Table API bằng hai tọa độ Việt Nam. OSRM dùng thứ tự
`longitude,latitude`:

```powershell
$result = Invoke-RestMethod `
  "http://127.0.0.1:5000/table/v1/driving/106.7009,10.7769;106.6602,10.7626?sources=0&destinations=1&annotations=distance,duration"
$result | ConvertTo-Json -Depth 5
```

Gate pass khi:

- `code` là `Ok`.
- `distances[0][0]` và `durations[0][0]` không null.
- Service ổn định, không restart loop hoặc báo thiếu MLD artifact.

## 9. Build station graph theo chunk

Chạy một chunk:

```powershell
.\.venv\Scripts\python.exe -m src.apps.worker.stations `
  build-station-graph --origin-limit 250
```

Đọc JSON output và ghi lại:

- `graph_version_id`
- `status`
- `expected_node_count`
- `processed_node_count`
- `matrix_calls`
- `edges_written`

Lặp lại cùng lệnh cho đến khi:

```text
processed_node_count == expected_node_count
status == ACTIVE
```

Builder sẽ tự resume graph version `BUILDING` phù hợp. Không chạy nhiều worker
song song cho cùng graph version trừ khi đã thiết kế và kiểm thử lại concurrency
ở cấp orchestration. Repository có optimistic checkpoint để reject stale worker,
nhưng một worker tuần tự vẫn là cách rollout an toàn nhất.

Nếu OSRM outage hoặc command fail giữa chunk:

1. Không đánh dấu station là unreachable hàng loạt.
2. Kiểm tra OSRM health/log.
3. Khởi động lại OSRM nếu cần.
4. Chạy lại cùng worker command; chunk chưa checkpoint sẽ được thực hiện lại.

Nếu active station dataset thay đổi trong lúc build, activation phải bị từ chối.
Không ép graph cũ thành `ACTIVE`; tạo một build mới gắn với dataset version mới.

## 10. Acceptance gate sau khi graph ACTIVE

Phải kiểm tra tối thiểu:

- Chỉ có một OSRM/driving graph version `ACTIVE` cho cùng identity.
- `processed_node_count == expected_node_count`.
- `edges <= expected_node_count × 40`.
- Maximum outgoing degree không vượt quá 40.
- Không có edge có source hoặc destination `charging_locations.active=false`.
- Runtime chỉ đọc graph version `ACTIVE`.
- Legacy graph `FAILED` không visible với runtime.
- Road version của graph trùng nội dung `data/osrm/road-version.txt`.
- Representative directed road-distance và duration spot checks hợp lý.
- Thay đổi runtime status `ACTIVE -> BUSY` không invalid graph edge.
- Hard-unavailable station không được tạo charging action.

Sau đó chạy lại automated tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tiếp tục thực hiện toàn bộ mục chưa đánh dấu trong Phase I đến Phase Q tại
`docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md`, bao gồm:

- Graph spot checks.
- Planner integration.
- OpenAI recovery semantics.
- Failure semantics.
- Persistence và multiple alternatives.
- Frontend acceptance.
- Redis OFF/ON decision.
- Performance/call metrics.
- Deployment readiness và rollback.

## 11. Điều kiện bật feature flag

Chỉ cân nhắc:

```dotenv
STATION_GRAPH_ENABLED=true
```

khi tất cả điều kiện sau cùng pass:

1. OSRM preprocessing và trial hoàn thành.
2. OSRM Table API smoke test pass.
3. Graph version đã chuyển `BUILDING -> ACTIVE` atomically.
4. K-bound, inactive endpoint và road-version checks pass.
5. Phase I đến Phase Q không còn mandatory gate fail.
6. Rollback/forward-fix procedure đã được xác nhận trên môi trường staging.

Không đổi default trong `.env.example` sang `true`. Feature flag production phải
được quản lý bằng deployment environment/secret configuration.

## 12. Invariant không được phá vỡ

1. Graph builder chỉ lấy `charging_locations.active=true`, coordinate hợp lệ và
   thuộc đúng active station dataset version.
2. Topology không phụ thuộc runtime status `ACTIVE`/`BUSY`.
3. Planner kiểm tra station eligibility riêng trước khi tạo charging action.
4. `BUSY` không đồng nghĩa unreachable; giữ nguyên risk/priority semantics.
5. `INACTIVE`, `MAINTAINING`, `OUTOFORDER`, `BLOCKED` không được dùng làm
   charging stop.
6. Lifecycle inactive node/edge không được đưa vào trip subgraph.
7. Edge không invalid chỉ vì `ACTIVE -> BUSY`; invalidation dựa vào road version
   hoặc station location lifecycle/dataset version.
8. Directed sparse graph luôn giữ `edges <= N × K`, với K mặc định bằng 40.
9. Provider outage phải fail closed, không được biến thành kết luận physical
   infeasibility hay ghi hàng loạt null edge.
10. Runtime không được đọc graph `BUILDING`, `FAILED` hoặc `SUPERSEDED`.

## 13. Những thứ không đưa lên GitHub

- `.env` và mọi API/database credential.
- `data/osrm/`.
- `*.osm.pbf`, `*.osrm*` và `road-version.txt`.
- `data/rollout_backups/` và database dump.
- Docker volume/image, `.venv`, `node_modules`, cache hoặc log chứa secret.

Nếu cần chia sẻ OSRM artifacts thay vì build lại, dùng object storage nội bộ có
checksum và access control; không commit binary lớn vào repository.

## 14. Kết quả người tiếp quản cần ghi lại

Sau mỗi gate, cập nhật:

- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`
- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md`
- `docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md`
- `docs/F1_KEEP_FORMULAS_ROLLOUT_LOG.md`
- `artifacts/F1_KEEP_FORMULAS_ROLLOUT_RESULT.md`

Evidence tối thiểu cần lưu:

- Host/Docker RAM và phiên bản Docker.
- PBF checksum, OSRM image tag/digest và road version.
- Thời gian extract/partition/customize.
- OSRM smoke response đã loại bỏ thông tin nhạy cảm.
- Graph version ID, node/edge counts, max degree và inactive endpoint count.
- Test results, route spot checks và performance metrics.
- Quyết định cuối cùng `GO` hoặc `NO-GO`, kèm lý do cụ thể.

Nếu một mandatory gate fail, giữ `STATION_GRAPH_ENABLED=false`, ghi evidence và
dừng enablement. Không chỉnh dữ liệu hoặc bypass validation chỉ để chuyển graph
sang `ACTIVE`.
