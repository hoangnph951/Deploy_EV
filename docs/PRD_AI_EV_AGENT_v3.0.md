# PRD — AI Agent lập kế hoạch chuyến đi và sạc pin cho Xe X

**Phiên bản:** 3.0  
**Ngày cập nhật:** 06/08/2026  
**Trạng thái:** Draft để xác thực với người dùng và sign-off  
**Primary persona:** Chủ xe Xe X đi đường dài

> Sản phẩm giúp chủ xe lập kế hoạch hành trình có điểm sạc, đánh giá tính khả thi, hiểu lý do của đề xuất và nhận phương án mới khi trạng thái chuyến đi thay đổi. AI Agent chỉ điều phối công cụ và giải thích. Sản phẩm MVP không điều khiển xe, không đọc SOC trực tiếp từ xe và không tuyên bố trạng thái trạm thời gian thực.

---

## 1. Problem statement

Khi chuẩn bị một chuyến đi dài bằng xe điện, chủ xe phải tự ghép thông tin từ bản đồ, mức pin, đặc tính xe, trạm sạc, đầu nối, công suất, thời gian dừng và mức pin an toàn tối thiểu. Các nguồn dữ liệu rời rạc và có độ mới khác nhau khiến người dùng khó xác định:

- Chuyến đi có thực sự khả thi không.
- Xe nên dừng ở trạm nào.
- Khi đến trạm hoặc đích sẽ còn bao nhiêu pin.
- Dữ liệu trạm có còn đáng tin không.
- Khi đi lệch tuyến, pin tụt nhanh hoặc trạm không dùng được thì cần thay đổi kế hoạch thế nào.

Sản phẩm phải hỗ trợ một hành trình khép kín:

```text
Lập kế hoạch
→ Giải thích và xác nhận
→ Theo dõi
→ Phát hiện thay đổi
→ Tái lập kế hoạch
→ Xác nhận lại
```

### Giả thuyết baseline cần kiểm chứng

Nhóm chưa có đủ evidence để khẳng định:

- Người dùng mất bao lâu để lập kế hoạch thủ công.
- Phải dùng bao nhiêu nguồn.
- Tần suất chọn sai trạm hoặc phải thay đổi kế hoạch.
- Mức độ người dùng hiểu các cảnh báo hiện tại.
- Pain point thực tế của hỗ trợ viên.

Trước khi PRD chuyển sang Approved, nhóm cần:

- Phỏng vấn 3–5 chủ xe điện có trải nghiệm đi đường dài.
- Quan sát hoặc ghi lại ít nhất 5 phiên lập kế hoạch.
- Thu thập thời gian hoàn thành, số nguồn sử dụng, lỗi thường gặp và cách xử lý hiện tại.
- Nếu giữ feature hỗ trợ viên, phỏng vấn ít nhất 1–2 người có vai trò hỗ trợ/tổng đài hoặc xác thực bằng tình huống thực tế.

### Pain points ưu tiên

| Pain point | Quy trình hiện tại → failure | Tác động | Root cause |
|---|---|---|---|
| Khó tạo một kế hoạch thống nhất | Người dùng mở bản đồ, xem SOC, tìm trạm và tự ước lượng → thông tin rời rạc | Mất thời gian; khó kiểm chứng; có thể chọn phương án không phù hợp | Không có workflow điều phối routing, energy, station và feasibility |
| Không biết kế hoạch có đủ an toàn | Dựa vào kinh nghiệm hoặc một con số tiêu hao → bỏ qua reserve SOC và sai số | Có thể đến trạm/đích dưới mức pin dự phòng hoặc không đến được | Thiếu công cụ deterministic kiểm tra feasibility |
| Trạm có thể không phù hợp hoặc dữ liệu đã cũ | Tìm theo vị trí nhưng không kiểm tra connector, freshness và nguồn | Kế hoạch sạc không thực hiện được | Metadata trạm chưa chuẩn hóa và thiếu provenance |
| Kế hoạch mất hiệu lực khi trạng thái thay đổi | Người dùng tự nhận biết lệch tuyến/pin tụt và lập lại thủ công | Phản ứng chậm, tăng rủi ro | Thiếu monitoring và event-driven replanning |
| Người dùng khó tin và kiểm soát đề xuất | Hệ thống chỉ đưa output mà không nêu lý do, giả định và phiên bản | Dễ áp dụng nhầm hoặc không dám dùng | Thiếu explanation, versioning và Human-in-the-Loop |
| Hỗ trợ viên phải hỏi lại toàn bộ trạng thái — giả thuyết | Chủ xe gọi hỗ trợ và kể lại vị trí, SOC, cảnh báo, plan | Hỗ trợ chậm và dễ hiểu sai | Không có read-only support view thống nhất |

Pain point hỗ trợ viên hiện là giả thuyết; feature tương ứng chỉ ở Should/P1.

---

## 2. Goals & metrics

Trong pilot với ít nhất 5 người dùng thử và benchmark được version hóa:

### Product goals

- Người dùng hoàn thành được hành trình từ nhập trip đến nhận và xác nhận plan.
- Người dùng thấy rõ route, charging stop, SOC dự kiến, risk và giả định.
- Khi có event, hệ thống tạo proposal mới hoặc cảnh báo không có phương án.
- Mọi trường dữ liệu quan trọng đều hiển thị nguồn và độ mới.

### Safety và correctness metrics

- **Infeasible recall = 100%**: không bỏ sót case thật sự `INFEASIBLE`.
- **Feasibility accuracy ≥ 95%**.
- **Valid charging plan rate = 100%**: mọi trạm trong plan phải tồn tại trong fixture/dataset, đúng connector, đạt reachability, reserve và freshness policy.
- **High-risk recall ≥ 95%**.
- **Hallucinated route/station facts = 0**.
- **100% station data stale/unknown** được gắn nhãn và không bị mô tả như availability thật.
- **100% plan thay đổi quan trọng** chỉ có hiệu lực sau khi đúng chủ xe xác nhận.

### Agent metrics

- Tool-selection accuracy ≥ 90%.
- Unnecessary tool-call rate ≤ 10%.
- Không gọi Agent/routing khi monitoring không phát hiện meaningful event.
- LLM không được làm ground truth cho feasibility.

### Performance

- Median replanning < 10 giây.
- p95 replanning < 30 giây.
- Hard timeout mục tiêu 60 giây.
- Quá timeout phải trả lỗi có mã, không treo vô hạn.

### Evaluation dataset

- **20 smoke cases**: chạy sau mỗi build.
- **Tối thiểu 60 benchmark cases**: mở rộng sau khi smoke set ổn định.
- Ground truth đến từ deterministic tools, fixtures và snapshot đã version hóa.
- Ground truth không phụ thuộc vào Map API hoặc station API live thay đổi giữa các lần chạy.

#### Phân nhóm smoke set đề xuất

| Nhóm | Số case tối thiểu | Ví dụ |
|---|---:|---|
| Happy path | 3 | Đi thẳng; cần một trạm; có nhiều trạm hợp lệ |
| Boundary | 3 | SOC vừa đủ; đúng 15%; trạm gần giới hạn detour |
| Invalid input | 3 | SOC ngoài khoảng; thiếu vị trí; connector không xác định |
| Safety | 4 | Dưới reserve; sai connector; stale station; infeasible |
| Replanning | 3 | Lệch tuyến; SOC tụt nhanh; simulated unavailable |
| Confirmation | 1 | Chưa confirm thì plan mới chưa có hiệu lực |
| Provider failure | 2 | Routing timeout; station provider lỗi |
| Explanation | 1 | Lý do chọn/loại phải khớp structured results |
| **Tổng** | **20** | |

Tỷ lệ benchmark 60 case sẽ được cố định trước lần đo chính thức.

---

## 3. Persona

### Primary persona — Chủ xe Xe X đi đường dài

- Dùng điện thoại hoặc trình duyệt web.
- Có thể biết SOC hiện tại và thao tác bản đồ cơ bản.
- Không bắt buộc hiểu mô hình năng lượng.
- Muốn biết chuyến đi có khả thi, nên sạc ở đâu và rủi ro là gì.
- Cần giữ quyền quyết định cuối cùng đối với thay đổi kế hoạch.

### Related role — Hỗ trợ viên

- Chỉ xem các chuyến đi được cấp quyền.
- Xem vị trí/SOC gần nhất, nguồn dữ liệu, freshness, cảnh báo, plan hiện hành và lịch sử replan.
- Giải thích/hướng dẫn cho chủ xe.
- Không sửa telemetry.
- Không tạo sự kiện giả.
- Không confirm/reject hoặc chỉnh plan thay chủ xe.

Feature hỗ trợ viên là Should/P1 và bị cắt đầu tiên nếu thiếu capacity hoặc chưa có evidence.

### System responsibility — Trip Service

Không phải persona. Đây là business boundary kiểm:

- Quyền sở hữu trip.
- Plan version.
- State transition.
- Safety references.
- Ghi dữ liệu nghiệp vụ.

Agent không được ghi trực tiếp PostgreSQL.

---

## 4. Input và data provenance

### 4.1 Input người dùng

| Input | Quy tắc MVP |
|---|---|
| Điểm đầu | Địa chỉ text hoặc tọa độ |
| Điểm cuối | Địa chỉ text hoặc tọa độ |
| SOC ban đầu | Số phần trăm hợp lệ; đề xuất 5–100% |
| Vehicle profile | Một profile Xe X cố định |
| Preference | `balanced` trong MVP; mode khác chỉ làm nếu còn capacity |

### 4.2 Giả định pilot

| Giả định | Giá trị MVP |
|---|---|
| Reserve SOC | 15% |
| Tải trọng | Profile danh định tương đương 2–3 người |
| Nhiệt độ | 25°C |
| Battery health | Profile version hóa đại diện xe đã sử dụng |
| Connector | Lấy từ VehicleProfile |
| Max charging power | Lấy từ VehicleProfile |
| Tốc độ | Route provider hoặc simulator profile |
| Địa hình | Route segments/elevation nếu có; nếu không dùng assumption công bố rõ |

**Reserve SOC 15%:**

- Cố định trong toàn bộ benchmark để so sánh được.
- Hiển thị trên UI.
- Được lưu cùng PlanVersion.
- Là configuration trong technical design.
- MVP chưa cho end-user tự chỉnh.
- Không được mô tả như khuyến nghị đúng cho mọi xe/chuyến đi.

### 4.3 Data provenance

| Trường | Nguồn MVP | Loại | Freshness/metadata | Benchmark |
|---|---|---|---|---|
| Origin/destination | Người dùng | `MANUAL` | `entered_at` | Fixture cố định |
| SOC ban đầu | Người dùng | `MANUAL` | `entered_at` | Fixture cố định |
| Vị trí hiện tại | GPS điện thoại | `REAL_GPS` | `updated_at`, age | Có thể thay bằng route fixture |
| Tuyến | Map API | `REAL_API` | provider, `updated_at` | Route snapshot |
| Metadata trạm | OCM/nguồn kiểm chứng | `REAL_API` hoặc `CACHED_SNAPSHOT` | source, `source_updated_at`, snapshot version | Station snapshot |
| SOC trong chuyến đi | Simulator | `SIMULATED` | scenario, tick, seed | Scenario cố định |
| Station availability event | Simulator | `SIMULATED` | event timestamp, scenario | Event timeline cố định |

### Quy tắc minh bạch

- UI và demo phải chỉ rõ `REAL`, `SIMULATED`, `CACHED`, `MANUAL`.
- Hiển thị thời điểm cập nhật và độ mới.
- Không tuyên bố đang theo dõi SOC thật.
- Không tuyên bố đang biết availability thật.
- Simulator phải chạy lại cùng scenario cho cùng timeline/input.
- Ground truth không dựa vào dữ liệu live.

---

## 5. Scope & priority

| Priority | Feature | Giá trị người dùng |
|---|---|---|
| **Must** | F1 — Lập kế hoạch trước chuyến đi | Biết trip có khả thi, đi tuyến nào, sạc ở đâu và risk là gì |
| **Must** | F2 — Giải thích và xác nhận kế hoạch | Hiểu đề xuất, giữ quyền quyết định và truy vết phiên bản |
| **Must** | F3 — Theo dõi chuyến đi mô phỏng | Biết trạng thái hiện tại đang bám sát kế hoạch hay không |
| **Must** | F4 — Tái lập kế hoạch | Nhận phương án mới khi kế hoạch cũ mất tính phù hợp |
| **Should** | F5 — Không gian hỗ trợ chuyến đi dạng chỉ đọc | Hỗ trợ viên hiểu nhanh tình trạng để hướng dẫn chủ xe |
| **Won't — MVP** | SOC thật từ xe/OEM API; live charger availability; điều khiển xe; mọi mẫu xe; end-user chỉnh reserve; chat/call/ticket; tự động confirm; production-grade dispatch | Giữ MVP có thể hoàn thành trong capacity |

---

## 6. Features & acceptance criteria

> Feature là phạm vi cam kết của PRD. User stories dùng để refinement; task kỹ thuật được phân rã trong backlog và Technical Design.

### F1 — Lập kế hoạch trước chuyến đi (Must)

**Pain point giải quyết:** người dùng khó kết hợp route, pin, trạm và feasibility thành một kế hoạch thống nhất.

#### User stories

1. Là chủ xe, tôi muốn nhập điểm đầu, điểm cuối và SOC để yêu cầu một kế hoạch.
2. Là chủ xe, tôi muốn thấy các giả định đang được áp dụng.
3. Là chủ xe, tôi muốn biết route, trạm, SOC dự kiến và mức rủi ro.
4. Là chủ xe, tôi muốn hệ thống từ chối phương án không đạt điều kiện an toàn.

#### Acceptance Criteria

```gherkin
Given người dùng nhập đủ origin, destination và SOC hợp lệ
When yêu cầu tạo plan
Then hệ thống tạo PlanRequest
And hiển thị các giả định gồm reserve SOC 15%, vehicle profile và nguồn dữ liệu
```

```gherkin
Given SOC trống, nhỏ hơn ngưỡng input hoặc lớn hơn 100%
When người dùng gửi yêu cầu
Then hệ thống trả lỗi validation rõ ràng
And không gọi Agent hoặc provider
```

```gherkin
Given địa chỉ có nhiều kết quả geocoding
When người dùng tạo plan
Then hệ thống yêu cầu chọn lại vị trí
And không tự đoán một địa điểm
```

```gherkin
Given input hợp lệ
When hệ thống lập kế hoạch
Then Routing phải hoàn thành trước
And Energy và Station chỉ được chạy sau khi có route segments/geometry
And Feasibility chỉ được chạy sau khi có Energy và Station results
```

```gherkin
Given một trạm sai connector hoặc không có connector xác định
When Station/Feasibility đánh giá candidate
Then trạm đó không được xuất hiện trong charging plan
And lý do loại được lưu trong structured result
```

```gherkin
Given SOC dự kiến tại trạm hoặc đích nhỏ hơn reserve SOC 15%
When Feasibility đánh giá
Then verdict là RISKY hoặc INFEASIBLE theo policy
And hệ thống không mô tả phương án đó là an toàn
```

```gherkin
Given không có phương án đạt feasibility
When Agent hoàn thành workflow
Then trả NoFeasiblePlan/INFEASIBLE
And không tạo charging plan giả
And UI hiển thị cảnh báo và giả định liên quan
```

```gherkin
Given station metadata đến từ cache/snapshot
When hiển thị trạm
Then UI hiển thị source, source_updated_at, snapshot_version và freshness
And không gọi đó là availability thời gian thực
```

```gherkin
Given routing provider timeout
When retry và fallback đều thất bại
Then trả ROUTING_UNAVAILABLE
And không tạo plan thiếu route
```

### F2 — Giải thích và xác nhận kế hoạch (Must)

**Pain point giải quyết:** người dùng khó hiểu, tin tưởng và kiểm soát đề xuất.

#### User stories

1. Là chủ xe, tôi muốn biết vì sao hệ thống chọn/loại tuyến hoặc trạm.
2. Là chủ xe, tôi muốn xác nhận hoặc từ chối plan.
3. Là chủ xe, tôi muốn plan cũ không bị ghi đè và có thể truy vết.

#### Acceptance Criteria

```gherkin
Given plan proposal được tạo
When UI hiển thị proposal
Then giải thích phải tham chiếu structured route, energy, station và feasibility results
And không bổ sung fact không có trong tool output
```

```gherkin
Given một proposal mới
When Trip Service lưu proposal
Then tạo PlanVersion ở trạng thái PENDING_CONFIRMATION
And chưa cập nhật current confirmed plan
```

```gherkin
Given đúng chủ xe xác nhận PlanVersion đang pending
When request confirm hợp lệ
Then plan chuyển CONFIRMED
And plan cũ chuyển SUPERSEDED nếu có
And thay đổi chỉ thành công sau DB commit
```

```gherkin
Given người không sở hữu trip
When cố confirm hoặc reject plan
Then hệ thống trả 403
And không thay đổi plan state
```

```gherkin
Given chủ xe từ chối proposal mới
When plan cũ vẫn feasible
Then proposal mới chuyển REJECTED
And plan cũ tiếp tục là current plan
```

```gherkin
Given chủ xe từ chối proposal mới
And plan cũ đã bị invalidated bởi safety
When hệ thống xử lý reject
Then không hiển thị plan cũ như phương án an toàn
And hiển thị cảnh báo khẩn cấp/NoFeasiblePlan
```

```gherkin
Given LLM provider lỗi
And deterministic tools vẫn tạo được structured plan
When tạo explanation
Then hệ thống dùng template explanation
And gắn nhãn explanation fallback
```

### F3 — Theo dõi chuyến đi mô phỏng (Must)

**Pain point giải quyết:** người dùng không biết trạng thái hiện tại có còn phù hợp với plan đã xác nhận không.

#### User stories

1. Là chủ xe, tôi muốn xem vị trí và SOC hiện tại.
2. Là chủ xe, tôi muốn biết dữ liệu nào thật và dữ liệu nào mô phỏng.
3. Là chủ xe, tôi muốn hệ thống chỉ kích hoạt Agent khi có thay đổi đáng kể.

#### Acceptance Criteria

```gherkin
Given chuyến đi đã có confirmed plan
When nhận GPS và SOC update
Then hệ thống lưu value, source_type, updated_at và freshness
```

```gherkin
Given vị trí từ GPS điện thoại
And SOC từ simulator
When hiển thị monitoring
Then vị trí có nhãn REAL_GPS
And SOC có nhãn SIMULATED
And UI không tuyên bố SOC được đọc từ xe
```

```gherkin
Given telemetry không vượt bất kỳ threshold nào
When Monitoring Service so sánh với confirmed plan
Then chỉ cập nhật trạng thái
And không gọi Agent, LLM hoặc routing
```

```gherkin
Given telemetry quá cũ theo configuration
When người dùng xem monitoring
Then hệ thống hiển thị STALE_TELEMETRY
And nêu thời điểm cập nhật cuối
```

```gherkin
Given cùng scenario_id, seed, route snapshot, station snapshot và configuration
When simulator chạy lại
Then chuỗi SOC/event và deterministic ground truth phải giống nhau
```

### F4 — Tái lập kế hoạch (Must)

**Pain point giải quyết:** kế hoạch cũ có thể mất tính phù hợp khi trạng thái chuyến đi thay đổi.

#### User stories

1. Là chủ xe, tôi muốn nhận plan mới khi đi lệch tuyến.
2. Là chủ xe, tôi muốn nhận cảnh báo khi SOC thấp hơn dự kiến.
3. Là chủ xe, tôi muốn có phương án thay thế khi trạm bị mô phỏng là không khả dụng.
4. Là chủ xe, tôi muốn xác nhận lại trước khi plan mới có hiệu lực.

#### Acceptance Criteria

```gherkin
Given Monitoring Service phát ROUTE_DEVIATION, SOC_UNDERPERFORMANCE hoặc SIMULATED_STATION_UNAVAILABLE
When Trip Service yêu cầu replan
Then Agent chạy Route
Then Energy và Station
Then Feasibility
```

```gherkin
Given event là SIMULATED_STATION_UNAVAILABLE
When hiển thị cảnh báo
Then UI ghi rõ đây là sự kiện mô phỏng
And không tuyên bố trạm ngoài đời đang hỏng
```

```gherkin
Given có phương án thay thế hợp lệ
When replan hoàn thành
Then tạo PlanVersion mới ở PENDING_CONFIRMATION
And plan mới chưa có hiệu lực trước confirm
```

```gherkin
Given không có phương án thay thế đạt reserve SOC và connector policy
When replan hoàn thành
Then trả NoFeasiblePlan
And không tạo phương án giả
```

```gherkin
Given map/station provider timeout hoặc dữ liệu thiếu field safety-critical
When fallback không đủ
Then fail closed với error code rõ ràng
And không áp dụng plan không đầy đủ
```

### F5 — Không gian hỗ trợ chuyến đi dạng chỉ đọc (Should/P1)

**Pain point giả thuyết:** khi chủ xe gặp sự cố và gọi hỗ trợ, nhân viên phải hỏi lại toàn bộ vị trí, SOC, cảnh báo và plan, làm xử lý chậm và dễ hiểu sai.

#### User stories

1. Là hỗ trợ viên, tôi muốn xem trạng thái của trip được cấp quyền.
2. Là hỗ trợ viên, tôi muốn xem lý do của plan/replan để giải thích cho chủ xe.
3. Là chủ xe, tôi muốn dữ liệu chuyến đi không bị lộ cho người không được cấp quyền.

#### Acceptance Criteria

```gherkin
Given hỗ trợ viên có SupportGrant hợp lệ
When mở trip
Then hệ thống hiển thị vị trí/SOC gần nhất, source label, freshness, cảnh báo, current plan và plan history
```

```gherkin
Given hỗ trợ viên không có SupportGrant
When truy cập trip
Then trả 403
And không để lộ sự tồn tại, vị trí, SOC hoặc plan history
```

```gherkin
Given plan đang PENDING_CONFIRMATION
When hỗ trợ viên xem trip
Then chỉ được đọc và giải thích
And không có quyền confirm, reject, sửa telemetry hoặc tạo simulated event
```

F5 bị cắt trước nếu thiếu thời gian hoặc pain point chưa được xác thực.

---

## 7. Non-functional requirements

### Safety

- Deterministic feasibility là nguồn quyết định.
- Agent không override `INFEASIBLE`.
- Missing field safety-critical phải fail closed.
- Không silent default ngoài versioned assumptions.
- Plan mới không tự động áp dụng.

### Data transparency

- 100% field quan trọng hiển thị source type.
- Hiển thị `updated_at` và freshness.
- Simulated/cached/manual data không được trình bày như live.
- Plan và benchmark lưu `scenario_id`, `snapshot_version`, `vehicle_profile_version`, `policy_version`.

### Reliability

- Retry giới hạn; không loop vô hạn.
- Tôn trọng `Retry-After` cho 429.
- Provider failure có error code rõ.
- Caching có versioned key.
- Idempotency cho create plan và confirm/reject.

### Performance

- Median replanning < 10 giây.
- p95 < 30 giây.
- Hard timeout 60 giây.
- Không gọi LLM/routing khi không có meaningful event.

### Security

- Xác thực người dùng.
- Chủ xe chỉ truy cập trip của mình.
- SupportGrant giới hạn theo trip và thời gian.
- Không đưa API key lên frontend.
- Giảm lưu precise location trong log.
- Agent không có DB write credential.

### Observability

- Trace mỗi AgentRun và ToolRun.
- Lưu selected tools, latency, retry count, error code và input hash.
- Dashboard tối thiểu: success rate, latency, unnecessary calls, provider errors.
- Không log secret hoặc vị trí chính xác nếu không cần.

### Reproducibility

- Simulator có `scenario_id`, seed và event timeline cố định.
- Benchmark dùng route/station snapshots.
- Ground truth được duyệt và version hóa trước khi đo.
- Không dùng dữ liệu live làm đáp án chuẩn.

---

## 8. Definition of Done

### Vertical slice — 08/08

Hoàn thành khi có thể demo:

```text
Nhập trip
→ tạo route
→ tìm ít nhất một trạm
→ kiểm tra feasibility/risk cơ bản
→ hiển thị route, trạm, SOC dự kiến và risk
```

Vertical slice có thể dùng model/fixture đơn giản nhưng phải chạy end-to-end, không chỉ là form nhập liệu.

### MVP Done

MVP done khi:

- F1–F4 đạt tất cả AC cấp feature.
- Người dùng hoàn thành được luồng:
  `create trip → plan → explain → confirm → monitor → event → replan → confirm/reject`.
- Dữ liệu real/simulated/cached/manual được gắn nhãn và có freshness.
- Reserve SOC 15% hiển thị rõ và được cấu hình.
- 20 smoke cases pass theo go/no-go bắt buộc.
- Benchmark set được chuẩn bị hoặc mở rộng theo kế hoạch 60 case.
- `INFEASIBLE` recall = 100%.
- Valid charging plan rate = 100%.
- Hallucinated facts = 0.
- Các contract chính đã chốt để FE/BE/Agent làm song song.
- Technical Design và architecture được review.
- F5 không bắt buộc để tính MVP Done.

---

## 9. Open questions

| Câu hỏi cần chốt | Owner đề xuất | Hạn |
|---|---|---|
| Baseline thực tế của chủ xe: thời gian, số nguồn, lỗi? | PO | Trước sign-off PRD |
| VehicleProfile Xe X dùng giá trị nào và nguồn nào? | Tech Lead | Trước freeze energy model |
| Ngưỡng route deviation và SOC underperformance? | PO + Tech Lead | Trước freeze simulator |
| Freshness policy cho station snapshot? | PO + Tech Lead | Trước smoke test |
| Ai review ground truth: mentor, tester hay domain reviewer? | PO | Trước freeze smoke set |
| Exact benchmark distribution của 60 case? | QA + Tech Lead | Sau khi 20 smoke ổn định |
| MVP Day và total team capacity? | Project Lead | Trước sprint planning |
| Có evidence đủ để giữ Support Workspace không? | PO | Trước khi bắt đầu F5 |
| Provider routing chính và fallback cuối cùng? | Tech Lead | Trước integration |
| Scope của fastest/lowest-cost có nằm trong MVP không? | PO | Trước sprint planning |

---

## 10. Sign-off

PRD chuyển từ Draft sang Approved khi đủ xác nhận:

| Vai trò | Phạm vi xác nhận | Người | Ngày | Trạng thái |
|---|---|---|---|---|
| Product Owner | Problem, persona, scope, priority, metrics | — | — | ☐ Chờ ký |
| Tech Lead | Feasibility, capacity, contract, NFR | — | — | ☐ Chờ ký |
| QA/Evaluation owner | Smoke set, benchmark plan, ground truth | — | — | ☐ Chờ ký |
| Mentor | Scope và cách đánh giá phù hợp kỳ vọng | — | — | ☐ Chờ review |
