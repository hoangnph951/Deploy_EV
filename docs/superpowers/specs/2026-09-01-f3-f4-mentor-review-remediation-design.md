# Thiết Kế Khắc Phục Các Case F3/F4 Trong Mentor Review

**Ngày:** 2026-09-01  
**Trạng thái:** F3/F4 remediation đã duyệt và triển khai; Evaluation section đã duyệt, chờ lập implementation plan
**Nguồn yêu cầu:** `mentor_feedback/review.md`  
**Phạm vi case:** Toàn bộ test có tiền tố `P210-F3-` hoặc `P210-F4-` đang có verdict `FAIL` hoặc `BLOCKED`

## 1. Mục tiêu

Đưa 15 case F3/F4 đang fail hoặc blocked về trạng thái có thể chạy lại một cách tất định trên live build, sửa hành vi sản phẩm thay vì làm yếu test, và tạo đủ bằng chứng để phân biệt:

- lỗi sản phẩm thực sự;
- case đã được sửa trong workspace nhưng chưa có trên live build mentor đã chấm;
- case bị block bởi precondition tạo hành trình có trạm;
- case chưa có fault-injection công khai để tái hiện provider failure.

Thiết kế này thay thế phần F3/F4 của `2026-08-31-mentor-review-test-reconciliation-design.md`. Phần F1/F2 trong tài liệu cũ vẫn giữ nguyên, ngoại trừ dependency F1 tối thiểu cần thiết để tạo một confirmed plan có trạm cho test F3/F4.

## 2. Baseline đã xác minh

Workspace hiện tại đã chạy thành công 120 test F3/F4 liên quan. Code hiện đã có:

- boundary values cho route deviation, SOC deficit và stale telemetry;
- pause, resume và reset;
- multi-event dùng chung telemetry snapshot;
- F4 semantic retry, reflection sau mỗi tool và fallback không dừng trước F1;
- candidate pending, compare plan, confirm/reject, stale-by-new-context và optimistic concurrency;
- ownership check trả 403 cho non-owner tại service hiện tại.

Khoảng trống còn lại ở cấp sản phẩm/live E2E:

1. Seed chưa do người dùng điều khiển và chưa hiển thị trong simulation state.
2. Hai case station không có precondition ổn định vì live planner trước đó lỗi trước khi tạo plan có trạm.
3. Không có fault injection có kiểu để tái hiện provider failure và proven infeasible trong cùng F4 flow.
4. Reject unsafe replan hiện xóa trạng thái UI thay vì giữ cảnh báo và lựa chọn dừng/hỗ trợ.
5. Các sửa đã có cần được khóa bằng E2E/API test rồi deploy đúng SHA để mentor retest.

## 3. Các phương án đã cân nhắc

### 3.1. Đồng bộ implementation hiện tại và bổ sung test seams có kiểm soát — chọn

Giữ nguyên thuật toán và policy an toàn. Bổ sung seed contract, simulation fault contract, station-bearing E2E precondition và reject lifecycle. Đây là phương án duy nhất vừa tái hiện được mọi case vừa không tạo endpoint mentor-only thiếu giá trị sản phẩm.

### 3.2. Chỉ deploy workspace hiện tại — loại

Phương án này giải quyết phần lớn blocker cũ nhưng vẫn không chạy được provider failure, không replay được cùng seed từ UI và có thể tiếp tục block station scenario nếu live F1 không tạo được plan có trạm.

### 3.3. Tạo endpoint hoặc dữ liệu giả chỉ dành cho mentor — loại

Nhanh nhưng làm sai ranh giới sản phẩm, có nguy cơ bịa một station không tồn tại trong confirmed plan và khiến F4 đánh giá sai remaining plan.

## 4. Phạm vi case và cách đóng

| Case | Trạng thái workspace | Cách đóng case |
|---|---|---|
| F3-EDGE-002 | Đã có boundary logic/UI | Khóa bằng API + UI regression, retest 1.99/2.00/2.01 |
| F3-EDGE-003 | Đã có boundary logic/UI | Khóa bằng API + UI regression, retest 4.9/5.0/5.1 |
| F3-HAPPY-004 | Còn phụ thuộc plan có trạm | Bảo đảm F1 tạo confirmed station-bearing plan; chạy outage đúng một lần |
| F3-EDGE-005 | Đã có boundary logic/UI | Khóa bằng API + UI regression, retest 60/61 và telemetry recovery |
| F3-EDGE-006 | Pause/resume/reset đã có; thiếu seed UI | Thêm seed contract/UI/state và replay cùng seed không nhân event |
| F4-HAPPY-001 | Agent loop đã sửa | E2E SOC event phải tạo candidate và plan diff |
| F4-HAPPY-002 | Còn phụ thuộc plan có trạm | E2E station blacklist phải tạo candidate không chứa station lỗi |
| F4-EDGE-003 | Multi-event đã có | E2E ba event, một epoch, một candidate |
| F4-UNHAPPY-005 | Thiếu fault injection | Thêm provider-failure và proven-infeasible simulation modes |
| F4-HAPPY-006 | Candidate/decision đã có | E2E pending diff, confirm/reject đúng version |
| F4-EDGE-007 | Lifecycle đã có | E2E context mới làm pending cũ thành stale và confirm trả 409 |
| F4-SEC-008 | Service hiện đã chặn non-owner | Thêm cross-user test cho cả generic plan endpoint và F4 endpoint, xác minh state bất biến |
| F4-AI-009 | Trace đã có | E2E multi-event kiểm tra strategy, tools, observations, reflections và guard |
| F4-AI-904 | Multi-event đã có | E2E station + SOC tạo một coherent candidate |
| F4-AI-905 | Reject có warning nhưng xóa UI state | Giữ AWAITING_DECISION, warning, nút dừng và hướng dẫn hỗ trợ |

## 5. Thiết kế F3 deterministic simulator

### 5.1. Seed contract

`SimulatorStartRequest.seed` tiếp tục là nguồn sự thật. Frontend thêm ô số seed với default ổn định, truyền seed vào `startSimulation`, và không tự thay bằng `Date.now()`.

`SimulationState` trả lại seed của session. UI hiển thị seed cạnh scenario và tốc độ. Reset giữ nguyên request gốc, bao gồm:

- scenario;
- scenario value;
- selected composite events;
- seed;
- speed multiplier.

Với cùng plan, seed và request, chuỗi telemetry/event phải giống nhau. Pause/resume không tăng tick khi paused. Reset xóa telemetry/events/count rồi chạy lại từ tick 0. Event deduplication tiếp tục dùng canonical batch key.

### 5.2. Boundary contract

Các ngưỡng an toàn không thay đổi:

- route deviation chỉ phát event khi `actual > 2.0 km`;
- SOC underperformance chỉ phát event khi `deficit > 5.0%`;
- stale telemetry chỉ phát event khi `age > 60 giây`.

UI giữ cả preset buttons và numeric input. Backend vẫn là authority quyết định event; UI không tự phân loại.

### 5.3. Station-unavailable precondition

Simulator không được tự thêm station vào một plan không có trạm. Test station phải bắt đầu từ một proposal đã được F1 tạo, lưu và confirm với ít nhất một charging stop.

Dependency F1 tối thiểu được phép sửa nếu live smoke còn lỗi:

- ánh xạ `CandidateStation.detail_quality`;
- timeout/error classification cho Open-Meteo;
- connector compatibility và station feasibility wiring;
- persistence/readback của station-bearing proposal.

Không thay công thức energy, reserve, station ranking hoặc feasibility. Một API E2E fixture dùng provider kiểm soát được sẽ bảo đảm test tự động không phụ thuộc mạng; live smoke dùng một route/SOC đã được ghi lại là tạo station thành công.

## 6. Thiết kế F4 orchestration

### 6.1. GPT và tool loop

GPT vẫn assess tình huống, chọn tool từ full event-specific allowlist, reflection sau mỗi observation rồi chọn tool kế tiếp. Không hard-code một thứ tự tool duy nhất cho mọi event.

Policy chỉ can thiệp khi lựa chọn schema-valid nhưng semantically invalid:

1. retry GPT với lỗi contract;
2. nếu vẫn invalid, chọn safe remaining tool;
3. không dừng trước F1/compare khi telemetry fresh và deterministic tools hoạt động.

Telemetry mô phỏng được dùng trực tiếp; không khôi phục `inspect_telemetry` hoặc GPS-validity tool. Telemetry thực sự stale vẫn fail-closed trước planning.

### 6.2. Multi-event coordination

Các event cùng telemetry snapshot được gửi trong một request, coordinate thành một epoch và giữ toàn bộ active constraints:

- route deviation;
- SOC underperformance;
- excluded station IDs.

F4 tạo tối đa một candidate cho epoch. Với station event, minimal substitution được thử trước full replan. Candidate phải qua F1 feasibility, plan comparison và ActionGuard rồi mới trở thành PENDING.

### 6.3. Fault injection có kiểu

Thêm field tùy chọn `simulation_fault` vào simulator request/state và replan submission với các giá trị:

- `NONE`;
- `F1_PROVIDER_FAILURE`;
- `F1_PROVEN_INFEASIBLE`.

Ràng buộc:

- chỉ chấp nhận khi telemetry source là `SIMULATED`;
- chỉ hoạt động khi `SIMULATOR_FAULT_INJECTION_ENABLED=true`;
- production mặc định false;
- không cho client truyền arbitrary exception/message/provider result.

Route replanning chọn một deterministic fault planner tại composition boundary; không cài nhánh fault vào thuật toán F1. Kết quả bắt buộc:

- provider failure → `INSUFFICIENT_EVIDENCE`/`ACTION_REQUIRED`, có retry guidance;
- proven infeasible → `PROVEN_INFEASIBLE`, có deterministic reason;
- hai outcome không dùng chung status hoặc user message.

### 6.4. Candidate lifecycle

Mỗi candidate gắn với base plan version và context version. Khi telemetry/base plan tạo context mới:

- pending cũ chuyển `STALE_BY_NEW_CONTEXT` nguyên tử;
- confirm/reject cũ trả 409;
- hai decision đồng thời chỉ một request thành công;
- non-owner nhận 403/404 trước mutation;
- owner state không đổi sau mọi request trái quyền.

### 6.5. Reject unsafe replan

Reject không tự áp dụng candidate và cũng không xóa simulation state. UI đánh dấu candidate đã bị từ chối, giữ F4 explanation, giữ simulator ở `AWAITING_DECISION` và hiển thị:

- cảnh báo plan hiện tại có thể không còn bảo đảm SOC/station constraint;
- nút dừng chuyến đi;
- hướng dẫn yêu cầu hỗ trợ.

Không cung cấp auto-continue sau reject. Continue chỉ được mở trong một flow riêng nếu deterministic safety evidence và ActionGuard xác nhận plan cũ còn an toàn.

## 7. Data flow

1. Người dùng chọn scenario, thresholds, seed, composite events và optional typed fault.
2. F3 backend lưu request trong session và trả authoritative `SimulationState`.
3. Tick tạo telemetry/events với source `SIMULATED`; boundary evaluator quyết định có phát event hay không.
4. Frontend gom các active events cùng snapshot và submit một F4 request.
5. F4 GPT/tool loop thu thập deterministic evidence, F1 tạo hoặc bác candidate, diff engine so sánh plan, ActionGuard kiểm tra action.
6. Candidate khả thi được lưu PENDING theo context/base version.
7. Confirm/reject/stale/ownership transitions xảy ra nguyên tử và UI tải lại authoritative state.

## 8. Error handling và safety

- Simulator input sai trả validation 422, không silently normalize thành case khác.
- Scenario station trên plan không có charging stop trả `STATION_REQUIRED` rõ ràng.
- Provider timeout/failure không được đổi thành infeasible.
- Invalid GPT tool choice không được làm mất active constraints hoặc chặn ngang flow fresh telemetry.
- Fault injection bị từ chối nếu source/config không hợp lệ.
- Mọi replan vẫn cần explicit owner confirmation; fault mode không được auto-apply plan.
- Evidence IDs vẫn tồn tại trong backend audit nhưng không render trên UI người dùng.

## 9. Chiến lược test

Triển khai theo TDD, từng nhóm có RED trước production change.

### 9.1. F3 tests

- unit table cho 1.99/2.00/2.01, 4.9/5.0/5.1, 60/61;
- service replay cùng seed;
- pause/resume/reset không nhân event;
- API trả seed và giữ request khi reset;
- station event đúng một lần, source `SIMULATED`;
- frontend presentation/input tests cho thresholds, seed và controls.

### 9.2. F4 tests

- SOC event tạo candidate/diff;
- station blacklist không xuất hiện trong candidate;
- route + SOC + station tạo một epoch/candidate;
- provider failure khác proven infeasible;
- stale context và concurrent decision trả 409 đúng contract;
- cross-user generic/F4 endpoints trả 403/404 và không mutation;
- reject giữ state/cảnh báo/dừng/hỗ trợ;
- trace có assess, tool observation, reflection, F1 build, compare và guard.

### 9.3. Verification gates

- toàn bộ F3/F4 backend suite;
- F2 ownership/decision tests liên quan shared plan endpoints;
- frontend tests, typecheck và production build;
- Ruff cho Python files thay đổi;
- migration check nếu có schema change;
- live smoke trên đúng deployment SHA;
- retest đủ 15 mentor IDs và lưu evidence mới.

## 10. Deliverables

1. Production changes và regression tests.
2. Cấu hình fault injection mặc định tắt trong `.env.example`.
3. Runbook route/SOC tạo confirmed station-bearing plan cho live retest.
4. Báo cáo mới `mentor_feedback/f3_f4_retest_20260901.md` chứa SHA, môi trường, từng verdict và evidence. Không ghi đè review gốc.

## 11. Ngoài phạm vi

- Các case F1/F2/XFLOW không trực tiếp block F3/F4 station precondition.
- Thay đổi công thức energy, reserve SOC, feasibility hoặc station ranking.
- Khôi phục station graph/catalog legacy không được test này yêu cầu.
- Thêm GPS-validity tool cho telemetry mô phỏng.
- Auto-apply hoặc auto-continue một replan chưa được owner xác nhận.

## 12. Điều kiện hoàn thành

- Cả 15 case F3/F4 đạt expected behavior và được ghi nhận `PASS`, không còn `FAIL` hoặc `BLOCKED`.
- External-provider failure được phân loại, timeout và recovery rõ ràng; không treo vô hạn và không cản bộ test dùng provider kiểm soát được.
- Full relevant backend/frontend suites pass trên SHA được deploy.
- Live retest report ghi nhận đúng SHA và không dùng mã nguồn cũ làm bằng chứng.

## 13. Evaluation

Evaluation là một deliverable có bằng chứng, không phải danh sách target tự khai báo. Mọi bảng kết quả phải ghi rõ commit SHA, thời điểm chạy, cấu hình máy, dataset version, runner version, model/prompt version và phân biệt `MEASURED` với `TARGET`. Không điền số giả cho metric chưa đo.

### 13.1. Golden dataset và cách thu thập

Tạo dataset versioned tại `eval/datasets/f3_f4_golden_v1.jsonl`. Mỗi record có:

```text
case_id, source, category, input_snapshot
expected_events, expected_constraints
required_tools, forbidden_tools
expected_outcome, expected_action, expected_lifecycle
ground_truth_method, label_notes, dataset_version
```

Nguồn mẫu gồm bốn cohort, tối thiểu 60 cases:

1. 15 remediation cases từ mentor review, dùng làm regression cohort và được ghi nhãn rõ là đã được dùng trong quá trình sửa lỗi.
2. Boundary cohort được sinh theo systematic cross-product quanh `2 km`, `5% SOC` và `60 giây`, gồm cả exact-boundary và just-above/below cases.
3. Failure/lifecycle cohort: provider failure, proven infeasible, stale telemetry, stale candidate, concurrent decision, ownership và unsafe reject.
4. Holdout cohort mới: thay route, SOC, event combinations và station position nhưng giữ cùng policy; không dùng để sửa prompt hoặc implementation trước lần benchmark đầu tiên.

Ground truth cứng đến từ deterministic oracle và executable assertions của F1–F4, không dùng LLM để tự tạo nhãn cho feasibility hoặc safety. Narrative labels dùng rubric cố định; 20% mẫu được human audit. Mọi thay đổi label tạo dataset version mới và lưu changelog. Báo cáo phải tách remediation-set score khỏi holdout score để tránh tuyên bố accuracy bị data leakage.

### 13.2. Accuracy metrics

Deterministic metrics được tính từ confusion matrix và exact contract matching:

- event precision, recall và F1 theo từng event type;
- `INFEASIBLE` precision/recall/F1; safety gate yêu cầu recall `100%` trên golden safety cases;
- final outcome/action exact-match;
- tool-selection precision/recall, required-tool recall và forbidden-tool violation rate;
- constraint preservation, one-epoch/one-candidate correctness;
- blacklist, stale-planning và cross-user mutation violation rate;
- plan lifecycle exact-match.

Các safety violation bắt buộc bằng `0`; không được che bằng macro-average tốt.

LLM-as-judge chỉ chấm phần diễn giải của agent theo rubric 1–5:

- groundedness vào typed observations;
- relevance với active event/constraint;
- completeness của limitation và uncertainty;
- action safety, không vượt deterministic evidence;
- clarity cho người dùng.

Judge chạy hai lượt độc lập trên cùng output với case ID ẩn, lưu judge model/prompt version và raw structured scores. Báo cáo gồm mean, median, pass rate (`mọi dimension >= 4`), weighted Cohen's kappa giữa hai lượt và kết quả human audit 20%. LLM-as-judge không thay thế deterministic safety metrics.

### 13.3. Performance và scalability benchmark

Benchmark local dùng workload cố định và ghi cấu hình CPU, RAM, OS, Python/Node, database, provider mode và model:

| Workload | CCU | Số mẫu mỗi mức | Metric |
|---|---:|---:|---|
| F3 tick/event API | 1, 5, 10, 20 | 200 | p50/p95/p99, throughput, error rate |
| F4 deterministic/fallback | 1, 5, 10, 20 | 40 | end-to-end latency, tool latency, error rate |
| F4 live LLM | 1 | tối thiểu 10 golden cases | latency, tokens, cost, fallback rate |

Mỗi workload có warm-up riêng; raw sample không trộn giữa các workload. Saturation point là mức CCU đầu tiên có một trong các dấu hiệu: error rate `>1%`, p95 lớn hơn `2×` baseline CCU 1, CPU duy trì `>85%`, hoặc memory tăng không ổn định. Local result chỉ chứng minh capacity trên cấu hình máy đã ghi, không suy rộng thành production capacity.

### 13.4. Availability, downtime và recovery

Vì benchmark chạy local một instance, không gọi kết quả là production uptime hay production HA. Đánh giá thực tế gồm:

- soak test 10 phút ở tải ổn định;
- observed request availability = expected successful responses / total requests;
- functional availability = responses giữ đúng safety contract / total requests;
- số error windows, tổng downtime quan sát được, longest downtime;
- recovery success rate và MTTR;
- fault windows cho LLM timeout, F1 provider failure và forced API restart.

Typed degraded outcomes như `INSUFFICIENT_EVIDENCE` được tính là functionally available nếu HTTP/contract đúng và fail-closed; timeout hoặc connection failure mới tạo downtime. Forced restart trên single-instance local dự kiến có downtime và không có automatic failover; số đo này phải được trình bày trung thực.

Hướng phát triển HA được ưu tiên theo evidence:

1. readiness/liveness probes và graceful shutdown;
2. ít nhất hai stateless API replicas sau load balancer;
3. tách durable worker queue cho planning/replanning;
4. PostgreSQL backup/replica và migration-safe rollout;
5. distributed idempotency/lease, circuit breaker và provider fallback;
6. rolling/canary deployment với SLO/error-budget monitoring.

### 13.5. Artifacts và phần trình bày

Evaluation tạo bốn artifact truy xuất được:

1. `eval/datasets/f3_f4_golden_v1.jsonl` — inputs và ground truth versioned.
2. Evaluation/load/soak runner — lệnh chạy tái lập được và raw JSON/CSV output.
3. `docs/evaluation/f3_f4_local_benchmark_20260901.md` — methodology, measured results, failures và limitations.
4. Slide `Evaluation Evidence` trong `presentation/README.md` — chỉ dùng số `MEASURED`, kèm dataset size, accuracy/safety, latency/CCU, observed availability/downtime và next HA step.

Pitch deck tăng từ 10 lên 11 slide; Evaluation Evidence đặt sau Architecture/Tech Stack và trước Traction. Slide phải nêu rõ “local benchmark, single instance” để không đánh đồng với production SLO.

### 13.6. Evaluation completion gate

- Golden dataset có schema validation, changelog và tách remediation/holdout cohort.
- Deterministic accuracy report có confusion matrix và zero-violation safety gates.
- LLM-as-judge có raw outputs, hai lượt chấm, agreement và human audit sample.
- Performance report có p50/p95/p99, throughput, error rate và saturation evidence theo CCU.
- Availability report có soak duration, downtime, MTTR, fault outcomes và giới hạn single-instance.
- Design, benchmark report và presentation dùng cùng dataset/result IDs; không có số liệu chỉ xuất hiện trên slide mà không truy được raw evidence.
