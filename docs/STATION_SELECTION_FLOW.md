# Luồng chọn trạm sạc hiện tại

## 1. Luồng tổng quát

```text
Nhận trip
  |
  v
Goong: route Origin -> Destination
  |
  v
Tính EnergyTool và thử đi thẳng
  |------------------------------|
  | đi thẳng an toàn              | cần sạc
  v                               v
Proposal                   Official lazy graph search
                                  |
                 |----------------+----------------|
                 | plan feasible                   | không có plan
                 v                                  v
             Proposal                    phân loại lỗi/search
                                      |       |       |
                                  rate    provider  exhausted
                                  limit   unavailable  |
                                      v       v       v
                                  Action    Action  OpenAI recovery
                                  Required  Required    |
                                                        v
                                             Goong + EnergyTool + Safety Gate
                                                        |
                                                Proposal hoặc Search Exhausted
```

Safety Gate là nguồn quyết định cuối cùng. Xếp hạng chỉ sắp xếp các plan đã được
Safety Gate xác nhận.

## 2. Bước route và đi thẳng

1. Lấy base route bằng Goong.
2. Lấy môi trường và tính consumption bằng EnergyTool.
3. Mô phỏng route không dừng sạc.
4. Nếu direct trip vẫn giữ reserve, trả proposal ngay và không gọi station provider.

Nếu SOC khởi hành dưới reserve, đây là `PROVEN_INFEASIBLE`; không gọi OpenAI để
tìm trạm vì xe đã không ở trạng thái xuất phát hợp lệ.

## 3. Official station discovery

Planner official gọi `find_official_station_window()` theo cửa sổ reachability của
từng label. Discovery dùng connector tương thích, corridor, progress, detour và
origin radius.

Mỗi lần backfill dùng các mức detail:

```text
24 -> 48 -> 96
```

Ý nghĩa là mở rộng số candidate được lấy detail từ provider. Sau merge chỉ giữ
target tối đa 12 candidate cho một cửa sổ. Candidate được deduplicate theo
`station_id`; số thực tế có thể nhỏ hơn 12.

## 4. Tiêu chí xếp candidate

Candidate score hiện tại là thứ tự ưu tiên deterministic, không phải quyết định
loại bỏ an toàn:

```text
ACTIVE
-> không dead-end
-> có khả năng tới destination theo lower bound
-> nhiều candidate nối tiếp hơn
-> progress phù hợp với chặng
-> detour thấp hơn
-> công suất cao hơn
```

Điểm “nhiều candidate nối tiếp” giúp tránh local optimum kiểu chọn trạm đi xa
nhưng không còn trạm phía sau.

## 5. Xây graph và kiểm tra cạnh

Graph là graph động. Node vật lý là Origin, station và Destination; một node có
thể có nhiều label Pareto.

Với mỗi edge candidate:

```text
1. gọi Goong từ vị trí hiện tại tới candidate;
2. tính chi phí SOC của leg;
3. kiểm tra arrival SOC >= reserve;
4. tính departure SOC và charge time tại station trước;
5. tạo label mới;
6. bỏ label nếu bị một label khác thống trị;
7. đẩy label còn lại vào priority queue.
```

Khi tới destination, planner gọi Goong (trừ label Origin có thể dùng base route),
ghép các leg, tính detour thật, mô phỏng itinerary cố định và chạy Safety Gate.

## 6. Pareto frontier

Không dùng các giới hạn cứng cũ như:

```text
EDGE_VALIDATION_LIMIT = 3
BRANCH_WIDTH = 2
STATE_WIDTH = 4
minimum_stops + 3
```

Thay vào đó, cùng một station giữ các label không bị dominated theo SOC, thời gian,
detour, rủi ro và số stop. Có một ngân sách xác minh toàn cục để bảo vệ latency:

```text
MAX_EDGE_VALIDATIONS = 120
SEARCH_TIME_BUDGET   = 45 giây / request
```

Mỗi label ưu tiên kiểm tra 8 candidate đầu. Nếu không tạo được cạnh nào, planner
mới mở rộng các candidate còn lại. Nếu hết edge budget hoặc time budget, trả trạng
thái cần retry với reason cụ thể; không gọi đó là infeasible.

## 7. Ba phương án trả về

Sau khi có các plan đã vượt Safety Gate, hệ thống dựng tối đa ba strategy:

```text
BALANCED
FASTEST
SAFEST
```

Nếu hai strategy trỏ tới cùng tuple station ID, chỉ giữ một bản. Vì vậy “tối đa 3”
không có nghĩa luôn luôn có đúng 3 phương án.

OpenAI ranking (nếu bật) chỉ chọn giữa các plan feasible đã được tạo. Nó không được
sửa station, route, SOC hoặc Safety Verdict.

## 8. Recovery OpenAI

Recovery chỉ được gọi khi:

1. direct trip không feasible;
2. official lazy search đã thực sự kết thúc mà không có plan;
3. không có lỗi rate limit;
4. station provider không ở trạng thái unavailable;
5. recovery station service tồn tại.

Recovery gọi `find_recovery_station_window()` và đánh dấu station web là
`UNVERIFIED`/`STALE`. Candidate recovery vẫn phải qua Goong, EnergyTool và Safety
Gate. Vì dữ liệu availability chưa được official xác minh, plan thường trả
`CONDITIONAL` hoặc `RISKY`.

Các trường hợp không gọi OpenAI recovery:

```text
INITIAL_SOC_BELOW_RESERVE -> PROVEN_INFEASIBLE
GOONG 429                 -> ACTION_REQUIRED / RETRY
ROUTING_VALIDATION_BUDGET -> SEARCH_EXHAUSTED / RETRY
station provider outage   -> ACTION_REQUIRED
```

## 9. Phân biệt outcome

```text
CONDITIONAL
    Plan đã qua Safety Gate nhưng có station cần xác nhận.

SEARCH_EXHAUSTED
    Chưa tìm thấy chain trong phạm vi/budget đã duyệt; không kết luận bất khả thi.

PROVEN_INFEASIBLE
    Có bằng chứng Safety Gate rằng điều kiện năng lượng hiện tại không thể thỏa.

ACTION_REQUIRED
    Cần retry vì provider, rate limit hoặc ngân sách xác minh.
```

## 10. Dữ liệu cần log để debug

```text
search_source
attempted_edge_count
route_failure_count
candidate station + provenance
station_provider_unavailable
station_routing_rate_limited
station_routing_budget_exhausted
official_search_exhausted
recovery_mode
recovery_search_exhausted
```

Khi thấy OpenAI station trong kết quả, cần kiểm tra:

1. Direct trip có thật sự không feasible không?
2. Official search có `search_exhausted=true` hay bị dừng do lỗi/budget?
3. Có station official nào đã được Goong xác minh nhưng Safety Gate loại vì SOC/detour không?
4. Nếu recovery tạo plan, station đó phải mang provenance OpenAI và risk tương ứng.

## 11. Tóm tắt

```text
Goong base route
 -> direct energy check
 -> official candidate windows
 -> candidate ordering with future connectivity
 -> lazy Goong edges
 -> Pareto multi-label frontier
 -> complete route + EnergyTool
 -> Safety Gate
 -> tối đa 3 strategy
 -> chỉ khi official search exhausted mới recovery OpenAI
```
