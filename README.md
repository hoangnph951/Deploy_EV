# P-210: AI EV Trip Planner

Ứng dụng web hỗ trợ chủ xe điện lập kế hoạch hành trình: chọn xe, nhập điểm đi/đến, tính tuyến đường, tìm trạm sạc phù hợp, dự báo SOC và đánh giá rủi ro. Hệ thống dùng dữ liệu có cấu trúc cùng các công cụ xác định cho các kết luận an toàn; AI chỉ hỗ trợ điều phối và giải thích.

## Demo

- Ứng dụng đã deploy: [https://p-210-web-dev.onrender.com](https://p-210-web-dev.onrender.com)
- Video demo: [YouTube](https://youtu.be/xjzdH6SZfS0)
- Kết quả đánh giá: [eval/results/report.md](eval/results/report.md)

## Tính năng hiện có

- Đăng ký, đăng nhập và quản lý xe cá nhân.
- Tìm kiếm địa điểm với Goong Places; xử lý địa chỉ mơ hồ bằng danh sách gợi ý.
- Tạo trip với snapshot giả định và policy dự phòng SOC.
- Lập kế hoạch qua Goong Directions, VinFast Locator và mô hình năng lượng tất định.
- Đề xuất nhiều phương án, hiển thị tuyến trên bản đồ, các điểm sạc, SOC theo hành trình và dữ liệu nguồn.
- Lưu version kế hoạch và cho phép xác nhận kế hoạch.
- Mô phỏng F3 cho các sự kiện lệch tuyến, SOC thấp hơn dự kiến, trạm không khả dụng và telemetry cũ.
- F4 Replanning: gom sự kiện, tạo safety envelope, lập candidate mới từ telemetry hiện tại, so sánh thay đổi với kế hoạch cũ và yêu cầu người dùng xác nhận hành động.

Trong chế độ mô phỏng ngẫu nhiên, `NORMAL` và mỗi tình huống rủi ro khả dụng có xác suất bằng nhau. Khi plan có trạm sạc, mỗi trong 5 tình huống có xác suất 20%; nếu không có trạm, mỗi trong 4 tình huống có xác suất 25%.

## Luồng nghiệp vụ

```text
Đăng nhập và chọn xe
  -> Nhập điểm đi, điểm đến, SOC
  -> Geocode và tạo trip
  -> Routing + tìm trạm + mô phỏng năng lượng
  -> Plan proposal (PENDING)
  -> Xác nhận và theo dõi hành trình
  -> Monitoring event
  -> F4 đánh giá, tạo replan candidate
  -> Người dùng xác nhận hoặc từ chối candidate
```

## Kiến trúc

```text
src/
  apps/api/           FastAPI routes, bootstrap và middleware
  apps/web/           React + Vite frontend
  packages/agent/     LangGraph planning và replanning supervisor
  packages/contracts/ Pydantic contracts dùng chung
  packages/core/      trips, monitoring, replanning và policies
migrations/           Alembic migrations
tests/                Unit/API/integration tests
docs/                 PRD, kiến trúc và feature specifications
```

Các quy tắc về tuyến, năng lượng, SOC, khả năng tiếp cận trạm và feasibility nằm ở `packages/core`. LLM không được phép tự tạo các số liệu hoặc vượt qua safety gate.

## Công nghệ

- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic, LangGraph.
- Frontend: React 18, TypeScript, Vite, React Hook Form.
- Data providers: Goong Places/Directions, VinFast Locator, Open-Meteo.
- Database: PostgreSQL/Supabase cho môi trường dùng chung; SQLite cho local/test.

## Chạy local

Yêu cầu: Python 3.10+, Node.js 20+ và npm.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
cd src/apps/web
npm install
cd ../../..
```

Cập nhật `.env` với ít nhất `DATABASE_URL`, `GOONG_API_KEY` và `GOONG_MAPTILES_KEY`. Không commit file `.env`.

Chạy migrations:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Chạy API:

```powershell
.\.venv\Scripts\uvicorn.exe src.apps.api.main:app --reload --port 8000
```

Chạy frontend trong terminal khác:

```powershell
cd src/apps/web
cmd /c npm run dev
```

- Web local: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

## API chính

| Nhóm | Endpoint |
| --- | --- |
| Auth | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me` |
| Xe | `GET /api/v1/vehicle-profiles`, `GET/POST/PATCH /api/v1/me/vehicles` |
| Trip | `POST /api/v1/trips`, `GET /api/v1/trips/{trip_id}`, `GET /api/v1/trips/history` |
| Planning | `POST /api/v1/trips/{trip_id}/plans`, `POST /api/v1/trips/{trip_id}/plans/stream`, `GET /api/v1/trips/{trip_id}/plans` |
| Monitoring | `POST /api/v1/simulator/trips/{trip_id}/start`, `POST /api/v1/simulator/trips/{trip_id}/tick` |
| Replanning | `POST /api/v1/trips/{trip_id}/replans`, `POST /api/v1/trips/{trip_id}/plans/{version}/confirm` |

Xem schema đầy đủ tại Swagger UI hoặc các contract trong `src/packages/contracts/`.

## Kiểm tra chất lượng

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
cd src/apps/web
cmd /c npm run typecheck
cmd /c npm run build
```

## Tài liệu

- [Product brief](docs/BRIEF_AI_EV_AGENT_v3.0.md)
- [Technical architecture](docs/TECHNICAL_ARCHITECTURE_AI_EV_AGENT_v3.1.md)
- [F4 implementation specification](docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md)
- [Agent architecture](docs/agent_architecture.md)

## Lưu ý vận hành

- Trạng thái trạm từ VinFast là metadata nguồn dữ liệu, không phải số cổng trống theo thời gian thực.
- Fallback và dữ liệu cache phải hiển thị kèm provenance/freshness; không kết luận an toàn khi thiếu bằng chứng.
- Khi deploy trên Render, cấu hình `CORS_ORIGINS`, database và các API key bằng environment variables trong dashboard service.

### Luồng khép kín F1–F4

1. F1 tạo phương án ở trạng thái `PENDING`.
2. Người dùng bấm **Xác nhận hành trình**; F2 kiểm tra phiên bản plan/context và chuyển phương án thành `CONFIRMED`.
3. F3 chỉ cho phép mô phỏng đúng phiên bản đã xác nhận. Plan chưa xác nhận trả `409 PLAN_NOT_CONFIRMED`.
4. Khi F3 phát canonical event, frontend tự gửi sự kiện đó sang F4 đúng một lần theo `event_id`.
5. F4 chạy chuỗi kiểm tra nhiều bước, phản tư sau mỗi bằng chứng, gọi F1 tạo candidate khi đủ điều kiện và vẫn để candidate ở `PENDING` chờ người dùng xác nhận.

Feature 4 hiển thị nhật ký quyết định bằng tiếng Việt. Nhật ký chỉ gồm mục tiêu, công cụ đã dùng, bằng chứng, phần còn thiếu, kết luận và hành động; không lưu hoặc hiển thị chain-of-thought riêng tư của mô hình.

Kiểm thử frontend bổ sung:

```powershell
cd src/apps/web
npm test
npm run build
```
