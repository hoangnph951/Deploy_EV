# IMPLEMENTATION BACKLOG — AI EV Agent

**Phiên bản:** 3.1  
**Ngày cập nhật:** 08/08/2026  
**Nguồn tham chiếu:** PRD v3.0 + Technical Architecture v3.1 + Interface Design v1.0 + OpenAPI v1.0  
**Cấu trúc phân rã:** `Feature (Must 1–4, Should) → User Story → Task chi tiết kỹ thuật`.  
**Quy ước Ước lượng (Size):**
- **S (Small):** ≤ 0,5 ngày công (cấu hình, contract schema, script nhỏ, fix đơn giản).
- **M (Medium):** ≈ 1 ngày công (feature component, service method, test suite cụ thể).
- **L (Large):** ≈ 2–3 ngày công (workflow phức tạp, tích hợp đa module, UI dashboard đầy đủ).

---

## 0. Chiến lược triển khai & Thứ tự ưu tiên (Milestones)

### 0.1. Vertical Slice (Ưu tiên số 1 — Chạy thông luồng lõi đầu tiên)

Vertical slice phải hoàn thành sớm nhất để chứng minh tính khả thi của chuỗi công cụ deterministic kết hợp AI orchestration:

```text
Nhập trip (Origin, Destination, SOC)
→ Geocoding & Route geometry (OSRM/Mapbox)
→ Lọc trạm sạc snapshot fixture (Connector, Detour)
→ Tính toán tiêu hao năng lượng & SOC chặng
→ Kiểm tra Feasibility (Reserve SOC 15%)
→ Trả về và hiển thị Plan, Station & Risk trên giao diện Web
```

**Các task cấu thành Vertical Slice:**
- Nền tảng & Contract: `X-T01`, `X-T02`
- Nhập liệu & Giả định: `F1-US1-T01`, `F1-US1-T02`, `F1-US1-T04`, `F1-US1-T05`, `F1-US2-T01`, `F1-US2-T02`
- Công cụ tính toán: `F1-US3-T02`, `F1-US3-T03`, `F1-US3-T04`, `F1-US3-T05`, `F1-US4-T01`, `F1-US4-T02`
- Điều phối & Hiển thị: `F1-US3-T06`, `F1-US3-T07`, `F1-US3-T08`, `F1-US4-T04`

---

### 0.2. Lộ trình hoàn thiện các giai đoạn (Milestone Roadmap)

```text
Giai đoạn 1: Vertical Slice & Hoàn thiện Must 1 (Lập kế hoạch trước chuyến đi & Safety check)
    ↓
Giai đoạn 2: Must 2 (Giải thích có căn cứ, Versioning & Xác nhận kế hoạch - Human-in-the-loop)
    ↓
Giai đoạn 3: Must 3 (Theo dõi GPS/SOC mô phỏng & So sánh kế hoạch theo thời gian thực)
    ↓
Giai đoạn 4: Must 4 (Phát hiện sự kiện, Tái lập kế hoạch & Xin xác nhận lại)
    ↓
Giai đoạn 5: Should (Không gian hỗ trợ Read-only) & Cross-cutting (Benchmark 20 cases, CI/CD, Demo)
```

---

# Must 1 — Lập kế hoạch trước chuyến đi

> **Mục tiêu:** Nhập dữ liệu hành trình & xe, công bố minh bạch giả định, tính toán tuần tự Route – Energy – Station và kiểm tra tính khả thi an toàn (Feasibility) với mức pin dự phòng 15%.

---

## F1-US1 — Nhập điểm đầu, điểm cuối và SOC để yêu cầu kế hoạch

**User Story:** Là chủ xe, tôi muốn nhập điểm xuất phát, điểm đích và mức pin ban đầu để yêu cầu hệ thống tính toán một kế hoạch chuyến đi phù hợp.

**Acceptance Criteria:**
1. Hỗ trợ nhập địa chỉ dạng text và chuyển đổi thành tọa độ qua Geocoding.
2. Khi địa chỉ mơ hồ (nhiều kết quả tương đương), hệ thống trả về mã `AMBIGUOUS_LOCATION` kèm danh sách gợi ý để người dùng chọn lại.
3. Validate mức pin ban đầu `initial_soc_percent` bắt buộc trong khoảng [1, 100]; báo lỗi rõ ràng nếu ngoài khoảng.
4. Tạo bản ghi `Trip` ở trạng thái `DRAFT` kèm thông tin chủ sở hữu và giả định ban đầu.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F1-US1-T01** | **Chốt OpenAPI Contract & Schema Request/Response cho Trip**<br>- Định nghĩa schema `POST /api/v1/trips` và `GET /api/v1/trips/{id}` trong `openapi.yaml`.<br>- Quy chuẩn request body: `origin` (text hoặc `{lat, lon}`), `destination`, `initial_soc_percent` (float), `vehicle_profile_id` (string).<br>- Định nghĩa error schemas chuẩn: `VALIDATION_ERROR`, `AMBIGUOUS_LOCATION`. | BE + FE | X-T01 | OpenAPI schema được review và freeze; code generator sinh ra type an toàn cho cả TypeScript và Python. | **S** |
| **F1-US1-T02** | **Tạo SQLAlchemy Data Models & DB Migrations cho Trip & Vehicle**<br>- Tạo bảng `trips`: `id` (UUID), `user_id`, `origin_name`, `origin_lat`, `origin_lon`, `destination_name`, `destination_lat`, `destination_lon`, `initial_soc_percent`, `status` (`DRAFT, PLANNING, ACTIVE, COMPLETED, CANCELLED`), `created_at`, `updated_at`.<br>- Tạo bảng `vehicle_profiles`: `id`, `name`, `battery_capacity_kwh`, `usable_capacity_kwh`, `max_charging_power_kw`, `connector_type`, `consumption_curve_json`.<br>- Tạo migration script bằng Alembic và seed dữ liệu `VehicleProfile Xe X v1`. | BE / DB | F1-US1-T01 | Alembic migration chạy thành công không lỗi; seed profile nạp chuẩn xác vào PostgreSQL. | **M** |
| **F1-US1-T03** | **Xây dựng Geocoding Adapter & Xử lý Địa chỉ mơ hồ**<br>- Triển khai service kết nối Geocoding API (OSRM/Nominatim hoặc Mapbox Geocoding).<br>- Thuật toán xử lý: nếu độ tin cậy kết quả < threshold hoặc có ≥ 2 địa điểm trùng tên có khoảng cách xa nhau, trả về danh sách candidates kèm `AMBIGUOUS_LOCATION`.<br>- Cache kết quả geocoding bằng Redis/in-memory LRU để tối ưu tốc độ và chi phí. | BE | F1-US1-T01 | Địa chỉ rõ ràng được geocode chuẩn xác; địa chỉ mơ hồ trả danh sách gợi ý, không tự đoán sai vị trí. | **M** |
| **F1-US1-T04** | **Xây dựng Trip Service & Pydantic Request Validation**<br>- Tạo `TripCreateRequest` Pydantic model với các custom validator cho SOC (1–100%) và tọa độ hợp lệ.<br>- Xây dựng method `TripService.create_trip()`: xác thực token người dùng, lưu bản ghi `Trip` với status `DRAFT`, gắn `vehicle_profile_id` mặc định của Xe X.<br>- Gán `trace_id` cho request để truy vết toàn bộ vòng đời chuyến đi. | BE | F1-US1-T02, F1-US1-T03 | Input sai trả HTTP 422 `VALIDATION_ERROR` kèm chi tiết field; Input đúng tạo bản ghi `Trip` trong DB. | **M** |
| **F1-US1-T05** | **Xây dựng Giao diện Form nhập hành trình trên Frontend**<br>- Tạo React component `TripInputForm` với React Hook Form và Zod validation.<br>- Input Origin/Destination hỗ trợ search autocomplete có debounce (300ms).<br>- Input SOC hỗ trợ cả Slider và Number input đồng bộ giá trị; hiển thị cảnh báo nếu SOC < 20%.<br>- Modal/Dropdown hiển thị danh sách ứng viên khi nhận mã `AMBIGUOUS_LOCATION` để người dùng click chọn lại. | FE | F1-US1-T01 | Form giao diện đẹp, mượt mà, validate tức thì; xử lý mượt luồng gợi ý địa chỉ khi bị mơ hồ. | **M** |
| **F1-US1-T06** | **Kiểm thử Tự động Unit & Integration cho Luồng Khởi tạo Trip**<br>- Unit test Pydantic validator với các giá trị biên SOC (-5, 0, 1, 99, 100, 105).<br>- Integration test endpoint `POST /api/v1/trips` từ request HTTP đến khi dữ liệu nằm trong PostgreSQL.<br>- Mock Geocoding service để kiểm tra kịch bản địa chỉ thành công, địa chỉ mơ hồ và nhà cung cấp geocoding timeout. | QA / BE | F1-US1-T04, F1-US1-T05 | Toàn bộ test suite pass 100%; độ phủ code của Trip Service đạt > 90%. | **M** |

---

## F1-US2 — Xem các giả định đang được áp dụng

**User Story:** Là chủ xe, tôi muốn thấy rõ các thông số giả định mà hệ thống đang sử dụng để tính toán kế hoạch nhằm hiểu rõ cơ sở an toàn.

**Acceptance Criteria:**
1. Cấu hình mức pin dự phòng tối thiểu cố định `reserve_soc_percent = 15%` qua cấu hình tập trung, không hard-code rải rác.
2. Snapshot giả định lưu kèm mỗi phiên bản kế hoạch gồm: reserve SOC, nhiệt độ môi trường, tải trọng xe, phiên bản profile xe.
3. Giao diện hiển thị rõ bảng giả định kèm nhãn cảnh báo "Pilot Assumption" (đây là giả định thử nghiệm, không phải khuyến nghị vận hành chung).

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F1-US2-T01** | **Xây dựng Module Quản lý Cấu hình Chính sách `PolicyConfig`**<br>- Tạo model và bảng `policy_configs`: `id`, `policy_version`, `reserve_soc_percent` (mặc định 15.0), `stale_station_hours_threshold` (mặc định 24h), `route_deviation_km_threshold` (mặc định 2.0km), `active`.<br>- Xây dựng `PolicyConfigService` cung cấp hàm đọc policy có cache, hỗ trợ override trong môi trường testing. | BE | F1-US1-T02 | Cấu hình tập trung, không hard-code; thay đổi config trong DB/file làm thay đổi hành vi tính toán. | **S** |
| **F1-US2-T02** | **Xây dựng Fixture & Versioning cho `VehicleProfile Xe X v1`**<br>- Tạo file fixture JSON chuẩn hóa cho Xe X: dung lượng danh định 75 kWh, dung lượng khả dụng 71.2 kWh, cổng sạc CCS2, max DC charge 150 kW.<br>- Đường đặc tính tiêu hao năng lượng cơ sở: 175 Wh/km (ở 25°C, đường bằng, tải 150kg).<br>- Seed dữ liệu vào DB và đánh version `xe_x_v1.0`. | BE / Data | F1-US1-T02 | Dataset profile xe hoàn chỉnh, có version rõ ràng, sẵn sàng cho Energy Tool tham chiếu. | **S** |
| **F1-US2-T03** | **Thiết kế Schema `AssumptionSnapshot` và lưu trữ cùng Plan**<br>- Tạo Pydantic schema `AssumptionSnapshot`: `policy_version`, `reserve_soc_percent`, `ambient_temperature_c` (25.0), `vehicle_payload_kg` (150.0), `vehicle_profile_version`, `created_at`.<br>- Bổ sung trường JSONB `assumptions` vào bảng `plan_versions` để lưu bất biến giả định tại thời điểm lập kế hoạch. | BE | F1-US2-T01, F1-US2-T02 | Giả định được lưu nguyên vẹn cùng plan; không bị ảnh hưởng khi policy hệ thống thay đổi sau này. | **M** |
| **F1-US2-T04** | **Xây dựng UI Assumption Panel & Cảnh báo Pilot trên Frontend**<br>- Tạo React component `AssumptionPanel` dạng drawer hoặc card thông tin có thể thu gọn/mở rộng.<br>- Hiển thị trực quan: Mức pin dự phòng tối thiểu (15%), Nhiệt độ môi trường (25°C), Tải trọng (150kg), Mẫu xe (Xe X v1).<br>- Hiển thị badge màu cam "Pilot Assumption" kèm tooltip: *"Mức 15% là giả định thiết kế thử nghiệm, người lái cần chủ động theo dõi điều kiện thực tế"*. | FE | F1-US1-T05, F1-US2-T03 | Giao diện hiển thị rõ ràng, minh bạch, tuân thủ đúng yêu cầu truyền thông an toàn của PRD. | **M** |
| **F1-US2-T05** | **Kiểm thử Kiểm chứng Cấu hình Giả định**<br>- Viết test tự động kiểm tra: đổi `reserve_soc_percent` từ 15% sang 20% trong config thì output snapshot của plan mới nhận đúng 20%.<br>- Kiểm tra không có trường hợp nào tạo plan mà thiếu trường `assumptions`. | QA / BE | F1-US2-T01, F1-US2-T03 | Test suite pass; đảm bảo toàn bộ plan đều có nguồn gốc giả định minh bạch. | **S** |

---

## F1-US3 — Xem route, trạm, SOC dự kiến và mức rủi ro

**User Story:** Là chủ xe, tôi muốn xem lộ trình chi tiết trên bản đồ, các trạm sạc được đề xuất dừng, mức pin dự kiến tại từng chặng và mức độ rủi ro của chuyến đi.

**Acceptance Criteria:**
1. Lộ trình được định tuyến độc lập qua `RoutingProvider` (OSRM/Mapbox), trả về polyline, khoảng cách và thời gian.
2. Trạm sạc được lọc từ snapshot dataset theo hành lang tuyến (corridor), giới hạn detour và đúng chuẩn cổng CCS2 của Xe X.
3. Mức tiêu hao năng lượng và SOC đến từng điểm dừng (Arrival SOC) được tính toán theo mô hình vật lý deterministic.
4. LangGraph điều phối luồng tuần tự: `Routing → Station Tool + Energy Tool → Feasibility Tool → PlanProposal`.
5. Giao diện Web hiển thị bản đồ lộ trình, danh sách điểm dừng sạc, biểu đồ SOC và mức độ rủi ro.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F1-US3-T01** | **Chốt OpenAPI Contract `POST /api/v1/trips/{id}/plans` & Schema `PlanProposal`**<br>- Định nghĩa request kích hoạt tạo kế hoạch `POST /api/v1/trips/{id}/plans`.<br>- Định nghĩa structured response `PlanProposal`: `route` (polyline, distance_m, duration_s, segments), `charging_stops` (station_id, name, lat, lon, arrival_soc, departure_soc, charge_duration_min, energy_added_kwh), `risk_assessment` (level, reasons), `assumptions`. | BE + FE + Agent | F1-US1-T01 | OpenAPI contract được đóng băng; định dạng JSON trả về có cấu trúc chặt chẽ, đầy đủ dữ liệu vẽ UI. | **S** |
| **F1-US3-T02** | **Xây dựng `RoutingProvider` Abstraction & Tích hợp Mapbox/OSRM**<br>- Xây dựng interface `RoutingProvider` với method `get_route(origin, destination, waypoints)` trả về `RouteResult`.<br>- Triển khai `OSRMClient` và `MapboxClient` implements interface trên; parse chuẩn hóa geometry GeoJSON polyline, step instructions, elevation profile (nếu có).<br>- Cấu hình timeout 5s, circuit breaker và retry tối đa 2 lần khi gặp lỗi mạng. | BE / Agent | F1-US1-T01 | Module routing độc lập nhà cung cấp; có thể chuyển đổi linh hoạt qua biến môi trường hoặc mock trong test. | **M** |
| **F1-US3-T03** | **Tạo Snapshot Dataset Fixture Trạm sạc v1 & Provenance Metadata**<br>- Xây dựng dataset JSON fixture chứa ~50 trạm sạc trên các tuyến quốc lộ chính.<br>- Mỗi trạm chứa: `id`, `name`, `lat`, `lon`, `address`, `connector_types` (CCS2, Type2, CHAdeMO), `max_power_kw`, `source` (`CACHED_SNAPSHOT`), `snapshot_timestamp`, `status` (`OPERATIONAL`).<br>- Import fixture vào bảng `station_snapshots` có index không gian PostGIS / GiST. | BE / Data | F1-US1-T02 | Dataset chuẩn hóa, có metadata nguồn gốc và thời gian thu thập dữ liệu; query không gian nhanh. | **M** |
| **F1-US3-T04** | **Xây dựng Station Data Service & Station Tool theo Bounding Corridor**<br>- Xây dựng `StationDataService.find_corridor_stations()`: tính bounding box bao quanh polyline với bán kính mở rộng 5km (buffer corridor); tính khoảng cách rẽ nhánh (detour distance & time) từ tuyến chính đến trạm.<br>- Xây dựng LangChain/LangGraph Tool `StationTool`: nhận polyline và vehicle profile, lọc chỉ lấy trạm có cổng CCS2 và detour < 15 phút, gắn nhãn độ tươi mới `FRESH` (<24h) hoặc `STALE` (>24h). | BE / Agent | F1-US3-T02, F1-US3-T03 | Trả về danh sách trạm ứng viên khả dụng kèm lý do; loại bỏ hoàn toàn các trạm sai chuẩn cổng sạc. | **L** |
| **F1-US3-T05** | **Xây dựng Deterministic Energy Tool tính toán Tiêu hao & SOC Chặng**<br>- Xây dựng module tính toán vật lý: $E_{\text{seg}} = d \times \text{consumption rate} \times k_{\text{temp}} \times k_{\text{payload}}$.<br>- Tính toán mức SOC dọc tuyến theo từng bước: $\text{SOC}_{\text{arrival}} = \text{SOC}_{\text{start}} - (E_{\text{seg}} / C_{\text{usable}}) \times 100\%$.<br>- Tính toán thời gian sạc tại trạm để đạt mức SOC an toàn cho chặng tiếp theo (mặc định sạc đến 80% để tối ưu đường cong sạc nhanh). | Agent / Data | F1-US2-T02, F1-US3-T02 | Kết quả tính toán năng lượng mang tính tất định 100% (cùng input luôn cho cùng output); không phụ thuộc LLM. | **M** |
| **F1-US3-T06** | **Xây dựng LangGraph Orchestrator cho Luồng Lập kế hoạch (Planning Workflow)**<br>- Thiết kế LangGraph StateGraph: `Input State → Node Routing → Node Station & Energy Filter → Node Feasibility Check → Node Plan Proposal Generation`.<br>- Ràng buộc cứng thứ tự thực thi: Routing Tool bắt buộc chạy trước; Station và Energy Tool chạy song song/tuần tự; Feasibility Tool chạy cuối cùng.<br>- Bọc toàn bộ quá trình bằng logger `AgentRun` và `ToolRun` đo lường latency từng bước. | Agent | F1-US3-T02, F1-US3-T04, F1-US3-T05 | Workflow điều phối mượt mà, đúng logic tuần tự; xuất ra structured output `PlanProposal` hợp lệ. | **L** |
| **F1-US3-T07** | **Xây dựng Trip Service Persistence cho `PlanVersion`**<br>- Tạo bảng `plan_versions`: `id` (UUID), `trip_id`, `version_number` (int, bắt đầu từ 1), `status` (`PENDING, CONFIRMED, REJECTED, SUPERSEDED`), `route_geometry_json`, `distance_km`, `duration_min`, `charging_stops_json`, `assumptions_json`, `risk_level`, `created_at`.<br>- Xây dựng method `TripService.save_plan_proposal()`: nhận proposal từ Agent, validate tính toàn vẹn và lưu bản ghi ở trạng thái `PENDING` (Agent không có quyền ghi DB trực tiếp). | BE | F1-US3-T01, F1-US3-T06 | Kế hoạch được lưu trữ an toàn trong DB; trạng thái ban đầu luôn là `PENDING`, sẵn sàng cho chủ xe duyệt. | **M** |
| **F1-US3-T08** | **Xây dựng UI Bản đồ Lộ trình, Điểm dừng sạc & Biểu đồ SOC trên Frontend**<br>- Tích hợp thư viện bản đồ (Leaflet / Mapbox GL JS): vẽ polyline lộ trình, marker điểm xuất phát, đích đến và các trạm dừng sạc.<br>- Popup trạm sạc hiển thị: Tên trạm, Công suất (kW), Chuẩn cổng, Mức pin khi đến (Arrival SOC %), Thời gian sạc dự kiến (phút), Mức pin khi rời trạm (Departure SOC %).<br>- Xây dựng biểu đồ đường (Line Chart / Stepped Chart) thể hiện sự thay đổi của SOC % dọc theo quãng đường km.<br>- Hiển thị Risk Badge: `LOW_RISK` (Xanh), `MEDIUM_RISK` (Vàng), `HIGH_RISK` (Đỏ) kèm giải thích. | FE | F1-US3-T01, F1-US3-T07 | Bản đồ tương tác mượt mà, trực quan; biểu đồ SOC thể hiện rõ các điểm sạc pin và mức pin an toàn. | **L** |
| **F1-US3-T09** | **Kiểm thử Tích hợp End-to-End Happy Path cho Vertical Slice**<br>- Viết integration test: Tạo trip với Origin Hà Nội, Destination Vinh, initial SOC 90%.<br>- Verify: Hệ thống gọi Routing lấy polyline ~300km, Station Tool lọc được các trạm sạc trên QL1A, Energy Tool tính toán cần dừng sạc 1 lần, Feasibility xác nhận `FEASIBLE`, PlanVersion lưu ở trạng thái `PENDING`.<br>- Verify UI render đầy đủ bản đồ, trạm sạc và biểu đồ pin. | QA / FE / BE | F1-US3-T01–F1-US3-T08 | Vertical slice chạy thông suốt từ UI qua BE, Agent và lưu DB thành công 100%. | **L** |

---

## F1-US4 — Từ chối phương án không đạt điều kiện an toàn

**User Story:** Là chủ xe, tôi muốn hệ thống cảnh báo rõ ràng và từ chối tạo phương án nếu chuyến đi không đảm bảo an toàn (ví dụ: pin tụt dưới 15% hoặc không có trạm sạc tương thích).

**Acceptance Criteria:**
1. Định nghĩa bộ quy tắc đánh giá an toàn với các verdict: `FEASIBLE`, `RISKY`, `INFEASIBLE`.
2. Chặn đứng phương án nếu Arrival SOC tại bất kỳ điểm nào < 15% (Reserve SOC).
3. Loại bỏ các trạm sạc không đúng chuẩn cổng CCS2 hoặc dữ liệu snapshot quá hạn mà không có trạm thay thế.
4. Trả về response `NoFeasiblePlan` có giải thích lý do cụ thể; tuyệt đối không tạo trạm sạc giả hoặc kế hoạch ảo.
5. Giao diện hiển thị cảnh báo nổi bật, giải thích nguyên nhân không khả thi.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F1-US4-T01** | **Định nghĩa Bộ Quy tắc An toàn & Reason Codes cho Feasibility**<br>- Xây dựng document và constants định nghĩa các verdict: `FEASIBLE` (mọi tiêu chí đều đạt), `RISKY` (đạt nhưng sát ngưỡng hoặc dữ liệu trạm cũ), `INFEASIBLE` (vi phạm an toàn).<br>- Định nghĩa mã lý do chuẩn hóa: `SOC_BELOW_RESERVE_15`, `NO_COMPATIBLE_CONNECTOR`, `UNREACHABLE_NEXT_STATION`, `STALE_STATION_DATA`, `ROUTING_UNAVAILABLE`. | Tech Lead + BE + QA | F1-US2-T01 | Bộ quy tắc an toàn được chốt; định nghĩa rõ ràng điều kiện kích hoạt từng mã lý do. | **S** |
| **F1-US4-T02** | **Xây dựng Feasibility Tool Deterministic kiểm tra An toàn**<br>- Triển khai `FeasibilityTool` độc lập với LLM: nhận danh sách các chặng, mức SOC tính toán và thông tin trạm sạc.<br>- Thuật toán kiểm tra:<br>  1. Nếu tồn tại bất kỳ chặng nào có $\text{SOC}_{\text{arrival}} < 15.0\%$ (Reserve SOC) $\rightarrow$ gán `INFEASIBLE` + code `SOC_BELOW_RESERVE_15`.<br>  2. Nếu trạm sạc được chọn không hỗ trợ CCS2 $\rightarrow$ gán `INFEASIBLE` + code `NO_COMPATIBLE_CONNECTOR`.<br>  3. Nếu trạm sạc có `freshness == STALE` $\rightarrow$ hạ mức đánh giá xuống `RISKY` + code `STALE_STATION_DATA`.<br>- Trả về struct `FeasibilityVerdict` gồm verdict, risk_score (0–100), và danh sách `reason_codes`. | Agent / BE | F1-US3-T04, F1-US3-T05, F1-US4-T01 | Tool chạy deterministic 100%; bắt chính xác mọi trường hợp vi phạm an toàn; không có ngoại lệ lọt lưới. | **M** |
| **F1-US4-T03** | **Áp dụng Nguyên tắc Fail-Closed & Xử lý `NoFeasiblePlan` trong Agent**<br>- Cập nhật LangGraph workflow: nếu `FeasibilityVerdict == INFEASIBLE` hoặc external API (Mapbox/OSRM) gặp sự cố timeout/lỗi 5xx, Agent lập tức chuyển sang trạng thái kết thúc `NoFeasiblePlan`.<br>- Trip Service tạo bản ghi `PlanVersion` với `risk_level = INFEASIBLE`, danh sách `charging_stops = []` và lưu lý do từ chối.<br>- Nghiêm cấm Agent tự ý suy diễn hoặc "bịa" ra trạm sạc không có trong snapshot fixture. | Agent + BE | F1-US3-T06, F1-US4-T02 | Hệ thống fail-closed an toàn; không trả ra kế hoạch sạc giả khi chuyến đi không khả thi. | **M** |
| **F1-US4-T04** | **Xây dựng UI Cảnh báo Infeasible / Risky & Hiển thị Lý do Từ chối**<br>- Tạo React component `InfeasibleWarningBanner` với phong cách trực quan, màu đỏ cảnh báo nổi bật.<br>- Hiển thị rõ danh sách lý do hệ thống từ chối: ví dụ *"Mức pin dự kiến khi đến trạm sạc chỉ còn 8% (thấp hơn mức an toàn tối thiểu 15%)"* hoặc *"Không tìm thấy trạm sạc chuẩn CCS2 trên hành lang tuyến"*\.<br>- Gợi ý giải pháp cho người dùng: sạc đầy pin trước khi khởi hành hoặc chọn điểm dừng trung gian. | FE | F1-US3-T08, F1-US4-T03 | Giao diện cảnh báo rõ ràng, không gây hiểu nhầm rằng đây là kế hoạch có thể thực hiện được. | **M** |
| **F1-US4-T05** | **Bộ Kiểm thử Tự động Kiểm chứng Ranh giới An toàn (Safety Boundary Suite)**<br>- Viết test suite chuyên biệt kiểm tra các trường hợp biên:<br>  1. Case Arrival SOC = 15.0% $\rightarrow$ FEASIBLE.<br>  2. Case Arrival SOC = 14.9% $\rightarrow$ INFEASIBLE.<br>  3. Case quãng đường quá dài không có trạm sạc nào $\rightarrow$ INFEASIBLE.<br>  4. Case trạm sạc có cổng CHAdeMO nhưng không có CCS2 $\rightarrow$ Bị loại khỏi ứng viên.<br>  5. Case Routing provider trả lỗi 500 $\rightarrow$ Trả `PROVIDER_ERROR`, fail-closed an toàn.<br>- Assert Infeasible Recall đạt 100% trên tập test an toàn. | QA / BE | F1-US4-T01–F1-US4-T04 | 100% ca thử nghiệm an toàn pass; chứng minh tính an toàn tuyệt đối của hệ thống trước khi sang F2. | **L** |

---

# Must 2 — Giải thích và xác nhận kế hoạch

> **Mục tiêu:** Cung cấp lời giải thích minh bạch dựa trên dữ liệu có cấu trúc (không bịa đặt), quản lý lịch sử phiên bản kế hoạch không bị ghi đè, và đảm bảo kế hoạch chỉ có hiệu lực sau khi được chính chủ xe xác nhận (Human-in-the-loop).

---

## F2-US1 — Biết vì sao hệ thống chọn/loại tuyến hoặc trạm

**User Story:** Là chủ xe, tôi muốn hiểu rõ lý do hệ thống lựa chọn trạm sạc này và loại bỏ các trạm sạc khác để tin tưởng kế hoạch.

**Acceptance Criteria:**
1. Lời giải thích phải tham chiếu trực tiếp đến dữ liệu đầu ra của tool (`station_id`, khoảng cách detour, công suất sạc, SOC arrival).
2. Kiểm duyệt prompt và output của LLM: nghiêm cấm đề cập đến trạm sạc hoặc dữ liệu không tồn tại trong tool output (Zero Hallucination).
3. Có sẵn bộ template tĩnh dự phòng (fallback template) để luôn có lời giải thích có căn cứ khi LLM lỗi hoặc timeout.
4. Giao diện cho phép người dùng click xem chi tiết lý do chọn và lý do loại trừ từng trạm.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F2-US1-T01** | **Chốt Schema `ExplanationReferences` & Contract Giải thích**<br>- Định nghĩa Pydantic schema `ExplanationReferences`: danh sách các trích dẫn chứa `entity_type` (`STATION, ROUTE, ENERGY`), `entity_id`, `metric_name` (`POWER_KW, DETOUR_KM, ARRIVAL_SOC`), `metric_value`.<br>- Định nghĩa schema `ExplanationPayload`: `summary_text`, `selected_station_reasons` (map station_id $\rightarrow$ reason), `rejected_station_reasons` (map station_id $\rightarrow$ rejection_reason), `references`. | Agent + BE | F1-US3-T01 | Schema được chuẩn hóa; đảm bảo mọi câu giải thích đều có thể truy ngược về dữ liệu gốc của tool. | **S** |
| **F2-US1-T02** | **Xây dựng Grounded Prompt & Module Explanation Generator**<br>- Xây dựng LLM prompt có cấu trúc: chỉ cung cấp JSON kết quả của Routing, Station và Feasibility tool; yêu cầu LLM tóm tắt lý do chọn trạm dựa trên 3 tiêu chí: (1) Đảm bảo reserve SOC ≥ 15%, (2) Công suất sạc cao nhất, (3) Khoảng cách detour ngắn nhất.<br>- Xây dựng `DeterministicExplanationFallback`: hàm sinh text giải thích theo template chuẩn mà không cần gọi LLM (sử dụng khi LLM gặp lỗi mạng hoặc timeout > 3s). | Agent | F2-US1-T01 | Generator sinh lời giải thích tự nhiên, chính xác; fallback template hoạt động tức thì khi LLM timeout. | **M** |
| **F2-US1-T02-B** | **Xây dựng Grounding Validator chống Hallucination**<br>- Xây dựng middleware validator kiểm tra output của LLM:<br>  1. Trích xuất toàn bộ tên trạm sạc và con số trong text giải thích.<br>  2. Đối chiếu với danh sách trạm sạc trong `ToolOutput`.<br>  3. Nếu phát hiện trạm sạc hoặc thông số bịa đặt không có trong dữ liệu gốc $\rightarrow$ hủy output LLM và kích hoạt `DeterministicExplanationFallback`. | BE / QA | F2-US1-T02 | Hallucinated facts = 0; bảo đảm 100% thông tin hiển thị cho người dùng là dữ liệu đã được xác thực. | **M** |
| **F2-US1-T03** | **Xây dựng UI Panel "Lý do Đề xuất & Đánh giá Trạm Sạc"**<br>- Tạo React component `StationExplanationCard` gắn liền với từng trạm sạc trên danh sách và popup bản đồ.<br>- Hiển thị rõ: *"Vì sao chọn trạm này?"* (công suất 150kW giúp tiết kiệm 20 phút, chỉ detour 500m, đến trạm còn 18% pin an toàn).<br>- Nút bấm *"Xem các trạm lân cận bị bỏ qua"* mở rộng danh sách các trạm bị loại kèm mã lý do (ví dụ: công suất chỉ 11kW quá chậm, hoặc detour quá xa > 5km). | FE | F1-US3-T08, F2-US1-T01 | Giao diện trực quan, minh bạch; giúp chủ xe hoàn toàn an tâm và hiểu rõ quyết định của hệ thống. | **M** |
| **F2-US1-T04** | **Kiểm thử Tính Chân thực của Lời Giải thích (Grounding Test Suite)**<br>- Viết test tự động kiểm tra: text giải thích chứa đúng ID và tên trạm sạc từ fixture.<br>- Test kịch bản giả lập LLM bị lỗi kết nối hoặc trả về nội dung sai lệch $\rightarrow$ hệ thống tự động fallback về template tĩnh chuẩn xác.<br>- Đo lường thời gian sinh lời giải thích < 2s. | QA / Agent | F2-US1-T02, F2-US1-T02-B | Test suite pass; bảo đảm tính trung thực tuyệt đối của nội dung giải thích trước khi người dùng xác nhận. | **M** |

---

## F2-US2 — Xác nhận hoặc từ chối plan

**User Story:** Là chủ xe, tôi muốn chủ động bấm Xác nhận hoặc Từ chối kế hoạch được đề xuất để giữ toàn quyền kiểm soát chuyến đi của mình.

**Acceptance Criteria:**
1. Kế hoạch chỉ được chuyển sang trạng thái `CONFIRMED` khi có thao tác bấm Xác nhận tường minh của chính chủ xe.
2. Kiểm tra phân quyền chặt chẽ (Authorization): người dùng khác hoặc nhân viên hỗ trợ không có quyền confirm/reject.
3. Áp dụng Optimistic Locking chống xung đột trạng thái (Version conflict / Double confirm).
4. Lưu vết Audit Log đầy đủ khi có thao tác xác nhận hoặc từ chối.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F2-US2-T01** | **Chốt OpenAPI Contract cho Confirm & Reject Plan**<br>- Định nghĩa schema `POST /api/v1/plans/{id}/confirm` và `POST /api/v1/plans/{id}/reject`.<br>- Request header hỗ trợ `If-Match: "{version_number}"` để xử lý optimistic concurrency.<br>- Định nghĩa response schema trả về `Trip` với status cập nhật (`PLANNING → ACTIVE` khi confirm) và `PlanVersion` status (`PENDING → CONFIRMED` hoặc `REJECTED`).<br>- Định nghĩa error code `VERSION_CONFLICT` (HTTP 409) và `UNAUTHORIZED_ACTION` (HTTP 403). | BE + FE | F1-US3-T01 | Contract OpenAPI được freeze; định nghĩa rõ ràng mã lỗi và payload cho cả 2 thao tác. | **S** |
| **F2-US2-T02** | **Xây dựng Plan State Machine & Nghiệp vụ Xác nhận Kế hoạch**<br>- Triển khai State Machine quản lý trạng thái kế hoạch: `PENDING → CONFIRMED / REJECTED / SUPERSEDED`.<br>- Xây dựng method `TripService.confirm_plan(plan_id, user_id, expected_version)` trong DB transaction:<br>  1. Kiểm tra quyền sở hữu `trip.user_id == user_id`.<br>  2. Kiểm tra `plan.status == PENDING` và version khớp với `expected_version`.<br>  3. Chuyển plan hiện tại thành `CONFIRMED`, chuyển mọi plan `CONFIRMED` trước đó của trip thành `SUPERSEDED`.<br>  4. Cập nhật `trip.status = ACTIVE` và `trip.current_plan_version_id = plan.id`. | BE | F1-US3-T07, F2-US2-T01 | State transition chặt chẽ; transaction an toàn ACID; chỉ có duy nhất 1 plan ở trạng thái `CONFIRMED`. | **M** |
| **F2-US2-T03** | **Xây dựng Nghiệp vụ Từ chối Kế hoạch & Audit Logging**<br>- Triển khai method `TripService.reject_plan(plan_id, user_id, reason)`:<br>  1. Xác thực quyền sở hữu trip.<br>  2. Chuyển trạng thái `plan.status = REJECTED`.<br>  3. Giữ nguyên trạng thái của plan confirmed hiện hành (nếu có).<br>- Ghi nhận bản ghi vào bảng `audit_logs`: `trip_id`, `plan_id`, `actor_id`, `action` (`CONFIRM_PLAN / REJECT_PLAN`), `ip_address`, `timestamp`. | BE | F2-US2-T02 | Thao tác từ chối được xử lý chuẩn xác; audit log ghi nhận đầy đủ phục vụ truy vết bảo mật. | **M** |
| **F2-US2-T04** | **Xây dựng UI Thanh công cụ Xác nhận/Từ chối & Modal Cam kết trên Frontend**<br>- Tạo React component `PlanConfirmationBar` cố định ở cuối màn hình khi có proposal ở trạng thái `PENDING`.<br>- Nút "Xác nhận kế hoạch" (màu xanh nổi bật) và nút "Từ chối" (màu xám viền đỏ).<br>- Khi bấm "Xác nhận", mở `ConfirmationModal` tóm tắt các điểm quan trọng: điểm dừng sạc, thời gian dự kiến và cam kết giữ reserve SOC ≥ 15%.<br>- Xử lý loading spinner, disable nút chống double-click; bắt lỗi 409 Conflict và hiển thị thông báo tải lại phiên bản mới nhất. | FE | F2-US2-T01, F2-US2-T02 | Giao diện thân thiện, an toàn; thao tác xác nhận mượt mà; ngăn chặn triệt để bấm nhầm hoặc bấm lặp. | **M** |
| **F2-US2-T05** | **Kiểm thử Phân quyền, Race Condition & Concurrency Suite**<br>- Viết integration test: User A không thể confirm plan của User B (trả về 403 Forbidden).<br>- Test race-condition: giả lập gửi 2 request confirm đồng thời cho cùng 1 plan $\rightarrow$ 1 request thành công, 1 request trả về 409 Conflict.<br>- Test flow Reject plan: plan chuyển thành `REJECTED`, trip không bị chuyển trạng thái sai. | QA / BE | F2-US2-T02–F2-US2-T04 | Tất cả test cases pass 100%; chứng minh tính an toàn tuyệt đối trong quản lý giao dịch kế hoạch. | **M** |

---

## F2-US3 — Plan cũ không bị ghi đè và có thể truy vết

**User Story:** Là chủ xe, tôi muốn xem lại toàn bộ lịch sử các phiên bản kế hoạch đã tạo và so sánh sự khác biệt giữa các phiên bản.

**Acceptance Criteria:**
1. Mỗi kế hoạch tạo ra là một bản ghi `PlanVersion` bất biến (Immutable), không bao giờ bị lệnh `UPDATE` ghi đè dữ liệu cũ.
2. Endpoint `GET /api/v1/trips/{id}/plans` trả về danh sách lịch sử đầy đủ theo thứ tự version tăng dần (v1, v2, v3...).
3. Giao diện hỗ trợ xem dòng thời gian (Timeline) và chế độ so sánh khác biệt (Plan Diff) giữa các phiên bản.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F2-US3-T01** | **Thiết kế Cấu trúc Dữ liệu Bất biến cho `PlanVersion`**<br>- Đảm bảo bảng `plan_versions` có khóa duy nhất `UNIQUE(trip_id, version_number)`.<br>- Mọi thông tin lộ trình, trạm sạc, năng lượng, giả định được lưu trữ dưới dạng snapshot JSONB độc lập.<br>- DB constraint: cấm thay đổi các trường dữ liệu nội dung khi `status != PENDING`. | BE / DB | F1-US3-T07 | Dữ liệu phiên bản kế hoạch hoàn toàn bất biến; không thể bị ghi đè hoặc làm hỏng dữ liệu lịch sử. | **S** |
| **F2-US3-T02** | **Xây dựng API Lịch sử Phiên bản `GET /api/v1/trips/{id}/plans`**<br>- Triển khai endpoint lấy toàn bộ danh sách phiên bản kế hoạch của trip.<br>- Trả về danh sách `PlanVersionSummary`: `id`, `version_number`, `status`, `created_at`, `total_distance_km`, `total_duration_min`, `stop_count`, `risk_level`, `trigger_reason`.<br>- Hỗ trợ query chi tiết từng version qua `GET /api/v1/plans/{id}`. | BE | F2-US3-T01 | API trả về danh sách có thứ tự rõ ràng; response nhanh nhờ index tối ưu trên `(trip_id, version_number)`. | **M** |
| **F2-US3-T03** | **Xây dựng UI Timeline Lịch sử Phiên bản trên Frontend**<br>- Tạo React component `PlanHistoryTimeline` hiển thị danh sách các thẻ version (v1, v2, v3...).<br>- Mỗi thẻ hiển thị: Số phiên bản, Badge trạng thái (`CONFIRMED, SUPERSEDED, REJECTED`), Thời gian tạo, Lý do tạo (Kế hoạch ban đầu / Lệch tuyến / Pin tụt).<br>- Cho phép người dùng click vào version cũ để xem lại lộ trình và trạm sạc đã lưu ở dạng chỉ đọc. | FE | F2-US3-T02 | Timeline trực quan, dễ theo dõi; người dùng dễ dàng xem lại các phương án đã từng được tạo. | **M** |
| **F2-US3-T04** | **Xây dựng Giao diện So sánh Phiên bản Kế hoạch (Plan Diff View)**<br>- Tạo React component `PlanDiffModal` cho phép chọn 2 version để so sánh.<br>- Bản đồ hiển thị đồng thời 2 lộ trình: Version cũ (đường nét đứt màu xám), Version mới (đường nét liền màu xanh).<br>- Bảng đối chiếu chỉ số: So sánh tổng quãng đường ($\Delta\text{ km}$), thời gian di chuyển ($\Delta\text{ phút}$), các trạm sạc mới được thêm/bớt, và chênh lệch SOC khi đến đích. | FE | F2-US3-T03 | Giao diện so sánh trực quan, nêu bật rõ ràng sự khác biệt giữa các phương án để người dùng dễ quyết định. | **L** |
| **F2-US3-T05** | **Kiểm thử Tính Toàn vẹn của Lịch sử Phiên bản Kế hoạch**<br>- Viết integration test: Tạo liên tiếp 3 phiên bản kế hoạch cho 1 trip.<br>- Kiểm tra DB: có đủ 3 bản ghi với `version_number` từ 1 đến 3; bản ghi v1 và v2 không bị thay đổi nội dung lộ trình.<br>- Kiểm tra API history trả về đúng thứ tự và đầy đủ metadata. | QA / BE | F2-US3-T01–F2-US3-T04 | Lịch sử kế hoạch được bảo toàn nguyên vẹn 100%; không có hiện tượng mất mát dữ liệu phiên bản. | **M** |

---

# Must 3 — Theo dõi chuyến đi mô phỏng

> **Mục tiêu:** Tiếp nhận tọa độ GPS thực tế kết hợp mô phỏng mức pin SOC và các sự kiện chuyến đi, gắn nhãn nguồn gốc & độ tươi mới dữ liệu, và liên tục so sánh với kế hoạch mà không gọi AI Agent bừa bãi khi hành trình bình thường.

---

## F3-US1 — Xem vị trí và SOC hiện tại

**User Story:** Là chủ xe, tôi muốn theo dõi vị trí di chuyển thực tế của xe và mức pin SOC hiện tại trên bản đồ giám sát hành trình.

**Acceptance Criteria:**
1. Thu nhận tọa độ GPS thực tế từ trình duyệt web (`navigator.geolocation.watchPosition`).
2. Bộ giả lập (Simulator) có khả năng phát dữ liệu telemetry mô phỏng (SOC giảm dần, odometer tăng dần) theo kịch bản tất định (deterministic seed).
3. Lưu trữ chuỗi sự kiện `TelemetryEvent` có timestamp và nhãn nguồn gốc dữ liệu.
4. Giao diện Dashboard hiển thị vị trí xe di chuyển, mức pin hiện tại và thời gian cập nhật gần nhất.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F3-US1-T01** | **Chốt OpenAPI Contract & Schema Ingestion Telemetry**<br>- Định nghĩa schema `POST /api/v1/trips/{id}/telemetry`.<br>- Request payload `TelemetryInput`: `lat` (float), `lon` (float), `soc_percent` (float), `speed_kph` (optional), `odometer_km` (optional), `source` (`REAL_GPS, SIMULATED`), `client_timestamp`.<br>- Xây dựng cơ chế chống spam/rate limiting: tối đa 1 update mỗi 3 giây cho mỗi trip. | BE + FE + Simulator | F2-US2-T01 | Contract OpenAPI được freeze; payload telemetry nhẹ, tối ưu cho việc gửi liên tục qua HTTP/WebSocket. | **S** |
| **F3-US1-T02** | **Tạo Data Model `TelemetryEvent` & Pipeline Lưu trữ Time-series**<br>- Tạo bảng `telemetry_events`: `id` (UUID), `trip_id`, `lat`, `lon`, `soc_percent`, `speed_kph`, `odometer_km`, `source`, `recorded_at`, `created_at`.<br>- Tạo index tối ưu trên `(trip_id, recorded_at DESC)` để truy vấn telemetry mới nhất với độ trễ < 5ms.<br>- Xây dựng method `TelemetryService.ingest_event()` validate và lưu dữ liệu. | BE / DB | F3-US1-T01 | Lưu trữ telemetry ổn định; truy vấn vị trí và mức pin mới nhất cực nhanh. | **M** |
| **F3-US1-T03** | **Tích hợp Web Geolocation API thu thập GPS thật trên Frontend**<br>- Xây dựng custom React hook `useGeolocationTracking(tripId, isTracking)`:<br>  1. Gọi `navigator.geolocation.watchPosition` với option `enableHighAccuracy: true, maximumAge: 5000`.<br>  2. Lọc bỏ các điểm GPS có độ chính xác kém (`accuracy > 50m`).<br>  3. Gửi tọa độ lên endpoint telemetry với nhãn `source = REAL_GPS`.<br>- Xử lý cấp quyền Geolocation và hiển thị thông báo hướng dẫn người dùng nếu quyền bị từ chối. | FE | F3-US1-T01 | Thu thập tọa độ GPS thực tế từ thiết bị mượt mà; tự động reconnect khi mạng chập chờn. | **M** |
| **F3-US1-T04** | **Xây dựng Bộ Giả lập Hành trình Deterministic (Telemetry Simulator)**<br>- Xây dựng service `TelemetrySimulator`: đọc lộ trình polyline của plan đã confirm, tính toán tọa độ xe di chuyển theo từng tick thời gian.<br>- Mô phỏng mức SOC giảm dần theo quãng đường di chuyển và tốc độ tiêu hao danh định.<br>- Hỗ trợ các tham số cấu hình: `seed` (ngẫu nhiên có kiểm soát), `tick_interval_ms` (1000ms), `speed_multiplier` (x1, x5, x10 để test nhanh).<br>- Cung cấp endpoint test `POST /api/v1/simulator/trips/{id}/start` và `/stop`. | BE / Simulator | F3-US1-T02 | Giả lập chạy deterministic 100% (cùng seed luôn cho cùng timeline tọa độ/SOC); phục vụ demo và test tự động. | **L** |
| **F3-US1-T05** | **Xây dựng UI Giám sát Hành trình Thời gian thực (Live Monitoring Dashboard)**<br>- Tạo React component `TripMonitoringDashboard`:<br>  1. Marker xe di chuyển mượt mà trên bản đồ lộ trình (sử dụng animation nội suy giữa các điểm GPS).<br>  2. Đồng hồ đo mức pin SOC lớn, trực quan kèm màu sắc (Xanh > 40%, Vàng 20–40%, Đỏ < 20%).<br>  3. Bảng thông số: Tốc độ hiện tại, Quãng đường đã đi, Quãng đường tới trạm sạc tiếp theo, Thời gian cập nhật gần nhất (ví dụ: *"vừa xong"*, *"5 giây trước"*). | FE | F3-US1-T01, F3-US1-T03, F3-US1-T04 | Giao diện giám sát hiện đại, phản hồi tức thì theo luồng telemetry; người dùng nắm bắt toàn diện trạng thái xe. | **L** |
| **F3-US1-T06** | **Kiểm thử Khả năng Tái lập của Bộ Giả lập & Pipeline Telemetry**<br>- Viết test tự động: Chạy simulator với `seed = 42` trong 100 ticks; kiểm tra chuỗi tọa độ và SOC sinh ra trùng khớp 100% với baseline snapshot.<br>- Test tải nhẹ: Gửi 500 telemetry events liên tục; verify không có event nào bị mất mát trong DB. | QA / Simulator | F3-US1-T02, F3-US1-T04 | Bộ giả lập chứng minh tính tất định và độ tin cậy cao, sẵn sàng phục vụ cho việc kiểm thử các kịch bản biến cố. | **M** |

---

## F3-US2 — Biết dữ liệu nào thật và dữ liệu nào mô phỏng

**User Story:** Là chủ xe, tôi muốn biết rõ từng thông số trên màn hình là dữ liệu đo thực tế, dữ liệu mô phỏng hay dữ liệu trích xuất từ bộ nhớ đệm để không hiểu lầm trạng thái thực của xe.

**Acceptance Criteria:**
1. Chuẩn hóa hệ thống nhãn nguồn dữ liệu (Provenance): `REAL_GPS`, `REAL_API`, `SIMULATED`, `CACHED_SNAPSHOT`, `MANUAL`.
2. 100% các trường dữ liệu quan trọng (GPS, SOC, Trạm sạc, Lộ trình) đều có gắn kèm metadata nguồn gốc và độ tươi mới (Freshness).
3. Giao diện hiển thị Badge màu sắc và Tooltip minh bạch; tuyệt đối không mô tả dữ liệu mô phỏng như dữ liệu trực tiếp từ xe thật.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F3-US2-T01** | **Chuẩn hóa Enum Provenance & Schema Data Wrapper**<br>- Định nghĩa enum Python/TypeScript `DataSourceProvenance`: `REAL_GPS`, `REAL_API`, `SIMULATED`, `CACHED_SNAPSHOT`, `MANUAL`.<br>- Xây dựng generic wrapper schema `TrackedValue<T>`: `{ value: T, source: DataSourceProvenance, updated_at: datetime, freshness_seconds: int }`.<br>- Áp dụng wrapper cho các trường: tọa độ xe, mức pin SOC, danh sách trạm sạc, thông tin lộ trình. | BE + FE | F3-US1-T01 | Toàn bộ schema API được chuẩn hóa; không có trường dữ liệu quan trọng nào bị "vô danh" về nguồn gốc. | **S** |
| **F3-US2-T02** | **Tính toán Độ tươi mới (Data Freshness) trên Backend & Frontend**<br>- Xây dựng utility tính toán độ tuổi dữ liệu: $\text{freshness} = \text{now}() - \text{updated at}$.<br>- Phân loại mức độ tươi mới cho dữ liệu trạm sạc và telemetry: `FRESH` (dưới 24h đối với trạm / dưới 30s đối với telemetry), `STALE` (vượt ngưỡng), `UNKNOWN`.<br>- Trả về thông tin phân loại độ tươi mới trong các API response. | BE + FE | F3-US2-T01 | Hệ thống tự động phát hiện và đánh dấu các dữ liệu đã cũ hoặc mất kết nối cập nhật. | **S** |
| **F3-US2-T03** | **Xây dựng Hệ thống UI Badge & Tooltip Provenance Thống nhất**<br>- Tạo React component `ProvenanceBadge` dùng chung toàn bộ ứng dụng:<br>  - `REAL_GPS` / `REAL_API`: Badge Xanh lá cây (🟢 Dữ liệu thật).<br>  - `SIMULATED`: Badge Tím (🟣 Dữ liệu mô phỏng).<br>  - `CACHED_SNAPSHOT`: Badge Vàng cam (🟡 Dữ liệu đệm snapshot).<br>  - `MANUAL`: Badge Xám (⚪ Nhập thủ công).<br>- Tooltip giải thích chi tiết khi hover: nguồn gốc dữ liệu, thời điểm thu thập và cảnh báo tương ứng. | FE | F3-US2-T01, F3-US2-T02 | Giao diện nhất quán 100%; người dùng phân biệt rõ ràng tức thì giữa dữ liệu thực và dữ liệu giả lập. | **M** |
| **F3-US2-T04** | **Kiểm toán Giao diện & Rà soát Tuyên bố Trạng thái (Compliance Review)**<br>- Rà soát toàn bộ các màn hình hiển thị, tiêu đề, modal và thông báo.<br>- Đảm bảo không có bất kỳ câu chữ nào tuyên bố hoặc gây hiểu nhầm rằng hệ thống đang đọc trực tiếp SOC từ cổng OBD-II của xe hoặc đọc trạng thái trạm sạc thời gian thực từ trạm.<br>- Cập nhật disclaimer ở footer: *"Dữ liệu pin trong phiên demo được tạo bởi bộ mô phỏng hành trình"*. | PO + QA + FE | F3-US2-T03 | Đạt chuẩn quy định sản phẩm của PRD; tránh hoàn toàn rủi ro truyền thông sai sự thật về năng lực hệ thống. | **S** |

---

## F3-US3 — Chỉ kích hoạt Agent khi có thay đổi đáng kể

**User Story:** Là chủ xe, tôi muốn hệ thống chỉ gọi AI Agent để tính toán lại khi có biến cố thực sự (như đi lạc đường hoặc pin tụt nhanh), tránh việc tính toán liên tục gây lãng phí tài nguyên và làm phiền.

**Acceptance Criteria:**
1. Cấu hình tập trung các ngưỡng kích hoạt biến cố (Deviation threshold > 2km, SOC underperformance > 5%, Telemetry stale > 60s).
2. `Monitoring Service` so sánh liên tục telemetry với kế hoạch hiện hành; khi không có biến cố, tuyệt đối không gọi Agent hoặc Routing tool (Unnecessary Tool Call = 0%).
3. Phát hiện và ghi nhận sự kiện `MonitoringEvent` khi các thông số vượt ngưỡng an toàn.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F3-US3-T01** | **Cấu hình Tập trung Ngưỡng So sánh Biến cố (Monitoring Thresholds)**<br>- Khai báo các tham số giám sát trong `PolicyConfig`: `max_off_route_distance_km = 2.0`, `max_soc_drop_deviation_percent = 5.0`, `max_telemetry_silent_seconds = 60`.<br>- Hỗ trợ cập nhật tham số theo version mà không cần sửa code. | BE | F1-US2-T01 | Ngưỡng giám sát được quản lý tập trung, có thể cấu hình linh hoạt cho từng kịch bản thử nghiệm. | **S** |
| **F3-US3-T02** | **Xây dựng Monitoring Service so sánh Telemetry với Kế hoạch Hiện hành**<br>- Xây dựng `MonitoringService.evaluate_telemetry(trip_id, telemetry_event)`:<br>  1. Lấy `CONFIRMED` plan version của trip và danh sách tọa độ polyline.<br>  2. Tính toán khoảng cách vuông góc nhỏ nhất từ vị trí xe hiện tại đến polyline ($d_{\text{perp}}$).<br>  3. Tra cứu mức SOC kỳ vọng tại điểm chiếu trên tuyến ($SOC_{\text{expected}}$) và tính $\Delta SOC = SOC_{\text{expected}} - SOC_{\text{actual}}$.<br>  4. Nếu $d_{\text{perp}} > 2.0\text{ km} \rightarrow$ phát hiện sự kiện `ROUTE_DEVIATION`.<br>  5. Nếu $\Delta SOC > 5.0\% \rightarrow$ phát hiện sự kiện `SOC_UNDERPERFORMANCE`. | BE / Monitoring | F3-US1-T02, F3-US3-T01 | Thuật toán so sánh hình học và năng lượng chạy cực nhanh (< 10ms); phát hiện chính xác mọi biến cố. | **L** |
| **F3-US3-T03** | **Tạo Data Model & Persistence cho `MonitoringEvent`**<br>- Tạo bảng `monitoring_events`: `id` (UUID), `trip_id`, `event_type` (`ROUTE_DEVIATION, SOC_UNDERPERFORMANCE, STALE_TELEMETRY, STATION_DISRUPTED`), `severity` (`INFO, WARNING, CRITICAL`), `payload_json`, `created_at`.<br>- Xây dựng method lưu trữ event và cập nhật trạng thái cảnh báo trên bảng `trips`. | BE / DB | F3-US3-T02 | Sự kiện biến cố được lưu vết đầy đủ vào DB; phục vụ làm đầu vào cho luồng Tái lập kế hoạch (F4). | **M** |
| **F3-US3-T04** | **Triển khai Bộ lọc Chống Gọi Agent Bừa bãi (Zero Unnecessary Calls)**<br>- Thiết lập logic điều hướng: Khi `MonitoringService` không phát hiện biến cố (trạng thái `NORMAL`) $\rightarrow$ chỉ lưu telemetry, cập nhật tọa độ trên UI qua SSE/Polling, kết thúc quy trình.<br>- Tuyệt đối không khởi tạo LangGraph runtime hoặc gọi bất kỳ Tool nào khi xe đang đi đúng lộ trình và mức pin bình thường. | BE | F3-US3-T02, F3-US3-T03 | Đảm bảo tính tối ưu tài nguyên; không tạo ra các lượt tính toán thừa thãi khi không có biến cố. | **S** |
| **F3-US3-T05** | **Kiểm thử Kiểm chứng Tỷ lệ Gọi Agent Thừa (Unnecessary Call Rate Test)**<br>- Viết test tự động chạy mô phỏng 1 trip di chuyển bình thường trên 100km với 50 telemetry updates.<br>- Assert: Số lần gọi LangGraph Agent = 0; Số lần gọi Mapbox/OSRM Routing API = 0; Số lần gọi LLM = 0.<br>- Kiểm tra khi giả lập xe rẽ nhánh sai lộ trình 2.5km $\rightarrow$ phát ra đúng 1 `ROUTE_DEVIATION` event. | QA / BE | F3-US3-T02–F3-US3-T04 | Unnecessary tool call rate = 0% trên kịch bản chuẩn; hệ thống hoạt động đúng tôn chỉ event-driven. | **M** |

---

# Must 4 — Tái lập kế hoạch

> **Mục tiêu:** Tự động phát hiện biến cố chuyến đi (lệch tuyến, SOC tụt nhanh, trạm sạc mô phỏng hỏng), khởi tạo đề xuất kế hoạch mới từ vị trí hiện tại, và bắt buộc xin xác nhận lại từ chủ xe trước khi áp dụng.

---

## F4-US1 — Nhận plan mới khi đi lệch tuyến

**User Story:** Là chủ xe, tôi muốn nhận được đề xuất lộ trình và trạm sạc mới từ vị trí hiện tại khi tôi vô tình đi chệch khỏi tuyến đường đã định.

**Acceptance Criteria:**
1. Khi phát hiện sự kiện `ROUTE_DEVIATION`, hệ thống tự động khởi tạo `ReplanRequest` lấy vị trí GPS hiện tại làm Origin mới.
2. LangGraph Replan Workflow tính toán lại lộ trình từ vị trí hiện tại đến điểm đích gốc và lọc lại trạm sạc phù hợp.
3. Tạo bản ghi `PlanVersion n+1` ở trạng thái `PENDING`, kế hoạch cũ vẫn giữ nguyên trạng thái cho đến khi được duyệt.
4. Giao diện hiển thị lộ trình mới bên cạnh lộ trình cũ và nêu rõ lý do tái lập kế hoạch.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F4-US1-T01** | **Xây dựng Bộ xử lý Biến cố & Khởi tạo `ReplanRequest` khi Lệch tuyến**<br>- Xây dựng handler bắt sự kiện `ROUTE_DEVIATION` từ Monitoring Service.<br>- Tạo payload `ReplanRequest`: `trip_id`, `current_lat`, `current_lon`, `current_soc_percent`, `destination`, `base_plan_version_id`, `trigger_reason = ROUTE_DEVIATION`.<br>- Validate quyền sở hữu trip và kiểm tra không có tiến trình replan nào đang chạy đồng thời cho trip này. | BE / Monitoring | F3-US3-T03 | ReplanRequest được tạo chuẩn xác với tọa độ và mức pin thực tế tại điểm rẽ sai; sẵn sàng cho Agent. | **M** |
| **F4-US1-T02** | **Triển khai LangGraph Workflow cho Tái lập Kế hoạch từ Vị trí Hiện tại**<br>- Xây dựng đồ thị con `ReplanningGraph`: nhận `current_location` làm điểm xuất phát mới.<br>- Gọi Routing Tool lấy polyline mới từ vị trí hiện tại đến đích.<br>- Gọi Station Tool tìm các trạm sạc trên hành lang tuyến mới.<br>- Gọi Energy Tool tính toán lại mức tiêu hao pin bắt đầu từ `current_soc_percent`.<br>- Gọi Feasibility Tool kiểm tra an toàn (reserve SOC ≥ 15%). | Agent | F4-US1-T01, F1-US3-T06 | Workflow replan chạy độc lập, trơn tru; tái sử dụng các deterministic tools sẵn có; thời gian chạy < 10s. | **L** |
| **F4-US1-T03** | **Tạo và Lưu trữ Bản ghi `PlanVersion n+1` ở trạng thái `PENDING`**<br>- `TripService` nhận kết quả từ `ReplanningGraph`, tự động tăng số phiên bản `version_number = n + 1`.<br>- Lưu bản ghi vào bảng `plan_versions` với `status = PENDING`, gắn `trigger_event = ROUTE_DEVIATION` và lưu `base_version_id = n`.<br>- Tuyệt đối không thay đổi trạng thái của plan phiên bản $n$ (vẫn giữ `CONFIRMED` cho đến khi người dùng quyết định). | BE | F4-US1-T02, F2-US3-T01 | Kế hoạch mới được tạo an toàn; không tự ý áp đặt lên xe; đảm bảo nguyên tắc Human-in-the-loop. | **M** |
| **F4-US1-T04** | **Xây dựng UI Cảnh báo Lệch tuyến & Bản đồ So sánh Replan trên Frontend**<br>- Hiển thị Banner cảnh báo màu vàng cam trên màn hình giám sát: *"Phát hiện xe đã đi lệch lộ trình 2.5km. Hệ thống đã tính toán phương án mới từ vị trí hiện tại"*\.<br>- Bản đồ vẽ đồng thời 2 lộ trình: Lộ trình cũ (nét đứt mờ) và Lộ trình đề xuất mới (nét liền nổi bật).<br>- Hiển thị thanh công cụ Re-confirm tóm tắt sự thay đổi: Quãng đường mới, thời gian ETA mới, trạm dừng mới. | FE | F4-US1-T03, F2-US3-T04 | Giao diện cảnh báo kịp thời, trực quan; người lái xe dễ dàng quan sát sự khác biệt và phương án điều chỉnh. | **L** |
| **F4-US1-T05** | **Kiểm thử Tích hợp Luồng Tái lập Kế hoạch khi Đi Lệch Tuyến**<br>- Viết integration test: Giả lập xe đi từ Hà Nội đến Vinh, tại Phủ Lý xe rẽ nhầm hướng đi Nam Định.<br>- Kiểm tra hệ thống tự động phát hiện `ROUTE_DEVIATION`, gọi Replan Graph từ vị trí Nam Định, tạo ra PlanVersion v2 khả thi, giữ nguyên v1.<br>- Đo lường thời gian từ lúc nhận event đến khi có plan v2 < 10 giây. | QA / BE | F4-US1-T01–F4-US1-T04 | Kịch bản lệch tuyến hoạt động chính xác 100%; đạt yêu cầu hiệu năng p95 < 30s của PRD. | **L** |

---

## F4-US2 — Nhận cảnh báo khi SOC thấp hơn dự kiến

**User Story:** Là chủ xe, tôi muốn nhận được cảnh báo sớm và phương án sạc bổ sung khi pin xe tụt nhanh hơn dự tính (do thời tiết lạnh hoặc chở nặng).

**Acceptance Criteria:**
1. Phát hiện sự kiện `SOC_UNDERPERFORMANCE` khi mức pin thực tế thấp hơn mức dự kiến > 5%.
2. Đánh giá lại khả năng tiếp cận trạm sạc tiếp theo: nếu không đạt reserve SOC 15%, tự động tìm trạm sạc gần hơn.
3. Nếu không còn trạm sạc nào khả thi, trả về cảnh báo khẩn cấp `NoFeasiblePlan` kèm hướng dẫn giảm tốc độ/tiết kiệm điện.
4. Giao diện hiển thị biểu đồ pin thực tế tụt dốc và đề xuất phương án dừng sạc sớm.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F4-US2-T01** | **Xây dựng Logic Đánh giá Lại Khả năng Tiếp cận (Reachability Check)**<br>- Triển khai thuật toán kiểm tra khả năng tới trạm sạc kế tiếp:<br>  $\text{SOC}_{\text{arrival next}} = \text{SOC}_{\text{current}} - (d_{\text{to next station}} \times \text{consumption rate} / C_{\text{usable}}) \times 100\%$.<br>- Nếu $\text{SOC}_{\text{arrival next}} < 15.0\% \rightarrow$ đánh dấu trạm kế tiếp là không an toàn, kích hoạt tìm kiếm trạm sạc khẩn cấp nằm gần hơn trên tuyến. | Agent / Data | F3-US3-T02, F1-US3-T05 | Tính toán chính xác khả năng tiếp cận trạm sạc; phát hiện nguy cơ hết pin trước khi quá muộn. | **M** |
| **F4-US2-T02** | **Triển khai Replan Tìm Trạm sạc Thay thế Gần hơn**<br>- Khi trạm sạc ban đầu không còn khả thi: Station Tool mở rộng bán kính tìm kiếm các trạm sạc công suất thấp hơn hoặc trạm dừng chân có cổng sạc nằm trong tầm với an toàn ($\text{SOC}_{\text{arrival}} \ge 15\%$).<br>- Nếu tìm thấy trạm phù hợp $\rightarrow$ tạo `PlanVersion n+1` với trạm dừng mới.<br>- Nếu không có bất kỳ trạm nào đạt $\text{SOC} \ge 15\% \rightarrow$ trả về verdict `INFEASIBLE` và mã `SOC_CRITICAL_UNREACHABLE`. | Agent + BE | F4-US2-T01, F4-US1-T02 | Tìm ra giải pháp cứu nguy phù hợp nhất; hoặc cảnh báo trung thực khi không có phương án an toàn. | **M** |
| **F4-US2-T03** | **Xây dựng UI Cảnh báo Pin Tiêu hao Cao & Đề xuất Dừng sạc Sớm**<br>- Tạo React component `BatteryAlertModal` màu đỏ cảnh báo mức pin tụt nhanh.<br>- Hiển thị biểu đồ đối chiếu: Đường SOC kỳ vọng (màu xanh lá) vs Đường SOC thực tế (màu đỏ tụt nhanh).<br>- Hiển thị thông báo khuyến nghị: *"Pin tiêu hao nhanh hơn dự tính 7%. Cần dừng sạc sớm tại Trạm Sạc ABC (cách 12km) thay vì trạm dự kiến ban đầu"*. | FE | F4-US2-T02, F3-US1-T05 | Cảnh báo rõ ràng, dễ hiểu, giúp người lái đưa ra quyết định sạc bổ sung kịp thời để tránh cạn pin giữa đường. | **M** |
| **F4-US2-T04** | **Kiểm thử Kịch bản Pin Tụt Nhanh & Đánh giá Ranh giới An toàn**<br>- Viết test case: Xe đang chạy ở 40% pin, giả lập tiêu hao tăng vọt khiến pin giảm còn 22% (kỳ vọng là 30%), trạm sạc cũ cách 35km (cần 10% pin để tới $\rightarrow$ tới nơi còn 12% < 15%).<br>- Verify: Hệ thống từ chối tiếp tục lộ trình cũ, tự động replan chọn trạm sạc khác cách 15km (tới nơi còn 17% > 15%), tạo PlanVersion v2 hợp lệ. | QA / BE | F4-US2-T01–F4-US2-T03 | Test case pass 100%; chứng minh khả năng bảo vệ chủ xe khi gặp điều kiện tiêu hao bất lợi. | **M** |

---

## F4-US3 — Có phương án thay thế khi trạm mô phỏng không khả dụng

**User Story:** Là chủ xe, tôi muốn hệ thống tự động tìm trạm sạc thay thế khi trạm sạc dự kiến ban đầu bị mô phỏng sự cố (quá tải, mất điện hoặc ngừng hoạt động).

**Acceptance Criteria:**
1. Bộ giả lập (Simulator) có khả năng phát sự kiện `SIMULATED_STATION_UNAVAILABLE` cho một trạm sạc cụ thể (gắn nhãn `SIMULATED`).
2. Station Tool tự động đưa trạm bị sự cố vào Blacklist và tìm kiếm các trạm sạc ứng viên thay thế trên hành lang tuyến.
3. Tạo phương án kế hoạch mới thay thế trạm hỏng; nếu không có trạm thay thế, trả về thông báo `NoFeasiblePlan`.
4. Giao diện gắn nhãn rõ "Sự kiện mô phỏng" để người dùng hiểu đây là tình huống diễn tập.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F4-US3-T01** | **Mở rộng Simulator phát sự kiện Trạm sạc Hỏng (`SIMULATED_STATION_UNAVAILABLE`)**<br>- Xây dựng module phát sự kiện trong Simulator: cho phép chỉ định `station_id` bị hỏng tại thời điểm $T$ trong kịch bản.<br>- Gửi sự kiện `SIMULATED_STATION_UNAVAILABLE` đến Monitoring Service kèm nhãn `source = SIMULATED`.<br>- Cung cấp API test `POST /api/v1/simulator/stations/{id}/disrupt` để trigger sự cố phục vụ demo. | Simulator + BE | F3-US1-T04 | Simulator phát sự kiện trạm hỏng mượt mà; gắn nhãn mô phỏng chuẩn xác; dễ dàng kích hoạt khi demo. | **M** |
| **F4-US3-T02** | **Cập nhật Station Tool: Loại bỏ Trạm Sự cố & Tìm Ứng viên Thay thế**<br>- Cập nhật `StationTool`: nhận tham số `excluded_station_ids` chứa danh sách trạm bị sự cố.<br>- Lọc bỏ trạm hỏng khỏi danh sách ứng viên; truy vấn trạm sạc lân cận tiếp theo trên tuyến đáp ứng chuẩn cổng CCS2 và còn khả năng tiếp cận.<br>- Nếu tìm được trạm thay thế $\rightarrow$ đưa vào quy trình tính toán năng lượng và feasibility. | Agent / BE | F1-US3-T04, F4-US3-T01 | Trạm hỏng bị loại trừ triệt để; tìm kiếm trạm thay thế tối ưu nhất trên hành lang tuyến còn lại. | **M** |
| **F4-US3-T03** | **LangGraph Replan Luồng Sự cố Trạm & Xử lý Trạm Không Khả dụng**<br>- Điều phối chuỗi Replan khi có biến cố trạm sạc: `Re-route (nếu cần đổi đường rẽ) → Station Tool (Blacklist trạm hỏng) → Energy Tool → Feasibility Check`.<br>- Tạo `PlanVersion n+1` với trạm sạc mới.<br>- Trường hợp không còn trạm nào thay thế được $\rightarrow$ trả về `NoFeasiblePlan` kèm mã `ALL_STATIONS_UNAVAILABLE`. | Agent + BE | F4-US3-T02, F4-US1-T02 | Hệ thống xử lý linh hoạt: có trạm thay thế thì đề xuất phương án mới, không có thì cảnh báo trung thực. | **L** |
| **F4-US3-T04** | **Xây dựng UI Thông báo Trạm Hỏng & Đề xuất Trạm Thay thế trên Frontend**<br>- Hiển thị Banner màu tím (nhãn mô phỏng): *"Trạm Sạc VinFast Tĩnh Gia tạm thời gián đoạn (Sự kiện mô phỏng). Hệ thống đề xuất đổi sang Trạm Sạc EV One cách 8km"*\.<br>- Đánh dấu icon trạm cũ bị gạch chéo đỏ trên bản đồ, icon trạm mới nhấp nháy màu xanh lá.<br>- Bảng so sánh thời gian sạc và mức chênh lệch thời gian đến đích. | FE | F4-US3-T03, F3-US2-T03 | Giao diện rõ ràng, minh bạch nguồn gốc mô phỏng; người dùng dễ dàng chuyển hướng sang trạm mới. | **M** |
| **F4-US3-T05** | **Kiểm thử Tự động Kịch bản Gián đoạn Trạm Sạc (Station Disruption Test)**<br>- Viết test suite: Trip đã confirm với điểm dừng tại Trạm A; Simulator phát tín hiệu Trạm A hỏng.<br>- Verify: Hệ thống tự động kích hoạt replan, loại bỏ Trạm A, chọn Trạm B thay thế, tạo PlanVersion v2 với đầy đủ giải thích và provenance `SIMULATED`.<br>- Test kịch bản không có trạm thay thế $\rightarrow$ hệ thống trả về đúng `NoFeasiblePlan`. | QA / Simulator | F4-US3-T01–F4-US3-T04 | Kịch bản trạm sạc hỏng chạy ổn định, lặp lại được 100% kết quả trong các lần test. | **M** |

---

## F4-US4 — Xác nhận lại trước khi plan mới có hiệu lực

**User Story:** Là chủ xe, tôi muốn chủ động xem xét và xác nhận lại phương án kế hoạch mới trước khi nó chính thức thay thế kế hoạch cũ.

**Acceptance Criteria:**
1. Tái sử dụng hợp đồng Confirm / Reject cho phiên bản kế hoạch mới (`PlanVersion n+1`).
2. Khi chủ xe bấm Confirm: `PlanVersion n+1` chuyển thành `CONFIRMED`, phiên bản cũ chuyển thành `SUPERSEDED`.
3. Khi chủ xe bấm Reject: nếu kế hoạch cũ vẫn còn an toàn thì giữ nguyên kế hoạch cũ; nếu kế hoạch cũ đã mất an toàn (hết pin/quá xa), chuyển kế hoạch cũ sang trạng thái `INVALIDATED_BY_SAFETY`.
4. Giao diện hiển thị cảnh báo nghiêm trọng nếu người dùng từ chối phương án an toàn duy nhất.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F4-US4-T01** | **Tái sử dụng Contract & Xây dựng Nghiệp vụ Xác nhận lại (Re-confirmation)**<br>- Tái sử dụng endpoint `POST /api/v1/plans/{id}/confirm` cho `PlanVersion n+1`.<br>- Khi confirm thành công: Cập nhật `trip.current_plan_version_id = n+1`, chuyển version $n$ sang `SUPERSEDED`, chuyển $n+1$ sang `CONFIRMED`.<br>- Cập nhật lại lộ trình và trạm sạc mục tiêu trên Monitoring Service. | BE | F2-US2-T02, F4-US1-T03 | Quy trình xác nhận lại nhất quán; chuyển giao trạng thái giữa 2 phiên bản kế hoạch an toàn tuyệt đối. | **S** |
| **F4-US4-T02** | **Xử lý Logic Kế hoạch Cũ Mất An toàn (`INVALIDATED_BY_SAFETY`) khi Reject**<br>- Triển khai logic nghiệp vụ khi chủ xe bấm Reject `PlanVersion n+1`:<br>  1. Kiểm tra tính khả thi của kế hoạch cũ (version $n$) từ vị trí và SOC hiện tại.<br>  2. Nếu kế hoạch cũ vẫn khả thi $\rightarrow$ giữ nguyên version $n$ làm `CONFIRMED`.<br>  3. Nếu kế hoạch cũ đã vi phạm an toàn (SOC < 15% hoặc không thể quay lại tuyến) $\rightarrow$ chuyển trạng thái version $n$ thành `INVALIDATED_BY_SAFETY` và cập nhật `trip.status = INFEASIBLE_STATE`. | BE | F4-US4-T01, F1-US4-T02 | Xử lý chặt chẽ logic an toàn; không cho phép hệ thống duy trì một kế hoạch cũ nguy hiểm khi đã bị từ chối kế hoạch mới. | **M** |
| **F4-US4-T03** | **Xây dựng UI Modal Re-confirm & Cảnh báo Kế hoạch bị Vô hiệu hóa**<br>- Tạo React component `ReconfirmModal` hiển thị so sánh chi tiết giữa kế hoạch hiện hành và kế hoạch tái lập.<br>- Nút bấm "Chấp nhận kế hoạch mới" và "Giữ kế hoạch cũ".<br>- Nếu kế hoạch cũ đã rơi vào vùng nguy hiểm: nút "Giữ kế hoạch cũ" sẽ hiển thị kèm cảnh báo đỏ rực: *"Cảnh báo: Lộ trình cũ không còn đủ pin để tới trạm sạc. Bạn có chắc chắn muốn từ chối phương án an toàn?"*. | FE | F4-US4-T01, F4-US4-T02 | Giao diện cảnh báo trách nhiệm rõ ràng; đảm bảo người lái xe nhận thức đầy đủ rủi ro trước khi quyết định. | **M** |
| **F4-US4-T04** | **Kiểm thử Toàn diện Quy trình Xác nhận lại & Xử lý Trạng thái Kế hoạch**<br>- Viết integration test cho 2 nhánh nghiệp vụ:<br>  1. Nhánh 1: Replan khi đi lệch đường nhỏ, chủ xe reject replan $\rightarrow$ Kế hoạch cũ vẫn `CONFIRMED` an toàn.<br>  2. Nhánh 2: Replan khi pin sắp cạn, chủ xe reject replan $\rightarrow$ Kế hoạch cũ chuyển thành `INVALIDATED_BY_SAFETY`, trip cảnh báo không an toàn.<br>- Assert trạng thái và audit log được ghi nhận chính xác 100%. | QA / BE | F4-US4-T01–F4-US4-T03 | Quy trình xác nhận lại đạt chuẩn an toàn cao nhất; không còn kịch bản lỗi trạng thái chưa được kiểm thử. | **M** |

---

# Should — Không gian hỗ trợ chuyến đi dạng chỉ đọc

> **Mục tiêu:** Cung cấp giao diện tra cứu và theo dõi trạng thái chuyến đi dành riêng cho nhân viên hỗ trợ khi được chủ xe cấp quyền, phục vụ việc giải thích và hướng dẫn mà không thể can thiệp hay sửa đổi kế hoạch của chủ xe.

---

## F5-US1 — Xem trạng thái trip được cấp quyền

**User Story:** Là nhân viên hỗ trợ, tôi muốn xem trạng thái vị trí, mức pin, lộ trình và các cảnh báo của chuyến đi khi được chủ xe cấp mã ủy quyền để hỗ trợ giải đáp thắc mắc.

**Acceptance Criteria:**
1. Thiết kế mô hình cấp quyền `SupportGrant` có thời hạn (`expires_at`) và phạm vi chỉ đọc (`scope = READ_ONLY`).
2. Endpoint chuyên biệt `GET /api/v1/support/trips/{id}` tổng hợp toàn bộ trạng thái chuyến đi.
3. Chặn 100% các thao tác mang tính ghi (POST, PUT, DELETE) từ tài khoản hỗ trợ viên (`403 Forbidden`).
4. Giao diện Web Support Workspace trực quan, tìm kiếm trip theo mã và xem trạng thái theo thời gian thực.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F5-US1-T01** | **Tạo Data Model & Migration cho Quyền Hỗ trợ (`SupportGrant`)**<br>- Tạo bảng `support_grants`: `id` (UUID), `trip_id`, `grant_code` (mã 6 ký tự ngẫu nhiên), `support_user_id` (nullable khi chưa claim), `granted_by` (user_id chủ xe), `expires_at` (mặc định 24h sau khi tạo), `scope` (`READ_ONLY`), `created_at`.<br>- Endpoint cho chủ xe tạo mã cấp quyền: `POST /api/v1/trips/{id}/support-grant`. | BE / DB | F1-US1-T02 | Model cấp quyền hoàn chỉnh; mã ủy quyền bảo mật, có thời hạn rõ ràng. | **M** |
| **F5-US1-T02** | **Xây dựng Authorization Policy & Middleware Chặn Ghi cho Support Role**<br>- Xây dựng middleware `SupportAuthorizationMiddleware`:<br>  1. Xác thực token hỗ trợ viên và kiểm tra `SupportGrant` còn hiệu lực (`now() < expires_at`).<br>  2. Áp dụng chính sách RBAC: Hỗ trợ viên chỉ được phép gọi các endpoint bắt đầu bằng `/api/v1/support/*`.<br>  3. Mọi request cố tình gọi sang endpoint ghi (`/plans/confirm`, `/plans/reject`, `/replans`, `/telemetry`) lập tức bị chặn và trả về HTTP 403 `FORBIDDEN_WRITE_ACTION`. | BE | F5-US1-T01 | Phân quyền bảo mật tuyệt đối; hỗ trợ viên hoàn toàn không có khả năng can thiệp sửa đổi dữ liệu chuyến đi. | **M** |
| **F5-US1-T03** | **Xây dựng Read-only API `GET /api/v1/support/trips/{id}` & Audit Logging**<br>- Triển khai endpoint chuyên biệt cho support: trả về bức tranh tổng thể gồm vị trí GPS mới nhất, mức SOC, lộ trình đã duyệt, danh sách trạm sạc, cảnh báo biến cố hiện tại, và provenance nhãn dữ liệu.<br>- Ghi nhận bản ghi `audit_logs` mỗi lần hỗ trợ viên mở xem chi tiết chuyến đi. | BE | F5-US1-T02, F3-US1-T02 | API trả về đầy đủ dữ liệu tổng quan cho hỗ trợ viên; lưu vết kiểm toán rõ ràng. | **M** |
| **F5-US1-T04** | **Xây dựng Giao diện Web Support Workspace Dạng Chỉ đọc trên Frontend**<br>- Tạo trang `/support`: Ô nhập mã `grant_code` hoặc `trip_id` để tra cứu chuyến đi.<br>- Màn hình Dashboard hỗ trợ viên: Bản đồ lộ trình và vị trí xe, đồng hồ đo mức pin, bảng cảnh báo biến cố, và danh sách các trạm dừng sạc.<br>- Giao diện được thiết kế độc lập, **hoàn toàn loại bỏ** các nút bấm thao tác (không có nút Confirm, Reject, Replan hay điều khiển). | FE | F5-US1-T03 | Dashboard hỗ trợ viên chuyên nghiệp, tải nhanh, trực quan; phục vụ tra cứu thông tin nhanh chóng. | **L** |

---

## F5-US2 — Xem lý do plan/replan để giải thích cho chủ xe

**User Story:** Là nhân viên hỗ trợ, tôi muốn xem toàn bộ cây giải thích và lịch sử các lần tính toán lại kế hoạch để giải thích rõ ràng cho chủ xe khi họ gọi điện hỏi.

**Acceptance Criteria:**
1. Hỗ trợ viên có thể xem chi tiết lý do hệ thống lựa chọn từng trạm sạc và lý do loại trừ các trạm khác.
2. Hỗ trợ viên có thể xem lịch sử các lần phát hiện biến cố (lệch tuyến, pin tụt) và so sánh giữa các phiên bản kế hoạch.
3. Tái sử dụng module giải thích có sẵn, không nhân đôi logic nghiệp vụ.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F5-US2-T01** | **Tái sử dụng API Explanation & Plan History cho Support Endpoint**<br>- Tích hợp dữ liệu từ `ExplanationReferences` và `PlanHistory` vào payload trả về của `/api/v1/support/trips/{id}`.<br>- Trả về danh sách câu hỏi - đáp nhanh: Lý do chọn trạm tối ưu, lý do loại các trạm lân cận, lý do kích hoạt replan (nếu có). | BE | F2-US1-T01, F2-US3-T02, F5-US1-T03 | Cung cấp đầy đủ thông tin giải thích chuyên sâu cho hỗ trợ viên mà không tốn công viết lại logic mới. | **S** |
| **F5-US2-T02** | **Xây dựng UI Panel Tra cứu Lý do Dành cho Hỗ trợ viên**<br>- Tạo React component `SupportExplanationViewer` trong Support Workspace.<br>- Hiển thị khung "Tóm tắt tình huống tư vấn": hiển thị nhanh lý do vì sao hệ thống đề xuất dừng sạc tại trạm này, mức pin an toàn dự kiến và các khuyến cáo cho chủ xe.<br>- Timeline hiển thị chi tiết các lần replan giúp nhân viên nắm bắt nhanh bối cảnh khi chủ xe liên hệ. | FE | F5-US2-T01, F5-US1-T04 | Giao diện hỗ trợ tư vấn cực kỳ tiện lợi; giúp nhân viên hỗ trợ giải đáp thắc mắc của chủ xe trong vòng 30 giây. | **M** |

---

## F5-US3 — Dữ liệu không bị lộ cho người không được cấp quyền

**User Story:** Là chủ xe, tôi muốn đảm bảo dữ liệu lộ trình và vị trí di chuyển của tôi không bị rò rỉ hoặc bị người khác xem lén khi chưa có sự cho phép của tôi.

**Acceptance Criteria:**
1. Truy cập vào trip mà không có `SupportGrant` hợp lệ hoặc grant đã hết hạn phải bị từ chối ngay lập tức (`404 Not Found` hoặc `403 Forbidden`).
2. Chống quét mã chuyến đi (Anti-enumeration): không phân biệt thông báo lỗi giữa trip không tồn tại và trip không được cấp quyền để tránh lộ thông tin.
3. Bảo vệ dữ liệu nhạy cảm: không ghi log vị trí chi tiết của chủ xe vào log hệ thống công khai.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **F5-US3-T01** | **Xây dựng Bộ Kiểm thử Bảo mật Phân quyền Support (Security Matrix)**<br>- Viết security test suite:<br>  1. Thử truy cập với mã grant sai $\rightarrow$ trả về 404 Not Found.<br>  2. Thử truy cập với mã grant đã hết hạn $\rightarrow$ trả về 403 Forbidden kèm mã `GRANT_EXPIRED`.<br>  3. Thử dùng token hỗ trợ viên gọi lệnh `POST /plans/123/confirm` $\rightarrow$ chặn 100% với 403 Forbidden.<br>  4. Thử truy cập chéo giữa 2 trip khác nhau với 1 grant $\rightarrow$ bị chặn 100%. | QA / Security | F5-US1-T02, F5-US1-T03 | Toàn bộ các lỗ hổng phân quyền được kiểm tra và chặn đứng; bảo đảm an toàn dữ liệu khách hàng. | **M** |
| **F5-US3-T02** | **Cơ chế Chống Quét mã Chuyến đi & Ẩn Dữ liệu Nhạy cảm trong Log**<br>- Áp dụng nguyên tắc Anti-enumeration: khi người dùng tra cứu trip ID ngẫu nhiên không thuộc quyền sở hữu, API luôn trả về `404 Not Found` đồng nhất.<br>- Cấu hình log filter trong logging middleware: tự động ẩn (masking) tọa độ GPS chi tiết, token và thông tin định danh cá nhân trong log file. | BE / Security | F5-US3-T01, X-T03 | Hệ thống đạt tiêu chuẩn bảo mật dữ liệu riêng tư, không rò rỉ metadata hay lịch sử di chuyển của chủ xe. | **M** |

---

# Cross-cutting Tasks (Kiến trúc nền tảng, Observability, Benchmark & CI/CD)

> **Mục tiêu:** Thiết lập khung làm việc chung, chuẩn hóa giao tiếp contract-first, xây dựng hệ thống giám sát hoạt động Agent, bộ kiểm thử đánh giá chuẩn và hạ tầng triển khai.

| Task ID | Tên Task & Chi tiết Kỹ thuật | Owner role | Phụ thuộc | Tiêu chí hoàn thành (Output / Done) | Size |
|---|---|---|---|---|:---:|
| **X-T01** | **Khởi tạo Cấu trúc Dự án Modular Monolith & Môi trường Phát triển**<br>- Cấu trúc source code rõ ràng: `/apps/web` (React + Vite + TypeScript), `/apps/api` (FastAPI + SQLAlchemy + Pydantic), `/packages/agent` (LangGraph + LangChain Tools), `/packages/contracts` (OpenAPI Schemas).<br>- Cấu hình Docker Compose môi trường dev: FastAPI API, PostgreSQL 16 (kèm PostGIS), Redis (cache), OSRM routing local server.<br>- Thiết lập bộ công cụ chuẩn hóa mã nguồn: ESLint, Prettier, Ruff, Black, Mypy. | Tech Lead / DevOps | — | Môi trường dev dựng lên dễ dàng chỉ với 1 lệnh `docker compose up`; phân tầng sạch sẽ, rõ ranh giới module. | **M** |
| **X-T02** | **Đóng băng Contract OpenAPI v1.0 & Tạo Mock Data Server**<br>- Hoàn thiện và freeze file đặc tả `openapi.yaml` cho toàn bộ các endpoint (Trip, Plan, Telemetry, Replan, Support).<br>- Thiết lập mock server (Prism hoặc MirageJS) và bộ generator sinh TypeScript Client SDK để FE và BE có thể phát triển độc lập song song ngay từ ngày đầu. | Tech Lead + FE + BE | X-T01 | Contract OpenAPI v1.0 đóng băng; FE phát triển với mock data mà không bị phụ thuộc vào tiến độ của BE. | **M** |
| **X-T03** | **Chuẩn hóa Error Handling, Trace ID & Agent Observability**<br>- Xây dựng middleware gán `trace_id` (UUIDv4) xuyên suốt cho mọi HTTP request và truyền vào LangGraph context.<br>- Chuẩn hóa định dạng lỗi trả về: `{ error_code, message, details, trace_id, timestamp }` cho các lỗi `VALIDATION_ERROR`, `AMBIGUOUS_LOCATION`, `INFEASIBLE_PLAN`, `PROVIDER_ERROR`, `VERSION_CONFLICT`.<br>- Xây dựng bảng `agent_runs` và `tool_runs` ghi nhận log cấu trúc cho từng bước chạy của Agent (tool latency, input params, output summary, error message). | BE / Agent | X-T01, X-T02 | Toàn bộ hệ thống có format lỗi đồng nhất; trace_id xuyên suốt từ UI đến DB; đo lường chính xác hiệu năng Agent. | **L** |
| **X-T04** | **Xây dựng Bộ dữ liệu 20 Smoke Cases & Automated Eval Runner**<br>- Xây dựng bộ dataset 20 test case chuẩn hóa đại diện cho các nhóm:<br>  - Happy path (3 cases: đi thẳng, 1 trạm, nhiều trạm).<br>  - Boundary (3 cases: SOC vừa đủ 15%, đúng 15.0%, detour sát ngưỡng).<br>  - Invalid input (3 cases: SOC ngoài khoảng, thiếu vị trí, connector lạ).<br>  - Safety & Fail-closed (4 cases: dưới 15%, sai connector, stale snapshot, provider lỗi).<br>  - Replanning (3 cases: lệch tuyến, pin tụt nhanh, trạm sạc hỏng).<br>  - Confirmation (1 case: chưa confirm thì plan chưa áp dụng).<br>  - Explanation (3 cases: grounding references, template fallback, anti-hallucination).<br>- Viết Eval Runner tự động đo lường: Feasibility Accuracy (≥ 95%), Infeasible Recall (100%), Unnecessary Tool Calls (≤ 10%). | QA + Agent | X-T02 | Bộ smoke cases chạy tự động sau mỗi bản build; xuất báo cáo metric rõ ràng phục vụ nghiệm thu chất lượng. | **L** |
| **X-T05** | **Thiết lập CI/CD Pipeline & Hạ tầng Triển khai Demo**<br>- Xây dựng GitHub Actions workflow: tự động chạy lint, type check, unit test và integration test trên mỗi Pull Request.<br>- Cấu hình tự động deploy Frontend lên Vercel và Backend API + PostgreSQL lên Render/Fly.io khi merge vào nhánh `main`.<br>- Thiết lập endpoint `/health` kiểm tra kết nối DB và trạng thái dịch vụ. | DevOps | X-T01, X-T04 | CI/CD tự động hóa 100%; môi trường demo cloud luôn hoạt động ổn định và sẵn sàng cho pilot test. | **M** |
| **X-T06** | **Soạn Kịch bản Demo Pilot & Rà soát Tính nhất quán Tài liệu**<br>- Soạn kịch bản trình diễn (Demo Script) chi tiết theo 5 bước: (1) Nhập trip & công bố giả định 15% $\rightarrow$ (2) Nhận đề xuất & giải thích có căn cứ $\rightarrow$ (3) Xác nhận kế hoạch $\rightarrow$ (4) Theo dõi xe di chuyển giả lập & kích hoạt biến cố lệch đường/trạm hỏng $\rightarrow$ (5) Tái lập kế hoạch & xác nhận lại.<br>- Đảm bảo phân định rõ nhãn thật và mô phỏng trên bản demo; rà soát tính nhất quán 100% giữa PRD v3.0, Tech Architecture v3.1, OpenAPI v1.0 và Implementation Backlog v3.1. | PO + Tech Lead + QA | X-T05 | Buổi demo chạy trơn tru theo kịch bản chuẩn; không nói quá năng lực hệ thống; tài liệu dự án hoàn toàn đồng nhất. | **S** |

---

## 3. Quy chuẩn Chất lượng (Quality Gates)

### Definition of Ready (DoR) — Điều kiện để Task được đưa vào Sprint / Thực hiện:
- [x] Có User Story và Acceptance Criteria rõ ràng, không mâu thuẫn với PRD.
- [x] Có Contract (OpenAPI schema hoặc Interface typed) được thống nhất.
- [x] Có Role phụ trách chính (Owner) và xác định rõ các Task phụ thuộc (Dependency).
- [x] Đã xác định tiêu chí hoàn thành kiểm tra được (Testable Output / Done).
- [x] Đã ước lượng kích thước hợp lý (S / M / L).
- [x] Không còn khúc mắc kỹ thuật (Open Questions) chưa được giải đáp.

### Definition of Done (DoD) — Điều kiện để Task được coi là Hoàn thành:
- [x] Source code được viết sạch, tuân thủ lint/typing và được review thông qua Pull Request.
- [x] Có đầy đủ Unit Test / Integration Test tương ứng và toàn bộ test suite đều Pass.
- [x] Tương thích 100% với đặc tả `openapi.yaml`, không gây breaking change.
- [x] Có ghi nhận log cấu trúc và `trace_id` phục vụ giám sát và gỡ lỗi.
- [x] Tài liệu kỹ thuật, API docs và hướng dẫn sử dụng được cập nhật đồng bộ.
- [x] Tính năng đã được kiểm chứng hoạt động thực tế trên môi trường demo/staging.
