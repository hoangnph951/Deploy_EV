# Prompt cho Codex — Tiếp tục rollout Feature 1 với self-hosted OSRM

## Cách dùng file này

Người tiếp quản:

1. Clone repository và checkout đúng nhánh bàn giao.
2. Mở thư mục repository trong Codex.
3. Gửi yêu cầu sau:

   > Đọc toàn bộ `docs/F1_OSRM_CODEX_CONTINUATION_PROMPT.md` và thực hiện đến
   > khi hoàn tất hoặc gặp blocker thực sự. Cập nhật log/checklist/evidence theo
   > file và không bỏ qua acceptance gate.

Phần còn lại là chỉ dẫn trực tiếp cho Codex.

---

## 1. Nhiệm vụ

Bạn là Codex tiếp quản rollout Feature 1 của dự án P-210. Implementation chính
đã hoàn thành. Hãy tiếp tục phần vận hành còn lại trên máy đủ tài nguyên:

1. Xác minh source, môi trường, database và baseline tests.
2. Preprocess OSRM MLD dataset Việt Nam bằng script có sẵn.
3. Khởi động và smoke-test OSRM local.
4. Build đầy đủ sparse station graph theo chunk cho active station dataset.
5. Xác minh atomic activation và các graph invariant.
6. Thực hiện acceptance Phase I đến Phase Q còn pending.
7. Cập nhật log, checklist, artifacts và kết luận `GO`/`NO-GO`.

Không viết lại phần đã hoàn thành khi chưa có evidence cho thấy code lỗi. Không
đánh dấu pass dựa trên suy đoán. Chỉ tick `[x]` sau khi đã chạy và lưu evidence.

## 2. Quyền hạn và nguyên tắc an toàn

- Được chạy diagnostics, tests, migration upgrade, station sync idempotent, OSRM
  preprocessing, Docker service và graph worker trong repository/database được
  người dùng cung cấp.
- Không xóa database, Docker volume, PBF, OSRM artifacts hoặc backup.
- Không chạy `docker compose down -v`, migration downgrade, `git reset --hard`
  hoặc thao tác phá hủy tương đương.
- Với database đã có dữ liệu, tạo/kiểm tra recovery backup trước migration thay
  đổi schema. Ưu tiên forward-fix; không downgrade khi graph data tồn tại.
- Không commit `.env`, credential, database dump, `data/osrm/`, `*.osm.pbf`,
  `*.osrm*`, `road-version.txt`, Docker volume hoặc file backup.
- Redact database password, API key, query secret và authorization header khỏi
  terminal output, log và artifact.
- Không sửa production deployment, GitHub Secrets hoặc remote environment nếu
  chưa có yêu cầu rõ ràng. Chỉ có thể bật flag local/staging sau khi đủ gate;
  production enablement cần chủ sở hữu xác nhận.
- Với tác vụ dài, gửi cập nhật tiến độ ít nhất mỗi 60 giây hoặc tại mỗi phase.
- Kiên trì resume các bước an toàn. Chỉ dừng khi hoàn tất hoặc có blocker thực sự.

## 3. Đọc nguồn sự thật trước khi thao tác

Đọc đầy đủ theo thứ tự:

1. `docs/F1_OSRM_HANDOFF_GUIDE.md`
2. `docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`
3. `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md`
4. `docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md`
5. `docs/F1_KEEP_FORMULAS_ROLLOUT_LOG.md`
6. `docs/FEATURE_1_REFACTOR_KEEP_FORMULAS.md`
7. `docs/FEATURE_1_REFACTOR_IMPLEMENTATION_LOG.md`
8. `docs/f1_keep_formulas_rollout_inventory.md`
9. `artifacts/F1_KEEP_FORMULAS_ROLLOUT_RESULT.md`
10. `artifacts/f1_station_ingestion_report.md`
11. `artifacts/f1_station_graph_report.md`

Sau đó đọc các source entry point:

- `scripts/prepare_osrm_vietnam.ps1`
- `docker-compose.yml`
- `src/apps/worker/stations.py`
- `src/apps/api/bootstrap/config.py`
- `src/packages/core/trips/application/station_graph_builder.py`
- `src/packages/core/trips/infrastructure/osrm_routing.py`
- `src/packages/core/trips/infrastructure/station_graph_repository.py`
- `src/packages/core/trips/infrastructure/station_catalog_repository.py`
- `migrations/versions/20260822_1700_add_atomic_station_graph_versions.py`

Tài liệu mô tả trạng thái trước đây; luôn kiểm tra lại trạng thái thật của máy và
database hiện tại.

## 4. Baseline bàn giao

Baseline implementation commit: `57e8a70` trên nhánh
`feature/f1-osrm-handoff`. Có thể có commit tài liệu mới hơn; dùng HEAD được người
bàn giao chỉ định và ghi exact commit SHA.

Evidence từ máy trước:

- Alembic head: `20260822_1700`.
- PostGIS 3.3 và location GIST index đã được kiểm tra.
- Database cũ có 23.919 active canonical locations.
- Một legacy graph `FAILED` chứa 40 Goong edge, không runtime-visible.
- Chưa có OSRM graph `ACTIVE`, complete MLD artifacts hoặc `road-version.txt`.
- Full backend: 135 passed, 5 expected xfailed.
- Focused formula/OSRM/graph/runtime: 13 passed.
- `STATION_GRAPH_ENABLED=false`.
- K mặc định 40, invariant `edges <= N × 40`.
- Rollout đang `NO-GO` tại Phase H do máy cũ thiếu tài nguyên.

Không giả định database hiện tại có cùng count hoặc migration state; hãy đo lại.

## 5. Audit repository và lập kế hoạch

```powershell
git status -sb
git rev-parse HEAD
git branch --show-current
git diff --check
```

Nếu working tree đã có thay đổi của người dùng, không overwrite/revert. Phân loại
file có trước và file do bạn tạo. Nếu xung đột với rollout, báo trước khi sửa.

Tạo plan gồm: audit, baseline, DB, OSRM preprocessing, OSRM smoke, graph build,
acceptance I–Q, documentation và final decision. Chỉ một phase `in_progress`.

## 6. Xác minh tài nguyên và cấu hình

Kiểm tra:

- Python 3.11+ và virtual environment.
- Docker daemon/Compose hoạt động.
- Host khuyến nghị từ 12 GB RAM; Docker có ít nhất 6–8 GB khả dụng.
- Disk đủ cho source PBF, filtered PBF và MLD artifacts.
- Internet truy cập được Geofabrik và GHCR.
- `.env` tồn tại nhưng không tracked.
- `DATABASE_URL` trỏ đúng database được phép rollout.
- `STATION_GRAPH_ENABLED=false`.
- `STATION_GRAPH_ROUTING_PROVIDER=osrm`.
- `OSRM_ROAD_VERSION_FILE=data/osrm/road-version.txt`.
- `STATION_GRAPH_MAX_NEIGHBORS=40`, trừ khi chủ sở hữu duyệt K khác.

Không hiển thị secret khi báo cáo cấu hình.

## 7. Baseline tests

Cài dependency nếu cần và chạy focused suite:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_core/test_f1_numerical_golden.py `
  tests/test_core/test_osrm_routing.py `
  tests/test_core/test_station_graph_repository.py `
  tests/test_core/test_station_runtime_wiring.py

.\.venv\Scripts\python.exe -m alembic heads
docker compose config
```

Nếu focused tests fail, chẩn đoán/sửa lỗi trước. Không preprocessing hoặc build
graph trên baseline đang đỏ. Giữ nguyên công thức/search semantics đã khóa; mọi
code fix phải chạy lại numerical golden tests và final hash verification.

## 8. Xác minh database và station dataset

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe scripts\verify_f1_rollout_schema.py
```

### Database đã có dữ liệu

1. Xác minh đúng database được phép rollout.
2. Nếu migration pending, tạo logical recovery backup trước khi upgrade.
3. Chạy `alembic upgrade head`, rồi verify schema.
4. Nếu active station dataset hợp lệ đã có, không bắt buộc ingest lại.
5. Chỉ chạy station sync idempotent khi cần refresh; ghi lại dataset/count đổi hay
   không.

### Database mới hoặc chưa có station dataset

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.apps.worker.stations sync-stations
.\.venv\Scripts\python.exe scripts\verify_f1_rollout_schema.py
```

Không dùng detail hydration làm điều kiện graph build. Detail probe trước trả 403;
local planner/catalog không phụ thuộc hydration.

Ghi evidence: revision, PostGIS version, GIST index, active dataset ID, active
location count, invalid-coordinate count và graph state trước build.

## 9. Preprocess OSRM

Chạy đúng script đã triển khai:

```powershell
& .\scripts\prepare_osrm_vietnam.ps1
```

Script thực hiện download-resume, car-routing filter, `osrm-extract`,
`osrm-partition`, `osrm-customize`, `osrm-routed --trial`, rồi mới ghi
`data/osrm/road-version.txt`.

Yêu cầu:

- Dùng image pin `ghcr.io/project-osrm/osrm-backend:v26.6.5-debian`.
- Không sửa/tự tạo `road-version.txt`.
- Không dùng incomplete artifact để chạy service/build graph.
- Nếu bị dừng, kiểm tra log/tài nguyên rồi chạy lại script để resume phase hợp lệ.
- Không commit PBF/artifacts/road-version.
- Ghi source và filtered checksum, OSM timestamp, image tag/digest, duration và
  resource của từng phase nếu có thể.

Nếu OOM, không giảm correctness filter/profile hoặc quay lại external routing
API. Kiểm tra Docker memory; báo blocker nếu host vẫn không đủ.

## 10. Khởi động và smoke-test OSRM

Sau successful trial và khi có `road-version.txt`:

```powershell
docker compose --profile routing up -d osrm
docker compose --profile routing ps
docker compose --profile routing logs --tail 100 osrm

$result = Invoke-RestMethod `
  "http://127.0.0.1:5000/table/v1/driving/106.7009,10.7769;106.6602,10.7626?sources=0&destinations=1&annotations=distance,duration"
$result | ConvertTo-Json -Depth 5
```

OSRM dùng `longitude,latitude`. Chỉ pass nếu `code=Ok`, distance/duration không
null và service không restart loop.

## 11. Build graph đến khi ACTIVE

Chỉ bắt đầu khi station dataset đã verify, OSRM healthy, `road-version.txt` được
script tạo và `STATION_GRAPH_ENABLED=false`.

```powershell
.\.venv\Scripts\python.exe -m src.apps.worker.stations `
  build-station-graph --origin-limit 250
```

Lưu JSON mỗi chunk, gồm:

- `graph_version_id`
- `status`
- `expected_node_count`
- `processed_node_count`
- `matrix_calls`
- `edges_written`

Chạy tuần tự đến khi:

```text
processed_node_count == expected_node_count
status == ACTIVE
```

Không chạy nhiều worker cho cùng graph version. Builder tự resume `BUILDING`.

Nếu OSRM outage: kiểm tra health/log, không checkpoint chunk lỗi, không biến outage
thành hàng loạt unreachable edge; khôi phục service rồi chạy lại command.

Nếu dataset/lifecycle đổi trong lúc build và activation bị reject, không bypass
validation. Tạo graph build mới gắn với active dataset version mới.

## 12. Graph acceptance gate

Thu thập evidence cho mọi điều kiện:

1. `BUILDING -> ACTIVE` trong một atomic transaction.
2. Runtime không thấy graph khi còn `BUILDING`.
3. Chỉ một OSRM/driving graph active cho cùng identity.
4. `processed_node_count == expected_node_count`.
5. `edge_count <= expected_node_count × K`.
6. Maximum directed out-degree `<= K` (mặc định 40).
7. Không edge nào có source/destination lifecycle inactive.
8. Graph road version trùng exact `road-version.txt`.
9. Legacy `FAILED` graph không runtime-visible.
10. Old road/dataset version không được chọn thay active identity đúng.
11. Representative directed distance/duration spot checks hợp lý.
12. Provider outage fail closed, không ghi synthetic route/edge.

Chạy lại tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_core/test_f1_numerical_golden.py `
  tests/test_core/test_osrm_routing.py `
  tests/test_core/test_station_graph_repository.py `
  tests/test_core/test_station_runtime_wiring.py

.\.venv\Scripts\python.exe -m pytest -q
```

Chạy Ruff và frontend typecheck/build theo command của repository. Phân biệt lỗi
có sẵn với regression, nhưng không bỏ qua mandatory failure.

## 13. Thực hiện Phase I đến Phase Q

Dùng `docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md` làm nguồn sự thật:

- **I — Graph spot checks:** coordinate order, directed semantics, representative
  route, old road-version rejection.
- **J — Planner integration:** short/long trip, local DB/graph, zero runtime
  VinFast detail call, không commit charging từ partial-only data.
- **K — OpenAI recovery:** web evidence `UNVERIFIED`, plan `CONDITIONAL`, không
  bypass deterministic feasibility.
- **L — Failure semantics:** outage khác physical infeasibility, safe graph-miss
  fallback, Redis outage non-fatal, routing outage fail closed.
- **M — Persistence:** proposal tách assumptions, legacy readability,
  alternatives/conditional persistence, atomic version allocation, không thêm F2
  confirm/activate behavior.
- **N — Frontend:** backend facts, provenance-driven trust, conditional UI,
  reload history/alternatives, không lộ server secret.
- **O — Redis:** Redis OFF là mandatory; Redis ON optional/deferred có ghi rõ.
- **P — Performance:** latency/call counts, zero VinFast detail trong
  `POST /plans`, tạo performance artifact.
- **Q — Deployment readiness:** deployment order, rollback/forward-fix, scheduled
  sync/graph rebuild và final formula/search hash.

Không đánh dấu phase pass nếu còn mandatory checkbox thiếu evidence.

## 14. Invariant không được thay đổi

1. Builder chỉ lấy `charging_locations.active=true`, coordinate hợp lệ, đúng
   active dataset.
2. Topology không phụ thuộc runtime `ACTIVE`/`BUSY`.
3. Planner kiểm tra eligibility riêng trước charging action.
4. `BUSY` không phải unreachable; giữ risk/priority semantics.
5. `INACTIVE`, `MAINTAINING`, `OUTOFORDER`, `BLOCKED` không làm charging stop.
6. Lifecycle inactive node/edge không vào trip subgraph.
7. `ACTIVE -> BUSY` không invalid edge; invalidation theo road version hoặc
   location lifecycle/dataset version.
8. Directed sparse graph giữ `edges <= N × K`, không trở thành N².
9. Provider outage fail closed, không bị hiểu là physical infeasibility.
10. Runtime không đọc graph `BUILDING`, `FAILED` hoặc `SUPERSEDED`.

Nếu code vi phạm, sửa tối thiểu, thêm regression test, chạy full relevant suite và
ghi thay đổi vào log.

## 15. Feature flag và GO/NO-GO

Giữ `STATION_GRAPH_ENABLED=false` trong preprocessing/build.

Chỉ bật local/staging để final acceptance khi:

1. Complete MLD artifacts và trial pass.
2. Table API smoke pass.
3. Graph atomically `ACTIVE`.
4. Mọi graph invariant pass.
5. Mandatory Phase I–Q pass.
6. Rollback/forward-fix đã verify.

Không đổi `.env.example` thành `true`. Không bật production nếu chưa được chủ sở
hữu phê duyệt.

Nếu mandatory gate fail: kết luận `NO-GO`, giữ flag `false`, ghi blocker/evidence.
Không sửa DB bằng tay hoặc bypass validation để tạo kết quả `GO` giả.

## 16. Log, checklist và artifacts

- Chỉ tick `[x]` sau evidence.
- Giữ lịch sử cũ; append section có timestamp cho lần chạy mới.
- Ghi command, exit code, duration, output summary; redact secret.
- Với failure, ghi attempt, root cause, remediation và trạng thái cuối.

Cập nhật:

- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_CHECKLIST.md`
- `docs/F1_OSRM_GRAPH_IMPLEMENTATION_LOG.md`
- `docs/F1_KEEP_FORMULAS_ROLLOUT_CHECKLIST.md`
- `docs/F1_KEEP_FORMULAS_ROLLOUT_LOG.md`
- `artifacts/F1_KEEP_FORMULAS_ROLLOUT_RESULT.md`
- `artifacts/f1_keep_formulas_performance_report.md` khi xong Phase P

Final evidence gồm:

- Exact Git SHA và host/Docker resources/versions.
- DB revision/PostGIS/dataset statistics.
- PBF checksums, OSRM image tag/digest, road version và phase durations.
- Smoke summary đã redact.
- Graph ID/status/node/edge/max-degree/inactive-endpoint statistics.
- Test/lint/frontend/planner acceptance results.
- Performance/call counts và file code sửa thêm (nếu có).
- Quyết định `GO`/`NO-GO` cùng lý do.

## 17. Báo cáo cuối

Trả lời người dùng theo cấu trúc:

1. **Kết quả:** `GO`, `NO-GO` hoặc blocker thực sự.
2. **OSRM:** preprocessing/trial/service/smoke và road version.
3. **Graph:** version, node/edge, max degree, inactive endpoints, activation.
4. **Acceptance:** Phase I–Q pass/fail/deferred kèm lý do.
5. **Feature flag:** false, staging true, hoặc đủ điều kiện đề xuất production.
6. **Tests:** focused/full/lint/frontend.
7. **Files cập nhật:** logs/checklists/artifacts và code fix.
8. **Còn lại:** chỉ liệt kê việc thật sự chưa hoàn thành.

Không tuyên bố hoàn tất nếu graph chưa `ACTIVE`, mandatory acceptance chưa pass
hoặc evidence chưa được lưu.
