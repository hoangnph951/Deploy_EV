# Thuật toán Lazy Multi-Label Graph Search

Tài liệu này mô tả thuật toán đang chạy trong
`src/packages/agent/planning/tools/adaptive_station_planner.py`.

Planner tìm chuỗi trạm sạc an toàn với số lần gọi Goong hợp lý. Goong là nguồn
xác minh route thực tế; Safety Gate vẫn là nơi duy nhất quyết định itinerary có
được chấp nhận hay không.

## 1. Ý tưởng chính

Planner không dựng toàn bộ graph của mọi trạm. Graph được dựng lười (lazy):

```text
Origin hoặc trạm hiện tại
        |
        | chỉ khi candidate có triển vọng
        v
Goong xác minh cạnh tới candidate
        |
        v
Label mới: SOC, thời gian, detour, rủi ro, chuỗi trạm
```

Mỗi station có thể có nhiều label. Một label là một cách khác nhau để đến cùng
station, vì đến nhanh hơn và đến với SOC cao hơn là hai ưu điểm khác nhau.

```text
Label = {
    node_id,
    arrival_soc_percent,
    minimum_soc_percent,
    drive_time_min,
    charge_time_min,
    detour_proxy_km,
    risk_penalty,
    stations,
    verified_legs,
}
```

Không có giới hạn kiểu “mỗi state chỉ giữ 2 nhánh” hoặc “mỗi depth chỉ giữ 4
state”. Search dùng một priority queue toàn cục và frontier Pareto tại từng node.

## 2. Candidate discovery

Với mỗi label, planner tính `safe_range_km` từ SOC tối đa có thể dùng đến reserve:

```text
safe_range = (departure_soc - reserve_soc)
              * usable_capacity_kwh
              / effective_consumption
```

Station service chỉ được hỏi trong cửa sổ progress hiện tại đến
`progress + safe_range`. Ở node Origin, thêm `origin_radius_km` để không bỏ sót
trạm gần Origin khi projection lên polyline không chính xác.

Nguồn được chọn rõ ràng:

```text
OFFICIAL -> find_official_station_window()
RECOVERY -> find_recovery_station_window()
```

Recovery không được gọi trong planner official. Graph chỉ chuyển sang recovery
sau khi official search kết thúc mà không có plan, và không chuyển sang recovery
khi lỗi là rate limit hoặc provider unavailable.

### Backfill 24 -> 48 -> 96

Đây là ngân sách lấy detail từ station provider, không phải số station được chọn
cuối cùng:

```text
24 candidate detail đầu tiên
    nếu chưa đủ 12 candidate hợp lệ -> 48
    nếu vẫn chưa đủ -> 96
```

Sau merge/deduplicate, discovery cố gắng trả tối đa `TARGET_CANDIDATES = 12`.
Nếu provider chỉ có ít hơn 12 station phù hợp thì trả số thực tế; không bịa thêm.

## 3. Xếp hạng candidate trước khi gọi Goong

Điểm xếp hạng chỉ quyết định thứ tự kiểm tra. Nó không tự loại một candidate an
toàn đã được Goong xác minh.

Các tín hiệu hiện dùng, theo thứ tự:

1. `ACTIVE` trước trạng thái khác.
2. Candidate không phải dead-end.
3. Có thể tới destination bằng lower bound hình học hay không.
4. Số candidate ở phía trước còn có thể nối tiếp (`onward count`).
5. Progress: chặng đầu ưu tiên gần Origin để cứu SOC; chặng sau ưu tiên tiến về đích.
6. Detour nhỏ hơn.
7. Công suất sạc cao hơn.

`onward count` được tính bằng Haversine và full-charge safe range. Đây chỉ là
heuristic để ưu tiên, không phải bằng chứng route. Cạnh vẫn phải qua Goong và
Safety Gate.

## 4. Lazy edge validation

Mỗi candidate được thử bằng route thực tế:

```python
leg = routing_provider.get_route(current, candidate)
edge_soc_cost = estimate_soc_cost(leg.distance_km)
```

Candidate bị bỏ qua nếu Goong không trả route, connector không tương thích, station
đã đi qua/đi lùi, arrival SOC thấp hơn reserve, hoặc station trước không có đủ
công suất để tạo departure SOC cần thiết.

Khi label đã có station, charge transition dùng công suất của station cuối cùng.
Planner ước tính SOC rời trạm và thời gian sạc tối thiểu; itinerary cuối cùng vẫn
được mô phỏng lại bằng `EnergyTool` với số liệu chính xác hơn.

## 5. Nối thẳng tới destination

Planner dùng Haversine làm lower bound để quyết định khi nào đáng thử cạnh tới
destination:

```text
haversine(current, destination) <= safe_range
```

Không dùng `safe_range * 1.15`. Lower bound chỉ để quyết định gọi Goong; nó không
chứng minh an toàn. Goong route thực tế, detour và EnergyTool mới là quyết định
cuối cùng.

Nếu label tạo được plan hợp lệ tới destination, planner không thêm station khác
vào label đó. Điều này tránh các chuỗi sạc thừa.

## 6. Pareto dominance

Tại cùng một station, label A thống trị label B nếu A không tệ hơn B ở mọi tiêu
chí và tốt hơn ít nhất một tiêu chí:

```text
arrival SOC       cao hơn hoặc bằng
minimum SOC       cao hơn hoặc bằng
drive + charge    thấp hơn hoặc bằng
detour proxy      thấp hơn hoặc bằng
risk penalty      thấp hơn hoặc bằng
stop count        thấp hơn hoặc bằng
```

Sai số nhỏ được chấp nhận:

```text
SOC       0.5 percentage point
time      1 minute
detour    0.5 km
```

Label bị dominated không được đưa vào queue. Label không dominated vẫn được giữ,
kể cả khi chậm hơn nhưng có SOC hoặc khả năng nối tiếp tốt hơn.

## 7. Priority queue và ngân sách

Queue ưu tiên theo optimistic total time (drive + charge + Haversine còn lại), sau
đó risk penalty, detour proxy, minimum SOC và số stop. Haversine / 90 km/h chỉ là
lower bound để xếp thứ tự, không phải route time dùng để phê duyệt.

Ngân sách xác minh toàn request hiện tại là:

```text
MAX_EDGE_VALIDATIONS = 120
SEARCH_TIME_BUDGET   = 45 seconds
```

Mỗi label kiểm tra tối đa 8 candidate ưu tiên trước. Nếu cả nhóm đầu không tạo
được cạnh, planner mới mở rộng sang candidate còn lại trong cửa sổ. Đây là adaptive
validation, không phải cắt cố định toàn bộ search space.

Khi chạm edge budget hoặc time budget, planner trả
`routing_budget_exhausted = true` cùng `search_budget_reason`. Đây là kết quả cần
retry, không phải `SEARCH_EXHAUSTED` và cũng không phải infeasible.

## 8. Các trạng thái kết quả

```text
PLAN_CREATED / CONDITIONAL
    Có plan đã vượt Safety Gate.

SEARCH_EXHAUSTED
    Queue đã cạn hoặc đã duyệt hết phạm vi official hiện có nhưng chưa tìm được
    plan. Chưa đủ bằng chứng để nói hành trình bất khả thi.

PROVEN_INFEASIBLE
    Safety Gate chứng minh vi phạm không thể sửa trong điều kiện hiện tại, ví dụ
    SOC khởi hành dưới reserve.

ACTION_REQUIRED
    Provider unavailable hoặc Goong rate limit cần người dùng retry. Hết routing
    budget trả SEARCH_EXHAUSTED kèm lựa chọn retry.
```

Search bounded không được gắn nhãn `PROVEN_INFEASIBLE` chỉ vì không tìm thấy plan.

## 9. Sau khi tìm được plan

Các plan được deduplicate theo tuple station ID. Từ tập plan đã vượt Safety Gate,
hệ thống chọn tối đa ba phương án:

```text
BALANCED = thời gian + detour + biên SOC
FASTEST  = thời gian lái + thời gian sạc
SAFEST   = minimum SOC cao nhất
```

OpenAI chỉ có thể xếp hạng các plan feasible đã có sẵn. LLM không được tạo station,
route, SOC hay verdict.

## 10. Giới hạn và benchmark

12 là target discovery để kiểm soát latency, không phải chứng minh tối ưu toàn cục.
Chất lượng được bảo vệ theo chuỗi:

```text
lọc hình học rẻ
    -> ưu tiên connectivity/dead-end
    -> Goong lazy validation
    -> Pareto labels
    -> Safety Gate
```

Nên đo trên oracle offline:

- `Candidate Recall@K`;
- `Feasible Chain Recall`;
- số Goong calls và latency;
- regret so với plan tối ưu của oracle.

Các con số 12, 24, 48, 96 và 120 là policy/budget có version; chúng không phải
điều kiện toán học để kết luận infeasible.
