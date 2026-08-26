# BRIEF — AI Agent lập kế hoạch chuyến đi và sạc pin cho Xe X

**Phiên bản:** 3.0  
**Ngày cập nhật:** 06/08/2026  
**Trạng thái:** Draft đã cập nhật theo phản hồi mentor  
**Primary persona:** Chủ xe Xe X đi đường dài  
**Secondary persona:** Hỗ trợ viên — Should/P1

> Ứng dụng web giúp chủ xe lập kế hoạch hành trình xe điện có điểm sạc, hiểu rủi ro, xác nhận kế hoạch và nhận phương án thay thế khi trạng thái chuyến đi thay đổi. AI Agent làm nhiệm vụ điều phối công cụ và giải thích; các kết luận về tuyến, năng lượng, trạm và tính khả thi phải đến từ dữ liệu có cấu trúc và công cụ xác định.

---

## 1. Vấn đề cần giải quyết

Khi chuẩn bị chuyến đi dài bằng xe điện, chủ xe phải tự kết hợp nhiều nguồn:

- Bản đồ và tuyến đường.
- Mức pin hiện tại.
- Mức tiêu hao của xe.
- Vị trí, đầu nối và công suất trạm sạc.
- Thời gian dừng sạc.
- Mức pin an toàn tối thiểu.
- Rủi ro khi đi lệch tuyến, pin tụt nhanh hoặc trạm dự kiến không dùng được.

Kế hoạch thủ công dễ rời rạc, khó kiểm chứng và có thể mất tính khả thi trong chuyến đi.

**Giả thuyết pain point cần xác thực:** người dùng phải mở nhiều ứng dụng, tự ước lượng và kể lại toàn bộ trạng thái khi cần hỗ trợ. Nhóm cần phỏng vấn 3–5 chủ xe và quan sát ít nhất 5 phiên lập kế hoạch trước khi chốt baseline.

---

## 2. Giá trị cốt lõi của sản phẩm

Sản phẩm phải giúp chủ xe trả lời bốn câu hỏi:

1. Chuyến đi có khả thi với mức pin và giả định hiện tại không?
2. Nên đi tuyến nào và sạc ở đâu?
3. Kế hoạch dựa trên dữ liệu và giả định nào?
4. Khi trạng thái thay đổi, có phương án thay thế an toàn nào không?

---

## 3. Vai trò của AI Agent

### Agent được làm

- Hiểu yêu cầu và sự kiện kích hoạt.
- Chọn công cụ phù hợp trong workflow đã cho phép.
- Điều phối theo dependency:
  `Route → Energy + Station → Feasibility → PlanProposal`.
- Tổng hợp kết quả có cấu trúc.
- Giải thích lựa chọn và lý do loại phương án.
- Yêu cầu người dùng xác nhận thay đổi quan trọng.

### Agent không được làm

- Tự tạo trạm, tọa độ, khoảng cách, công suất hoặc trạng thái live.
- Dùng suy luận ngôn ngữ thay cho phép tính pin và feasibility.
- Ghi đè kết luận `INFEASIBLE`.
- Ghi trực tiếp dữ liệu nghiệp vụ vào PostgreSQL.
- Tự xác nhận hoặc áp dụng kế hoạch thay người dùng.

---

## 4. Phạm vi feature

### Must 1 — Lập kế hoạch trước chuyến đi

Gồm nhập dữ liệu, công bố giả định, tính tuyến, ước tính năng lượng, tìm trạm và kiểm tra khả thi.

**Giá trị demo:** người dùng nhập trip và nhận được route, trạm sạc, SOC dự kiến và mức rủi ro.

### Must 2 — Giải thích và xác nhận kế hoạch

Giải thích lựa chọn, lưu phiên bản và chỉ áp dụng kế hoạch sau khi chủ xe xác nhận.

### Must 3 — Theo dõi chuyến đi mô phỏng

Nhận GPS, SOC và event; hiển thị nguồn dữ liệu, thời điểm cập nhật và so sánh với kế hoạch đã xác nhận.

### Must 4 — Tái lập kế hoạch

Phát hiện lệch tuyến, SOC tụt nhanh hoặc sự kiện trạm không khả dụng; tạo proposal mới và xin xác nhận lại.

### Should — Không gian hỗ trợ chuyến đi dạng chỉ đọc

Hỗ trợ viên được cấp quyền có thể xem trạng thái, cảnh báo, plan hiện hành và lịch sử replan; không được sửa telemetry hoặc confirm/reject thay chủ xe.

---

## 5. Dữ liệu hybrid của MVP

| Trường dữ liệu | Nguồn | Nhãn |
|---|---|---|
| Điểm đầu, điểm cuối | Người dùng nhập | `MANUAL` |
| SOC ban đầu | Người dùng nhập | `MANUAL` |
| Vị trí trong chuyến đi | GPS điện thoại | `REAL_GPS` |
| Tuyến đường | Map API | `REAL_API` |
| Route dùng benchmark | Snapshot cố định | `CACHED_SNAPSHOT` |
| Metadata trạm | Open Charge Map hoặc nguồn đã kiểm chứng | `REAL_API` / `CACHED_SNAPSHOT` |
| SOC trong chuyến đi | Telemetry Simulator | `SIMULATED` |
| Trạng thái trạm không khả dụng | Station Event Simulator | `SIMULATED` |

Mọi dữ liệu hiển thị phải có:

- Loại nguồn.
- Tên nguồn.
- `updated_at`.
- Độ mới/freshness.
- `scenario_id` nếu là mô phỏng.
- `snapshot_version` nếu là cached snapshot.

Sản phẩm không được tuyên bố đang đọc SOC thật từ xe hoặc availability thật của trạm.

---

## 6. Giả định pilot

- Một vehicle profile Xe X được version hóa.
- Mức pin dự phòng cố định cho benchmark: **15%**.
- `reserve_soc = 15%` là configuration, không hard-code sâu trong thuật toán.
- UI hiển thị rõ mức 15%.
- MVP chưa cho end-user tự chỉnh reserve SOC.
- SOC trong chuyến đi và station event được mô phỏng có kiểm soát.
- Benchmark dùng snapshot/fixture cố định, không dùng dữ liệu live làm ground truth.

---

## 7. Luồng chính

### Trước chuyến đi

```text
Nhập trip
→ Validate + công bố giả định
→ Route
→ Energy + Station
→ Feasibility
→ Hiển thị plan, trạm và risk
→ Giải thích
→ User confirm/reject
```

### Trong chuyến đi

```text
GPS thật + SOC mô phỏng + simulated event
→ Monitoring Service
→ Không có sự kiện: chỉ cập nhật trạng thái
→ Có sự kiện: yêu cầu replan
→ Route
→ Energy + Station
→ Feasibility
→ PlanProposal mới
→ User confirm/reject
```

---

## 8. Mốc vertical slice 08/08

Đến 08/08, team cần demo được một lát cắt mỏng chạy xuyên suốt:

```text
Nhập điểm đầu, điểm cuối, SOC
→ tạo một route
→ tìm ít nhất một trạm phù hợp
→ tính feasibility/risk cơ bản
→ hiển thị route, trạm và risk
```

Không để toàn bộ core planning đến MVP Day mới tích hợp.

---

## 9. Evaluation

### Smoke set

- 20 case chạy nhanh sau mỗi build.
- Ưu tiên chất lượng và ground truth rõ ràng hơn số lượng.

### Benchmark set

- Mở rộng tối thiểu 60 case sau khi smoke set ổn định.
- Dùng fixtures và snapshot được version hóa.

### Nhóm tình huống

- Happy path.
- Boundary.
- Invalid input.
- Safety.
- Replanning.
- Confirmation.
- Provider failure.
- Explanation.

### Ngưỡng chính

- `INFEASIBLE` recall = 100%.
- Feasibility accuracy ≥ 95%.
- Valid charging plan rate = 100%.
- High-risk recall ≥ 95%.
- Tool-selection accuracy ≥ 90%.
- Unnecessary tool-call rate ≤ 10%.
- Hallucinated station/route facts = 0.
- Median replanning < 10 giây; p95 < 30 giây.
- 100% kế hoạch mới chỉ có hiệu lực sau khi đúng chủ xe xác nhận.

---

## 10. Kiến trúc và contract

- Trip Service là write boundary duy nhất cho Trip và PlanVersion.
- Agent chỉ trả structured `PlanProposal`.
- Monitoring Service chỉ phát hiện sự kiện.
- Chỉ cần hoàn thiện OpenAPI cho các luồng chính:
  - Tạo trip.
  - Tạo plan.
  - Cập nhật telemetry/simulator event.
  - Replan.
  - Confirm/reject.
  - Xem trip và plan history.
- PRD giữ What/Why/Scope/AC/Metric.
- Technical Design giữ stack, component, contract, sequence, timeout/retry/fallback và deployment.

---

## 11. MVP demo path

```text
Create trip
→ Generate grounded plan
→ Explain
→ Confirm
→ Start monitoring
→ Trigger deviation / SOC underperformance / station event
→ Replan
→ Confirm or reject
→ Show provenance, freshness, assumptions and plan history
```
