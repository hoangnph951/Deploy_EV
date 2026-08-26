# Evaluation Report

> Báo cáo đánh giá chất lượng sản phẩm theo tiêu chí BTC.

---

## 1. Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Response accuracy | >80% | — | ⏳ |
| Response latency | <3s | — | ⏳ |
| User satisfaction | >4/5 | — | ⏳ |
| Test coverage | >60% | — | ⏳ |

## 2. Test Results

### Manual Evaluation Cases

Các case dưới đây được chạy thủ công qua giao diện/API. Phần `Actual output` được cập nhật bằng response thực tế sau mỗi lần chạy.

#### TC01 - Chuyến ngắn, không cần sạc

- Input:
  - Origin: `Vincom Center Bà Triệu, Hà Nội`.
  - Destination: `Hồ Hoàn Kiếm, Hà Nội`.
  - Initial SOC: `90%`.
  - Vehicle: `VinFast VF 3` (`vinfast-vf3-v1`).
  - Preference: `balanced`.
  - Cách nhập: chọn cả hai địa điểm từ danh sách gợi ý Goong trên UI.
- Expected: tạo được kế hoạch; không cần dừng sạc; SOC đến đích vẫn trên reserve 15%.
- Actual output:
  - `outcome`: `PLAN_CREATED`.
  - `trip_id`: `0431d936-22c9-49f2-b4e7-562697ca9fc9`.
  - `plan_id`: `plan-3f89b5e42169`; version `1`; status `PENDING`.
  - Route: `2.31 km`, `9.1 phút`, provider `GOONG_DIRECTIONS`.
  - `charging_stops`: `[]` (không cần dừng sạc).
  - SOC: `90.0%` tại điểm xuất phát → `88.7%` tại điểm đến.
  - Reserve SOC: `15.0%`.
  - Risk assessment: `FEASIBLE`, `LOW_RISK`, risk score `0.0`.
  - Detour: `0.0 km`, `0.0 phút`; `includes_backtracking=false`.
  - Effective consumption: `101.8 Wh/km`.
  - Environment: `29.5°C`, gió `6.4 km/h`, tăng độ cao `21 m`.
  - Summary: `Lộ trình trực tiếp 2.3 km; SOC tại đích 88.7%. Không cần sạc giữa chặng.`
- Result: `PASS` — hệ thống tạo kế hoạch khả thi, không thêm trạm sạc không cần thiết và SOC tại đích cao hơn reserve 15%.

#### TC02 - Quay lại trạm gần điểm xuất phát để sạc

- Input:
  - Origin: `10 Tạ Quang Bửu, Hai Bà Trưng, Hà Nội`.
  - Destination: `Highlands Coffee VinUniversity, Gia Lâm, Hà Nội`.
  - Initial SOC: `17%`.
  - Vehicle: `VinFast VF 3` (`vinfast-vf3-v1`).
  - Preference: `balanced`.
  - Cách nhập: chọn cả hai địa điểm từ danh sách gợi ý Goong trên UI; kiểm tra tất cả phương án trả về để tìm phương án có `includes_backtracking=true`.
- Expected: planner trả về ít nhất một phương án quay lại trạm gần hoặc phía sau điểm xuất phát, sạc rồi tiếp tục đi; `includes_backtracking=true`; SOC đến trạm không dưới 15%.
- Actual output:
  - `outcome`: `PLAN_CREATED`.
  - `trip_id`: `628464ba-28c0-4488-854e-fd47f1e1aa3b`.
  - Số phương án an toàn: `3`.
  - Phương án backtracking: alternative rank `3`, `plan_id=plan-d6394fb17ded`.
  - Route: `19.15 km`, `44.4 phút`; tuyến trực tiếp `15.42 km`.
  - Detour: `3.73 km`, `10.0 phút`; `includes_backtracking=true`.
  - Trạm sạc: `HTV GREENWAY`, station ID `C.HNO11740`.
  - Trạm: `ACTIVE`, `FRESH`, mở `24/7`, nguồn `VINFAST_OFFICIAL`.
  - Connector: `CCS2`; công suất `120 kW`; `6` cổng.
  - SOC: xuất phát `17.0%` → đến trạm `15.7%` → rời trạm `80.0%` → đến đích `71.7%`.
  - Thời gian sạc: `35.3 phút`; năng lượng bổ sung `11.99 kWh`.
  - Reserve SOC: `15.0%`; SOC đến trạm cao hơn reserve `0.7` điểm phần trăm.
  - Risk assessment: `FEASIBLE`, `LOW_RISK`, risk score `0.0`.
  - Summary: `Lộ trình 19.1 km, 1 điểm sạc (HTV GREENWAY), sạc khoảng 35 phút; SOC tại đích 71.7%. Có đoạn quay lại trạm gần điểm xuất phát.`
- Result: `PASS` — API trả về một phương án backtracking đã được định tuyến thực, có trạm CCS2 chính thức và duy trì SOC không thấp hơn reserve 15%.

#### TC03 - Chuyến dài cần dừng sạc dọc tuyến

- Input:
  - Origin: `Hà Nội, Việt Nam`.
  - Destination: `Thành phố Vinh, Nghệ An, Việt Nam`.
  - Initial SOC: `60%`.
  - Vehicle: `VinFast VF 3` (`vinfast-vf3-v1`).
  - Preference: `balanced`.
  - Cách nhập: chọn cả hai địa điểm từ danh sách gợi ý Goong trên UI.
- Expected: tạo được kế hoạch; có trạm CCS2 phù hợp; response có SOC đến/rời trạm và thời gian sạc.
- Actual output:
  - `outcome`: `PLAN_CREATED`.
  - `trip_id`: `2b461f38-794e-4dea-b9b7-531726cc0d32`.
  - `plan_id`: `plan-9781779c4374`; version `1`; status `PENDING`.
  - Route: `305.43 km`, `322.8 phút`, provider `GOONG_DIRECTIONS`.
  - Tuyến trực tiếp: `299.96 km`; detour `5.47 km`, `13.4 phút`; `includes_backtracking=false`.
  - Số điểm sạc: `3`.
  - Điểm sạc 1: `HTV GREENWAY`, station ID `C.HNO11740`.
    - Connector: `CCS2`; công suất `120 kW`; `6` cổng.
    - Trạm: `ACTIVE`, `FRESH`, mở `24/7`.
    - SOC: đến trạm `57.6%` → rời trạm `80.0%`.
    - Thời gian sạc: `12.3 phút`; năng lượng bổ sung `4.18 kWh`.
  - Điểm sạc 2: `Trạm dừng nghỉ Tây Ninh Bình - Chiều đi`, station ID `C.NBI0017`.
    - Connector: `CCS2`; công suất `250 kW`; `10` cổng.
    - Trạm: `ACTIVE`, `FRESH`, mở `24/7`.
    - SOC: đến trạm `34.2%` → rời trạm `80.0%`.
    - Thời gian sạc: `25.1 phút`; năng lượng bổ sung `8.53 kWh`.
  - Điểm sạc 3: `Cửa hàng xăng dầu Petrolimex Nghệ An Số 76 Quỳnh Vinh`, station ID `C.NAN0040`.
    - Connector: `CCS2`; công suất `180 kW`; `2` cổng.
    - Trạm: `ACTIVE`, `FRESH`, mở `24/7`.
    - SOC: đến trạm `18.9%` → rời trạm `80.0%`.
    - Thời gian sạc: `33.5 phút`; năng lượng bổ sung `11.39 kWh`.
  - Tổng thời gian sạc: khoảng `71 phút`.
  - SOC: xuất phát `60.0%` → đến đích `40.5%`.
  - Reserve SOC: `15.0%`.
  - Risk assessment: `FEASIBLE`, `LOW_RISK`, risk score `0.0`.
  - Effective consumption: `90.8 Wh/km`.
  - Environment: `27.0°C`, gió `4.2 km/h`, tăng độ cao `236 m`.
  - Summary: `Lộ trình 305.4 km, 3 điểm sạc (HTV GREENWAY → Trạm dừng nghỉ Tây Ninh Bình - Chiều đi → Cửa hàng xăng dầu Petrolimex Nghệ An Số 76 Quỳnh Vinh), sạc khoảng 71 phút; SOC tại đích 40.5%.`
- Result: `PASS` — hệ thống tạo được kế hoạch khả thi cho chuyến dài, bố trí 3 điểm sạc CCS2; response cung cấp đầy đủ SOC đến/rời từng trạm và thời gian sạc, đồng thời duy trì SOC tại các điểm đến không thấp hơn reserve 15%.

#### TC04 - SOC thấp hơn mức dự phòng

- Input:
  - Origin: `Hà Nội, Việt Nam`.
  - Destination: `Thành phố Vinh, Nghệ An, Việt Nam`.
  - Initial SOC: `10%`.
  - Vehicle: `VinFast VF 3` (`vinfast-vf3-v1`).
  - Preference: `balanced`.
  - Cách nhập: chọn cả hai địa điểm từ danh sách gợi ý Goong trên UI.
- Expected: hệ thống fail-closed, không tạo plan giả; `outcome=INFEASIBLE`; reason code gồm `INITIAL_SOC_BELOW_RESERVE`.
- Actual output:
  - `outcome`: `INFEASIBLE`.
  - `trip_id`: `81593b43-3dc6-4911-86e5-ce9276549bbf`.
  - Không có plan được tạo.
  - `charging_stops`: `[]`.
  - Initial SOC: `10.0%`.
  - Reserve SOC: `15.0%`.
  - Risk assessment: `INFEASIBLE`, `is_feasible=false`, risk score `100.0`.
  - Reason codes:
    - `SOC_BELOW_RESERVE_15`.
    - `INITIAL_SOC_BELOW_RESERVE`.
    - `UNREACHABLE_NEXT_STATION`.
  - Reasons:
    - SOC dự kiến tại `Destination` còn `-136.0%`, thấp hơn reserve `15.0%`.
    - SOC khởi hành `10.0%` thấp hơn reserve `15.0%`.
    - Không thể tiếp cận trạm tiếp theo mà vẫn duy trì SOC dự phòng.
  - Số trạm được đánh giá: `0`.
  - Search scope: `ADAPTIVE_CORRIDOR_5_10_20_KM`.
  - Summary: `Không có phương án an toàn đã được chứng minh cho chuyến đi (SOC_BELOW_RESERVE_15, INITIAL_SOC_BELOW_RESERVE, UNREACHABLE_NEXT_STATION).`
- Result: `PASS` — hệ thống fail-closed khi SOC khởi hành `10%` thấp hơn reserve `15%`, trả `outcome=INFEASIBLE` với reason code `INITIAL_SOC_BELOW_RESERVE` và không tạo kế hoạch hoặc điểm sạc giả.

#### TC05 - Input không hợp lệ

- Input:
  - Origin: `Vincom Center Bà Triệu, Hà Nội`.
  - Destination: `Vincom Center Bà Triệu, Hà Nội`.
  - Initial SOC: `60%`.
  - Vehicle: `VinFast VF 3` (`vinfast-vf3-v1`).
  - Preference: `balanced`.
  - Cách nhập: chọn cùng một địa điểm từ danh sách gợi ý Goong cho cả origin và destination.
- Expected: API/UI trả lỗi validation; không gọi planning.
- Actual output:
  - API trả lỗi validation.
  - Error code: `VALIDATION_ERROR`.
  - Message: `Điểm xuất phát và điểm đến phải khác nhau.`
  - Fields liên quan: `origin`, `destination`.
  - Reason: `SAME_ORIGIN_DESTINATION`.
  - `trace_id`: `c65247eb-f495-4daa-863f-96af662b169a`.
  - Response không chứa `trip_id`, `plan_id` hoặc kế hoạch hành trình.
  - Việc planner có được gọi nội bộ hay không không thể xác minh chỉ từ response này.
- Result: `PASS` — hệ thống phát hiện origin và destination trùng nhau và trả `VALIDATION_ERROR` với reason `SAME_ORIGIN_DESTINATION`; không có kế hoạch hành trình được trả về.

### Unit Tests

```text
Command: .\.venv\Scripts\python.exe -m pytest tests -q
Result: 78 passed in 2.48s
```

### Integration Tests

```text
Command: npm run typecheck
Result: Passed (tsc --noEmit -p tsconfig.app.json)
```

## 3. User Feedback

| User | Feedback | Rating |
|------|----------|--------|
| [User 1] | [feedback] | [1-5] |
| [User 2] | [feedback] | [1-5] |

## 4. Demo Results

- Ngày demo: [YYYY-MM-DD]
- Người tham gia: [số người]
- Feedback chung: [tóm tắt]
- Issues phát hiện: [danh sách]

## 5. Action Items

- [ ] [Cần cải thiện 1]
- [ ] [Cần cải thiện 2]
