# P-210 AI EV Agent

Kho lưu trữ (repository) này là vertical slice hoàn chỉnh cho bài toán lập kế hoạch chuyến đi xe điện đường dài theo bộ tài liệu thiết kế trong thư mục `docs/`. Trạng thái hiện tại đã hoàn thành và kiểm thử toàn diện các User Story **`F1-US1`**, **`F1-US2`** và **`F1-US3`**: người dùng tạo `Trip` ở trạng thái `DRAFT`, xem snapshot giả định được version hóa, kích hoạt Agent điều phối lập kế hoạch lộ trình, lọc trạm sạc khả dụng, tính toán tiêu hao pin tất định và hiển thị trực quan bản đồ lộ trình, biểu đồ diễn tiến pin cùng danh sách trạm sạc trên giao diện Web.

Tài liệu `README.md` này giúp đồng đội khi clone repo có thể nắm bắt nhanh: kiến trúc tổng thể, những phần đã hoàn thành, cách chạy backend/frontend và các tài liệu cần tham chiếu trước khi phát triển tiếp.

### Video demo

[Xem video demo trên YouTube](https://youtu.be/xjzdH6SZfS0)

[Xem báo cáo kết quả 5 test](eval/results/report.md)

---

## 1. Mục tiêu sản phẩm

Theo [docs/PRD_AI_EV_AGENT_v3.0.md](docs/PRD_AI_EV_AGENT_v3.0.md), MVP hướng tới luồng nghiệp vụ khép kín:

$$\text{Nhập trip} \rightarrow \text{Geocode/Validate} \rightarrow \text{Tạo Trip DRAFT} \rightarrow \text{Lập kế hoạch} \rightarrow \text{Giải thích} \rightarrow \text{Xác nhận} \rightarrow \text{Theo dõi} \rightarrow \text{Replan}$$

### 🟢 Những phần ĐÃ HOÀN THÀNH (Đến hết F1-US3):

- **API Trip Intake:** `POST /api/v1/trips` & `GET /api/v1/trips/{trip_id}`.
- **Tài khoản & xe cá nhân:** đăng ký/đăng nhập bằng access token có thể thu hồi; bước “Xe của tôi” liên kết tài khoản với profile VinFast đã xác minh.
- **Geocoding & Xử lý địa chỉ:** Geocoding địa chỉ text, trả về `AMBIGUOUS_LOCATION` kèm danh sách gợi ý ứng viên nếu địa chỉ không rõ ràng để người dùng chọn lại.
- **Pydantic Validation:** Kiểm tra mức pin ban đầu `initial_soc_percent` bắt buộc trong khoảng `[1, 100]`.
- **Quản lý Giả định & Policy:** `GET /api/v1/config/assumptions`, quản lý policy tập trung (`reserve_soc_percent = 15%`), lưu `AssumptionSnapshot` bất biến kèm trip và plan.
- **API Lập kế hoạch (Planning):** `POST /api/v1/trips/{trip_id}/plans` & `GET /api/v1/trips/{trip_id}/plans`.
- **Bộ 3 Deterministic Tools cho F1-US3:**
  1. `RoutingProvider`: Định tuyến Goong Directions / InMemory trả về polyline hình học, khoảng cách (km) và thời gian (phút).
  2. `StationDataService`: Lọc trạm sạc trong hành lang tuyến (bounding corridor buffer 15km, detour $\le 15$ phút), lọc cổng sạc tương thích (CCS2 cho Xe X) và phân loại độ tươi mới (`FRESH` / `STALE`).
  3. `EnergyTool`: Tính toán mô hình vật lý tất định mức tiêu thụ năng lượng ($E_{\text{seg}} = d \times \text{consumption rate} \times k_{\text{temp}} \times k_{\text{payload}}$), mức pin tụt dọc tuyến $SOC_{\text{arrival}}$ và thời gian sạc lên 80%.
- **LangGraph Planning Orchestrator:** Điều phối tuần tự chuỗi tool: `Routing` $\rightarrow$ `Station & Energy Filter` $\rightarrow$ `PlanProposal Generation`.
- **Lưu trữ phiên bản kế hoạch:** Lưu `PlanVersionRecord` ở trạng thái `PENDING` vào bảng `plan_versions` (lưu trữ đồng bộ trong trường `assumptions` dạng JSONB trên PostgreSQL/Supabase và Text trên SQLite).
- **Giao diện Web Frontend:**
  - Goong Places Autocomplete cho điểm đầu/đích, hỗ trợ đổi chiều và GPS hiện tại.
  - Modal chọn lại khi gặp địa chỉ mơ hồ.
  - `AssumptionPanel`: Hiển thị Reserve SOC 15%, nhiệt độ 25°C, tải trọng 150kg, badge "Pilot Assumption" và cảnh báo an toàn.
  - `TripPlanMap`: Bản đồ tuyến đường vẽ polyline, điểm xuất phát, điểm đến và các marker trạm sạc đề xuất.
  - `SocChart`: Biểu đồ diễn tiến pin (SOC % vs km) kèm đường kẻ ngang nét đứt màu đỏ thể hiện ngưỡng an toàn tối thiểu 15%.
  - `ChargingStopList`: Danh sách card chi tiết từng trạm sạc dừng chân (Pin đến, pin rời, thời gian sạc, công suất kW).

### 🟡 Những phần tạm thời chưa triển khai (Dành cho các phase tiếp theo):

- **F1-US4:** Xây dựng bộ quy tắc từ chối toàn diện khi vi phạm an toàn (`NoFeasiblePlan` / `INFEASIBLE`).
- **F1-US5 / Must 2:** `POST /api/v1/trips/{trip_id}/plans/{version}/confirm` — Xác nhận kế hoạch Human-in-the-loop để chuyển trạng thái từ `PENDING` sang `CONFIRMED`.
- **Must 3 & Must 4:** Giám sát GPS/SOC thời gian thực và tự động kích hoạt replanning khi phát hiện lệch tuyến hoặc pin tụt nhanh.
- **Should:** Không gian hỗ trợ viên Read-only (`support workspace`).

---

## 2. Tài liệu cần đọc trước

Thứ tự ưu tiên nên đọc để nắm đúng ngữ cảnh dự án:

1. [docs/PRD_AI_EV_AGENT_v3.0.md](docs/PRD_AI_EV_AGENT_v3.0.md)
2. [docs/TECHNICAL_ARCHITECTURE_AI_EV_AGENT_v3.1.md](docs/TECHNICAL_ARCHITECTURE_AI_EV_AGENT_v3.1.md)
3. [docs/INTERFACE_DESIGN_AI_EV_AGENT_v1.0.md](docs/INTERFACE_DESIGN_AI_EV_AGENT_v1.0.md)
4. [docs/IMPLEMENTATION_BACKLOG_AI_EV_AGENT_v3.0.md](docs/IMPLEMENTATION_BACKLOG_AI_EV_AGENT_v3.0.md)

Nếu cần đọc code nhanh để tiếp tục phát triển:

- [src/apps/api/routes/trips.py](src/apps/api/routes/trips.py)
- [src/packages/contracts/trips.py](src/packages/contracts/trips.py)
- [src/packages/core/trips/application/service.py](src/packages/core/trips/application/service.py)
- [src/packages/agent/planning/nodes/planning_nodes.py](src/packages/agent/planning/nodes/planning_nodes.py)
- [src/apps/web/src/App.tsx](src/apps/web/src/App.tsx)

---

## 3. Kiến trúc mã nguồn hiện tại

Dự án sử dụng mô hình Monorepo module hóa sạch sẽ: `src/apps/` (các ứng dụng đầu cuối) và `src/packages/` (các thư viện và domain core).

```text
D:\P-210
├─ src/
│  ├─ apps/
│  │  ├─ api/                 # FastAPI backend (Routes, dependencies, middleware)
│  │  └─ web/                 # React/Vite frontend (Form, Map, SOC Chart, Panels)
│  └─ packages/
│     ├─ core/
│     │  ├─ trips/            # Domain, Service, Repository, Geocoding, Energy, Routing, Stations
│     │  ├─ policies/         # PolicyConfigService + Assumption snapshot
│     │  ├─ monitoring/       # Scaffold cho Must 3 (Giám sát thời gian thực)
│     │  ├─ simulator/        # Scaffold cho Telemetry Simulator
│     │  └─ support/          # Scaffold cho Support Workspace
│     ├─ agent/
│     │  └─ planning/         # LangGraph Orchestrator (StateGraph, Nodes, Tools)
│     └─ contracts/           # Public schemas chia sẻ (Pydantic / TypeScript types)
├─ migrations/                # Alembic migrations
├─ tests/                     # Pytest suite (API tests, Planning tests, Boundary checks)
├─ docs/                      # Tài liệu thiết kế kỹ thuật và sản phẩm
├─ scripts/                   # Script launcher và Git pre-push hook AI Log
└─ build/
   └─ web/                    # Production build output của Frontend
```

---

## 4. Ánh xạ giữa Mã nguồn và Nghiệp vụ (Business Mapping)

### 🔹 Backend (`src/apps/api` & `src/packages/core`)
1. `POST /api/v1/trips`: Tiếp nhận yêu cầu, geocode địa chỉ, validate pin $\ge 1\%$, chụp snapshot giả định và lưu bản ghi `Trip` ở trạng thái `DRAFT`.
2. `POST /api/v1/trips/{trip_id}/plans`: Kích hoạt Agent Orchestrator:
   - Gọi `RoutingProvider` lấy polyline hình học, quãng đường và thời gian.
   - Gọi `StationDataService` lọc trạm sạc trong hành lang corridor 15km và chuẩn cổng CCS2.
   - Gọi `EnergyTool` tính toán tiêu hao năng lượng và thời gian sạc pin lên 80%.
   - Lưu `PlanVersionRecord` ở trạng thái `PENDING` vào DB và trả về proposal.
3. `GET /api/v1/trips/{trip_id}/plans`: Truy vấn danh sách các phiên bản kế hoạch của chuyến đi.

### 🔹 Frontend (`src/apps/web`)
- `App.tsx`: Quản lý toàn bộ luồng tạo trip, xử lý modal địa chỉ mơ hồ và kích hoạt lập kế hoạch.
- `AssumptionPanel.tsx`: Thẻ hiển thị các thông số giả định pilot.
- `TripPlanMap.tsx`: Bản đồ tuyến đường, điểm xuất phát, điểm đến và các trạm sạc đề xuất.
- `SocChart.tsx`: Biểu đồ mức pin (SOC %) giảm dần theo quãng đường và nạp tăng tại trạm sạc.
- `ChargingStopList.tsx`: Thẻ thông tin chi tiết từng trạm sạc dừng chân.

### 🔹 Cơ sở dữ liệu (Database)
- Hệ quản trị: PostgreSQL (Supabase Session Pooler) và hỗ trợ SQLite local cho test.
- Công cụ migration: Alembic.
- Các bảng đã có:
  - `vehicle_profiles`: Chứa thông số xe (Mặc định: `xe-x-mvp-v1`, version `xe_x_v1.0`).
  - `trips`: Lưu thông tin chuyến đi ở trạng thái `DRAFT, PLANNING, ACTIVE, COMPLETED, CANCELLED`.
  - `policy_configs`: Quản lý cấu hình policy tập trung (`reserve_soc_percent = 15.0`).
  - `plan_versions`: Lưu trữ các phiên bản kế hoạch dạng JSONB `NOT NULL`.

---

## 5. Chi tiết các User Story đã hoàn thành

### 5.1. F1-US1 — Nhập hành trình & Geocoding
- Hỗ trợ nhập địa chỉ dạng text và geocoding sang tọa độ.
- Trả về mã lỗi `AMBIGUOUS_LOCATION` kèm danh sách ứng viên nếu địa chỉ không rõ ràng.
- Validate `initial_soc_percent` trong khoảng `[1, 100]`.
- Tạo bản ghi `Trip` trạng thái `DRAFT` kèm `owner_id` và snapshot giả định.

### 5.2. F1-US2 — Cấu hình chính sách tập trung & Versioning giả định
- `PolicyConfigService` đọc active policy có cache và hỗ trợ override trong môi trường test.
- Fixture `Xe X v1` (version `xe_x_v1.0`) chứa dung lượng pin 75 kWh (khả dụng 71.2 kWh), cổng sạc CCS2, công suất sạc 150 kW, tiêu hao cơ sở 175 Wh/km.
- `AssumptionSnapshot` bất biến gồm: policy version, reserve SOC (15%), nhiệt độ môi trường (25°C), tải trọng (150kg) và vehicle profile version.
- UI có `AssumptionPanel` dạng đóng/mở và badge cảnh báo pilot.

### 5.3. F1-US3 — Lập kế hoạch lộ trình, trạm sạc và mức tiêu hao SOC
- Định tuyến độc lập qua `RoutingProvider` (Goong Directions / InMemory) trả về polyline hình học và cự ly.
- Lọc trạm sạc theo corridor hành lang tuyến (bán kính 15km, detour $\le 15$ phút, cổng CCS2).
- Tính toán mô hình vật lý tiêu hao năng lượng tất định 100% (không để LLM tự suy diễn số liệu).
- LangGraph Orchestrator điều phối tuần tự chuỗi tool và sinh structured output `PlanProposal`.
- UI hiển thị bản đồ lộ trình, danh sách điểm dừng sạc và biểu đồ SOC trực quan.

---

## 6. Hướng dẫn khởi động nhanh (Quick Start)

### 6.1. Yêu cầu môi trường
- Python 3.11+
- Node.js 20+ hoặc 22+
- npm

### 6.2. Tạo và kích hoạt môi trường ảo (Virtualenv)

Trên Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 6.3. Cài đặt dependencies Backend
```powershell
pip install -r requirements.txt
```

### 6.4. Cài đặt dependencies Frontend
```powershell
cd src/apps/web
npm install
cd ../../..
```

### 6.5. Cấu hình biến môi trường (`.env`)
Copy từ `.env.example` sang `.env` và điền giá trị thực tế:
```powershell
copy .env.example .env
```
Các biến quan trọng:
- `DATABASE_URL`: Kết nối Supabase PostgreSQL hoặc SQLite `sqlite:///./data/app.db`.
- `AUTH_SESSION_TTL_HOURS`: thời hạn phiên thường, mặc định 24 giờ.
- `AUTH_REMEMBERED_SESSION_TTL_DAYS`: thời hạn phiên “Ghi nhớ đăng nhập”, mặc định 30 ngày.
- `GEOCODER_PROVIDER`: `google`.
- `GOONG_MAPTILES_KEY`: key công khai để hiển thị Goong Maptiles trên frontend.
- `GOONG_API_KEY`: REST key giữ ở backend cho Places, Geocoding và Directions.
- `APP_ENV`: `development`.

### 6.6. Chạy Database Migrations
```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### 6.7. Khởi chạy Backend Server
```powershell
.\.venv\Scripts\uvicorn.exe src.apps.api.main:app --reload --port 8000
```
Swagger UI tài liệu API:
- `http://localhost:8000/docs`

### 6.8. Khởi chạy Frontend Web App
Mở một cửa sổ terminal mới:
```powershell
cd src/apps/web
npm run dev
```
Giao diện người dùng:
- `http://localhost:5173`

---

## 7. Kiểm thử và Build (Testing & Build)

### 7.1. Chạy Automated Tests Backend
Chạy toàn bộ test suite API & Planning:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api/ -v
```

Kiểm tra riêng test suite Lập kế hoạch (F1-US3):
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api/test_planning.py -v
```

### 7.2. Kiểm tra TypeScript & Build Frontend
```powershell
cd src/apps/web
npm run typecheck
npm run build
```
Artifact sau khi build được xuất ra: [build/web/index.html](build/web/index.html).

---

## 8. Quy ước và lưu ý cho thành viên nhóm (Team Conventions)

- **Biến môi trường:** `.env` là file cục bộ, tuyệt đối không commit lên Git.
- **Git Hook AI Log:** Chạy một lần sau khi clone để cài đặt pre-push hook:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1
  ```
- **Nguyên tắc tính toán an toàn:** Mọi công cụ tính toán lộ trình, năng lượng và trạm sạc phải nằm trong `packages/core` hoặc `packages/agent` dưới dạng **deterministic tools**, không để LLM tự suy diễn số liệu.
- **Đồng bộ schema:** Mọi thay đổi schema request/response phải được cập nhật đồng bộ trong `src/packages/contracts/`, backend routes và frontend types.

