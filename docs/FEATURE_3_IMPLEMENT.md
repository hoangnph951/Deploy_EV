# FEATURE 3 IMPLEMENT

**Phiên bản:** 1.0  
**Ngày:** 22/08/2026  
**Trạng thái:** Source of truth cho triển khai  
**Phạm vi:** Telemetry, monitoring và mô phỏng chuyến đi đang diễn ra

**Tài liệu liên quan:** [FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md](FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md), [agent_architecture.md](agent_architecture.md)

## 1. Mục tiêu

Feature 3 biến các plan F1 đã tạo thành chuyến đi mô phỏng có telemetry theo thời gian:

```text
F1 PlanProposal đã thành công và được confirm
  -> đóng băng SimulationCase snapshot
  -> Simulator phát GPS/SOC/station status theo tick
  -> TelemetryService ingest như dữ liệu runtime thật
  -> MonitoringService đánh giá deterministic
  -> NORMAL hoặc MonitoringEvent
  -> F4 xử lý event cần quyết định
```

F3 chịu trách nhiệm tạo **facts và events**, không lập plan và không gọi LLM.

### Kết quả bắt buộc

- Có catalog mục tiêu 90 simulation case từ 5 tuyến × 3 SOC × 6 profile.
- Người dùng chọn case trên frontend, chạy/pause/resume/reset và theo dõi xe trên bản đồ.
- Telemetry đi qua cùng ingestion/monitoring pipeline như nguồn runtime; simulator không ghi DB hoặc gọi F4 trực tiếp.
- Các threshold được tính bằng code thuần và lấy từ policy snapshot.
- `NORMAL` không gọi Agent/Routing/Station/LLM.
- Mọi dữ liệu mô phỏng có provenance `SIMULATED`.

## 2. Phạm vi và quan hệ với F1/F2/F4

| Feature | F3 dùng lại | Ranh giới |
|---|---|---|
| F1 | `PlanProposal`, route polyline, `soc_points`, charging stops, vehicle/policy snapshot | Chỉ nhận plan đã chứng minh khả thi; không chạy lại planner trong simulator |
| F2 | Plan version, trạng thái `CONFIRMED`, ownership | Chỉ proposal đã confirm mới được làm simulation fixture |
| F4 | Không dùng trực tiếp | F3 phát `MonitoringEvent`; F4 tự quyết định phản ứng |

Không mô tả simulator là GPS/OBD thật. “Mô phỏng như đi thật” nghĩa là xe di chuyển theo timeline, có GPS/SOC/event và đi qua đúng runtime service; nguồn vẫn phải hiện rõ là `SIMULATED`.

## 3. Catalog 90 simulation case

### 3.1. Năm tuyến gốc

| Route ID | Origin | Destination |
|---|---|---|
| `HUST_HUU_NGHI` | Đại học Bách khoa Hà Nội | phường Hữu Nghị, Hòa Bình, Phú Thọ |
| `VINUNI_HCM` | Đại học VinUni | thành phố Hồ Chí Minh |
| `AN_KHANH_TIME_CITY` | An Khánh | Time City |
| `LUNG_CU_CA_MAU` | Lũng Cú, Hà Giang | Cà Mau |
| `MOET_NGHE_AN` | Bộ Giáo dục và Đào tạo, Hà Nội | Nghệ An |

Mỗi tuyến có ba mức SOC đầu vào:

```text
17% | 42% | 60%
```

Tạo 15 base case:

```text
case_id = {route_id}_SOC{soc_percent}
```

Ví dụ: `HUST_HUU_NGHI_SOC17`.

Toàn bộ 15 base case phải được lấy trực tiếp từ 15 bộ log F1 tương ứng trong thư mục `log_F1/`. Với mỗi log F1 đã tạo plan thành công, hệ thống trích xuất và đóng băng dữ liệu cần thiết để sinh đúng 6 biến thể simulator theo các profile đã chốt. Quan hệ bắt buộc là:

```text
1 F1 log hợp lệ -> 1 base case -> 6 simulation cases
15 F1 logs       -> 15 base cases -> 90 simulation cases
```

Không tự dựng base case ngoài dữ liệu trong `log_F1/` và không gộp dữ liệu từ nhiều log thành một case.

### 3.2. Sáu profile

Người dùng liệt kê năm profile. Để khớp tổng 90, tài liệu chốt profile thứ 6 là `NO_FEASIBLE_ALTERNATIVE`, đã tồn tại ở dạng optional trong fixture hiện tại.

Khi implement, chuyển profile này từ `optional_outcome_profiles` vào catalog mặc định của fixture; không giữ cấu hình 5 default profile nếu sản phẩm công bố 90 case.

| Profile | Mục đích | F4 được gọi? |
|---|---|---:|
| `NORMAL` | Baseline không có bất thường | Không |
| `ROUTE_DEVIATION` | Kiểm tra lệch route | Có |
| `SOC_UNDERPERFORMANCE` | Kiểm tra SOC hụt so với plan | Có |
| `STATION_UNAVAILABLE` | Trạm trong plan mất khả dụng | Có |
| `STALE_TELEMETRY` | Telemetry quá cũ | Không replan; chỉ yêu cầu dữ liệu mới |
| `NO_FEASIBLE_ALTERNATIVE` | Negative path: F4 không tìm được plan thay thế an toàn | Có |

```text
5 routes × 3 SOC × 6 profiles = 90 target cases
```

### 3.3. Fixture validity gate

Một case chỉ có trạng thái `READY` khi:

- F1 đã tạo `PlanProposal` thành công và `risk_assessment.is_feasible=true`;
- F2 đã confirm đúng plan version;
- snapshot có polyline, SOC timeline, vehicle profile và policy version;
- `STATION_UNAVAILABLE` có ít nhất một charging stop thật trong proposal;
- `NO_FEASIBLE_ALTERNATIVE` có dữ liệu đủ để chứng minh negative outcome;
- toàn bộ station target tồn tại trong snapshot, không được simulator tự bịa.

Nếu một plan ngắn không có charging stop, profile `STATION_UNAVAILABLE` của base case đó là `NOT_APPLICABLE`, không được phát event giả. Muốn giữ đủ 90 case, đội dữ liệu phải chuẩn bị một F1 proposal hợp lệ có charging stop hoặc thay base fixture bằng proposal khác. UI chỉ cho chạy case `READY`.

Catalog phải hiển thị:

```text
TARGET=90
READY=<số case qua validation>
NOT_APPLICABLE=<số case thiếu prerequisite>
INVALID=<fixture hỏng>
```

## 4. Quy tắc từng profile

### 4.1. `NORMAL`

- GPS bám polyline.
- SOC thực tế gần SOC nội suy từ `soc_points`; noise deterministic khuyến nghị trong `±1%`.
- Telemetry cập nhật đều.
- Không có station disruption.

Kết quả:

```text
monitoring_events = []
agent_invoked = false
replan_created = false
```

### 4.2. `ROUTE_DEVIATION`

Rule:

```text
distance_to_route_km > 2.0 -> ROUTE_DEVIATION
```

| Offset | Kết quả |
|---:|---|
| `1.99 km` | Không event |
| `2.00 km` | Không event |
| `2.01 km` | Tạo event |

Event phải tham chiếu telemetry tick gây vi phạm, confirmed plan version, threshold và actual distance. F4 nhận GPS/SOC tại tick đó để route lại từ vị trí hiện tại.

### 4.3. `SOC_UNDERPERFORMANCE`

SOC kỳ vọng được nội suy theo progress trên confirmed plan:

```text
soc_gap = expected_soc_percent - actual_soc_percent
soc_gap > 5.0 -> SOC_UNDERPERFORMANCE
```

| SOC hụt | Kết quả |
|---:|---|
| `4.9%` | Không event |
| `5.0%` | Không event |
| `5.1%` | Tạo event |

F4 bắt buộc dùng actual SOC tại tick; không dùng lại SOC lúc tạo trip.

### 4.4. `STATION_UNAVAILABLE`

- Target mặc định: charging stop kế tiếp chưa đi qua.
- Phát đúng một station status event tại tick cấu hình.
- Event chứa `station_id`, base plan version, `scenario_id`, tick và provenance `SIMULATED`.
- F4 phải đưa station vào `excluded_station_ids`.

Không chọn station đã hoàn thành và không phát lại event ở mọi tick.

### 4.5. `STALE_TELEMETRY`

```text
server_now - telemetry.recorded_at > 60 seconds
    -> STALE_TELEMETRY
```

| Tuổi telemetry | Kết quả |
|---:|---|
| `60s` | Chưa stale |
| `61s` | Stale |

Kết quả:

- hiển thị field bị stale và sample cuối;
- không tự động gọi planner/routing/station/energy;
- F4 chỉ tạo `REQUEST_NEW_TELEMETRY`;
- khi sample mới đến, monitoring đánh giá lại từ đầu.

### 4.6. `NO_FEASIBLE_ALTERNATIVE`

Đây là profile negative outcome, không phải event type mới. Simulator tạo constraint có căn cứ, ví dụ SOC actual hụt trên 5% và charging stop kế tiếp cùng các alternative hợp lệ bị đánh dấu unavailable.

F3 phát các event canonical tương ứng. F4 hợp nhất constraint và chỉ trả `NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE` khi F1 tools đã chứng minh không có candidate đạt reserve. Provider lỗi hoặc hết search budget không được coi là infeasible.

## 5. Simulator runtime

### 5.1. Snapshot đầu vào

`SimulationCaseSnapshot` phải đóng băng:

```text
case_id, fixture_version
trip_id, plan_id, plan_version
origin, destination, initial_soc_percent
route geometry + segments
soc_points, charging stops
vehicle profile/version
assumption/policy snapshot
station snapshots
scenario profile + seed
```

Thay đổi dữ liệu live bên ngoài không được làm replay cũ đổi kết quả.

### 5.2. Generator deterministic

```python
TelemetrySimulator(
    case_snapshot,
    profile,
    seed,
    tick_interval_seconds,
    speed_multiplier,
) -> sequence[SimulationEmission]
```

Invariant:

- cùng snapshot + profile + seed tạo cùng sequence;
- progress và SOC ground truth không đổi khi đổi tốc độ phát;
- marker không đi lùi ngoài profile cố ý;
- SOC không tăng ngoài charging stop;
- charging stop có arrival/departure và SOC jump phù hợp plan;
- station disruption phát đúng một lần;
- timestamps dùng injected clock, không gọi wall clock trực tiếp trong domain test.

### 5.3. Luồng phát dữ liệu

```text
SimulationRunner
  -> TelemetryService.ingest(sample)
  -> MonitoringService.evaluate(...)
  -> persist telemetry + event
  -> publish latest simulation state
```

Station status emission đi qua trusted station-event adapter rồi mới vào MonitoringService. Simulator không ghi thẳng `monitoring_events`, không tự tạo `PlanningRun` và không gọi Agent.

## 6. Kiến trúc code

```text
src/apps/api/routes/
├── telemetry.py
├── monitoring.py
└── simulation.py

src/packages/contracts/
├── monitoring.py              # API request/response
└── simulator.py

src/packages/core/monitoring/
├── api/dependencies.py
├── domain/
│   ├── telemetry.py           # TelemetrySample, freshness
│   ├── events.py              # MonitoringEvent + enums
│   ├── geometry.py            # projection/progress
│   ├── soc.py                 # expected SOC interpolation
│   └── policies.py            # pure threshold rules
├── application/
│   ├── ports.py
│   ├── telemetry_service.py
│   └── monitoring_service.py
└── infrastructure/
    ├── models.py
    └── repositories.py

src/packages/core/simulator/
├── api/dependencies.py
├── domain/
│   ├── cases.py
│   ├── profiles.py
│   └── generator.py
├── application/
│   ├── catalog_service.py
│   └── simulator_service.py
└── infrastructure/
    ├── fixtures/
    └── run_repository.py
```

Contracts chỉ chứa request/response. `TelemetrySample`, `MonitoringEvent`, threshold rule và simulator generator thuộc domain.

## 7. Policy

Mở rộng policy versioned:

```python
class PolicyConfig:
    reserve_soc_percent: float
    stale_station_hours_threshold: float
    route_deviation_km_threshold: float
    soc_underperformance_threshold_percent: float
    telemetry_stale_after_seconds: int
    monitoring_event_cooldown_seconds: int
```

Giá trị pilot lần lượt là `15%`, `24h`, `2km`, `5%`, `60s` và cooldown cần freeze trước implementation. Threshold dùng cho run phải nằm trong snapshot của case; không hard-code ở frontend, prompt hoặc generator.

## 8. Persistence

### Telemetry contract tối thiểu

```json
{
  "event_id": "telemetry-0001",
  "location": {
    "lat": 20.95,
    "lng": 105.95,
    "source_type": "SIMULATED",
    "updated_at": "2026-08-22T10:00:00Z"
  },
  "soc": {
    "value_percent": 42.0,
    "source_type": "SIMULATED",
    "scenario_id": "HUST_HUU_NGHI_SOC42_ROUTE_DEVIATION",
    "simulation_run_id": "sim-run-1",
    "tick": 10,
    "updated_at": "2026-08-22T10:00:00Z"
  },
  "speed_kph": 52.0,
  "odometer_km": 84.3,
  "client_timestamp": "2026-08-22T10:00:00Z"
}
```

Response ví dụ cho `NORMAL`:

```json
{
  "accepted": true,
  "duplicate": false,
  "monitoring_events": [],
  "agent_invoked": false,
  "last_updated_at": "2026-08-22T10:00:01Z"
}
```

Validate lat/lng, SOC trong `[0,100]`, timestamp, source và payload size. `SIMULATED` bắt buộc có `scenario_id + simulation_run_id + tick`.

### `telemetry_events`

```text
id, trip_id, event_id
lat, lng, soc_percent, speed_kph, odometer_km
source_type, source_name, scenario_id, simulation_run_id, tick
client_timestamp, recorded_at, created_at, payload_json
UNIQUE(trip_id, event_id)
INDEX(trip_id, recorded_at DESC)
```

Append-only. Sample đến trễ được lưu audit nhưng không ghi đè latest telemetry.

### `monitoring_events`

```text
id, trip_id, event_type, severity
telemetry_refs_json, confirmed_plan_version
threshold_name, threshold_value, actual_value
requires_agent_decision
source_type, scenario_id, simulation_run_id, tick
occurred_at, handled_at, payload_json
```

### `simulation_runs`

```text
id, case_id, fixture_version, owner_id
status: CREATED | RUNNING | PAUSED | COMPLETED | FAILED | CANCELLED
current_tick, total_ticks, speed_multiplier, seed
started_at, paused_at, finished_at, error_code
UNIQUE(owner_id, idempotency_key)
```

## 9. API

| Method | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/api/v1/simulation-cases` | Liệt kê catalog, filter route/SOC/profile/status |
| `GET` | `/api/v1/simulation-cases/{case_id}` | Metadata và prerequisite |
| `POST` | `/api/v1/simulation-runs` | Start một case `READY` |
| `POST` | `/api/v1/simulation-runs/{id}/pause` | Pause |
| `POST` | `/api/v1/simulation-runs/{id}/resume` | Resume |
| `POST` | `/api/v1/simulation-runs/{id}/reset` | Reset về tick 0 |
| `GET` | `/api/v1/simulation-runs/{id}` | Poll state/latest telemetry/event |
| `POST` | `/api/v1/trips/{trip_id}/telemetry-events` | Ingestion chung cho runtime/simulator |

Mọi mutation nhận `idempotency_key`. API kiểm tra ownership; client không được tự nhận `REAL_API`.

## 10. Frontend

Thanh chọn hỗ trợ:

```text
Route (5) | Initial SOC (17/42/60) | Profile (6)
```

Hoặc một combobox 90 case:

```text
[HUST → Hữu Nghị] [SOC 17%] [ROUTE_DEVIATION]
```

Case `NOT_APPLICABLE/INVALID` hiển thị lý do và disable nút Start.

Màn hình run:

- start, pause, resume, reset;
- tốc độ `1×`, `5×`, `10×`;
- tick/progress và virtual time;
- map hiển thị confirmed polyline, marker thực tế và offset;
- SOC expected/actual;
- latest telemetry, freshness, provenance;
- monitoring event timeline;
- trạng thái F4: queued/running/decision/replan;
- old/candidate route sau khi F4 hoàn tất.

MVP dùng REST polling 1–2 giây. Chưa cần WebSocket, Redis, Kafka, PostGIS hoặc microservices.

## 11. Failure, audit và bảo mật

- Duplicate telemetry trả kết quả cũ, không nhân bản event.
- Một event type chỉ phát lại sau cooldown hoặc sau khi signal recovery rồi vi phạm lại.
- Runner crash có thể replay từ snapshot + seed + tick đã persist.
- F1 plan bị sửa/xóa sau khi tạo fixture không làm snapshot đổi.
- Provider/LLM call count bằng `0` ở `NORMAL`; planning call count bằng `0` ở `STALE_TELEMETRY`.
- Log: `trace_id`, `case_id`, `simulation_run_id`, `trip_id`, `plan_version`, tick, event, threshold, actual.
- Không lưu secret; giới hạn event size và rate theo run/trip.

## 12. Triển khai và kiểm thử

### Thứ tự

1. Freeze schema, policy và 15 base snapshots.
2. Implement fixture validator và catalog readiness.
3. Implement pure generator + frozen clock.
4. Implement telemetry persistence/dedup/latest snapshot.
5. Implement geometry, SOC interpolation và freshness rules.
6. Implement monitoring event persistence/cooldown.
7. Implement runner/API.
8. Implement frontend selector và replay.
9. Nối F4 qua `MonitoringEvent`.

### Test bắt buộc

| Test | Assertion |
|---|---|
| Catalog | 90 target entries; mỗi entry có readiness rõ ràng |
| Determinism | cùng snapshot/profile/seed cho sequence giống nhau |
| Normal zero-call | Agent/Routing/Station/LLM = 0 |
| Route boundary | 1.99/2.00 không event; 2.01 có event |
| SOC boundary | 4.9/5.0 không event; 5.1 có event |
| Stale boundary | 60s không stale; 61s stale; không replan |
| Station unavailable | target thuộc proposal; emit once; provenance simulated |
| Negative outcome | F4 chỉ infeasible khi tools chứng minh |
| Dedup | retry cùng event không tăng record/event count |
| Replay | thay live data không làm snapshot sequence đổi |
| Controls | pause không tăng tick; resume tiếp tục; reset về tick 0 |
| Ownership | user khác không start/xem run |

## 13. Definition of Done

- 15 F1/F2 base case được snapshot và có validation report.
- Catalog có 90 target case; UI không cho chạy case thiếu prerequisite.
- Năm event profiles và negative profile chạy deterministic.
- Threshold `>2km`, `>5%`, `>60s` pass boundary test.
- `NORMAL` không tạo warning/replan; `STALE_TELEMETRY` không replan mù.
- Station event chỉ dùng station có thật trong proposal và có provenance `SIMULATED`.
- Simulator đi qua cùng Telemetry/Monitoring service như runtime.
- UI cho chọn case, điều khiển replay và quan sát GPS/SOC/event/F4.
- Persistence, idempotency, cooldown, ownership và recovery có test.
- Mọi run truy được case snapshot, seed, tick, telemetry, event và plan version.

## 14. Mentor review deterministic controls — 2026-09-01

Runtime F3 cho phép operator nhập `seed`; backend giữ seed trong request và trả lại ở mọi `SimulationState`. Pause/resume không làm đổi seed; reset phát lại cùng scenario, boundary value và seed từ tick 0. Frontend không còn dùng `Date.now()` để tự sinh seed.

Các threshold dùng strict `>`: lệch tuyến `1.99/2.00/2.01 km`, SOC `4.9/5.0/5.1%`, telemetry `60/61 giây`. Multi-event dùng một telemetry snapshot và một tick cho 2–3 canonical events.

`STATION_UNAVAILABLE` chỉ được chọn khi confirmed proposal thật sự có `charging_stops`. Simulator không tự dựng trạm giả và không dùng bước xác minh GPS thật để chặn GPS mô phỏng. Event có `source=SIMULATED`, phát đúng một lần và đưa run vào `AWAITING_DECISION`.

Control F1 fault dành cho demo có ba giá trị typed: `NONE`, `F1_PROVIDER_FAILURE`, `F1_PROVEN_INFEASIBLE`. Control chỉ hiển thị khi `GET /api/v1/simulator/capabilities` trả `fault_injection_enabled=true`; backend mặc định tắt bằng `SIMULATOR_FAULT_INJECTION_ENABLED=false` và từ chối fault nếu telemetry không phải `SIMULATED`.

Các endpoint simulator canonical đang dùng:

| Method | Endpoint | Contract |
|---|---|---|
| `GET` | `/api/v1/simulator/capabilities` | Capability cho fault injection |
| `POST` | `/api/v1/simulator/trips/{trip_id}/start` | Scenario, exact value, seed, typed fault |
| `POST` | `/api/v1/simulator/trips/{trip_id}/tick` | Tiến một tick deterministic |
| `POST` | `/api/v1/simulator/trips/{trip_id}/pause|resume|reset` | Replay controls |
| `POST` | `/api/v1/simulator/trips/{trip_id}/refresh-telemetry` | Làm mới stale simulated telemetry |
| `POST` | `/api/v1/simulator/trips/{trip_id}/activate-plan` | Kích hoạt plan đã được owner xác nhận |

Coverage mentor được khóa bởi `test_f3_monitoring.py`, `test_monitoring_service.py`, `test_planning.py` và `test_f4.py`: `P210-F3-HAPPY-001`, `P210-F3-HAPPY-004`, `P210-F3-EDGE-002`, `P210-F3-EDGE-003`, `P210-F3-EDGE-005`, `P210-F3-EDGE-006`.
