# F1 OSRM Station Graph — Hướng dẫn nhanh bàn giao

## 1. Bạn cần gửi cho đồng nghiệp

Gửi hai thứ qua hai kênh riêng:

1. **Git repository/branch** chứa code.
2. Thư mục **`data/osrm/`** qua Google Drive.

Không commit `data/osrm/`, `.env`, database credential hoặc database dump lên GitHub.

## 2. Đồng nghiệp chuẩn bị máy

Yêu cầu:

- Docker Desktop đang chạy.
- Python 3.11+.
- Máy có tối thiểu khoảng 12 GB RAM vật lý.
- Docker được cấp khoảng 6–8 GB RAM trở lên.

Clone code:

```powershell
git clone <repository-url>
cd P-210
git switch <branch-name>

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Chép OSRM artifact từ Google Drive

Tải thư mục `osrm` từ Drive và đặt vào:

```text
P-210\data\osrm\
```

Cần giữ nguyên tên file và cấu trúc thư mục. Không giải nén thành thư mục lồng sai dạng:

```text
P-210\data\osrm\osrm\   # sai
```

Kiểm tra tối thiểu:

```powershell
Test-Path .\data\osrm\road-version.txt
Test-Path .\data\osrm\vietnam-routing.osrm
Test-Path .\data\osrm\vietnam-routing.osrm.mldgr
Test-Path .\data\osrm\vietnam-routing.osrm.partition
```

Tất cả phải trả về `True`.

## 4. Cấu hình `.env`

Copy file mẫu:

```powershell
Copy-Item .env.example .env
```

Nếu OSRM chạy trực tiếp trên máy host:

```dotenv
DATABASE_URL=<postgresql-postgis-connection-string>
STATION_GRAPH_ENABLED=false
STATION_GRAPH_ROUTING_PROVIDER=osrm
STATION_GRAPH_MAX_NEIGHBORS=40
OSRM_BASE_URL=http://127.0.0.1:5000
OSRM_PROFILE=driving
OSRM_ROAD_VERSION_FILE=data/osrm/road-version.txt
```

Nếu backend cũng chạy bằng Docker Compose, dùng:

```dotenv
OSRM_BASE_URL=http://osrm:5000
```

Giữ `STATION_GRAPH_ENABLED=false` trong lần chạy kiểm tra đầu tiên.

## 5. Khởi động OSRM

Từ thư mục root `P-210`:

```powershell
docker compose --profile routing up -d osrm
docker compose --profile routing ps
docker compose --profile routing logs --tail 100 osrm
```

Container phải ở trạng thái `running` hoặc `Up`, không được restart loop.

Smoke test:

```powershell
$result = Invoke-RestMethod `
  "http://127.0.0.1:5000/table/v1/driving/106.7009,10.7769;106.6602,10.7626?sources=0&destinations=1&annotations=distance,duration"
$result | ConvertTo-Json -Depth 5
```

Kết quả cần có:

```text
code = Ok
distances[0][0] != null
durations[0][0] != null
```

OSRM dùng thứ tự tọa độ `longitude,latitude`.

## 6. Kiểm tra database graph

Đồng nghiệp chạy:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe scripts\verify_f1_rollout_schema.py
```

Database đúng phải có:

```text
Alembic: 20260822_1700 (head)
Graph: ACTIVE
Processed nodes: 23,919 / 23,919
Edges: 946,138
Max out-degree: 40
Inactive endpoints: 0
```

Nếu database mới chưa có graph `ACTIVE`, không bật feature flag. Cần chạy migration, station sync và graph builder theo tài liệu đầy đủ:

```text
docs/F1_OSRM_HANDOFF_GUIDE.md
```

## 7. Bật graph sau khi owner xác nhận

Chỉ khi OSRM smoke test và database graph đều pass, đổi deployment environment:

```dotenv
STATION_GRAPH_ENABLED=true
```

Restart backend:

```powershell
docker compose restart backend
```

Không sửa graph binary, không tự tạo `road-version.txt` và không dùng graph `BUILDING`, `FAILED` hoặc `SUPERSEDED`.

## 8. Nếu có lỗi

- Container OSRM không chạy: xem `docker compose --profile routing logs osrm`.
- Thiếu file `.osrm*`: tải lại đầy đủ thư mục `data/osrm` từ Drive.
- Smoke trả `NoRoute` hoặc `null`: kiểm tra đúng file artifact và đúng thứ tự `longitude,latitude`.
- Database không có graph `ACTIVE`: giữ `STATION_GRAPH_ENABLED=false`, không ép activation.
- Không chia sẻ credential trong Drive công khai; gửi `.env`/connection string qua kênh bảo mật riêng.

## 9. Bằng chứng bàn giao hiện tại

- OSRM preprocessing, partition, customize và routed trial: **PASS**.
- OSRM Table smoke test: **PASS**.
- Graph nationwide: **23,919/23,919 nodes**, trạng thái **ACTIVE**.
- `946,138` edges, max out-degree `40`, inactive endpoint `0`.
- Feature flag mặc định vẫn để `false` chờ owner approval.
