# F3/F4 Mentor Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Làm cho toàn bộ 15 case F3/F4 đang FAIL/BLOCKED trong mentor review chạy tất định và đạt PASS trên đúng deployment SHA.

**Architecture:** Mở rộng simulator contract bằng seed và typed fault mode, giữ F3 làm nguồn telemetry/event mô phỏng và F4 làm supervisor trên deterministic evidence. Fault injection nằm tại composition boundary, không chèn nhánh test vào thuật toán F1; candidate lifecycle và reject UX tiếp tục dùng authoritative backend state.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, React 18, TypeScript, Node test runner, Vite.

**Spec:** `docs/superpowers/specs/2026-09-01-f3-f4-mentor-review-remediation-design.md`

## Global Constraints

- Không đổi công thức energy, reserve SOC, feasibility, station ranking hoặc các ngưỡng 2.0 km / 5.0% / 60 giây.
- GPT tiếp tục assess, reflection sau từng observation và chọn tool từ allowlist; không khôi phục `inspect_telemetry` cho GPS mô phỏng.
- Telemetry stale thật sự vẫn fail-closed trước F1.
- Fault injection chỉ nhận typed values, chỉ dùng với source `SIMULATED`, được chặn bằng config và mặc định tắt.
- Không tạo station giả trong một confirmed plan không có charging stop.
- Không auto-apply hoặc auto-continue một candidate chưa được owner xác nhận.
- Không ghi đè `mentor_feedback/review.md`; tạo báo cáo retest mới.
- Worktree đang có thay đổi hợp lệ từ các fix F4 trước đó; chỉ stage đúng file của từng task và không reset thay đổi ngoài phạm vi.

---

### Task 1: Seed deterministic xuyên suốt F3 contract, API và UI

**Files:**
- Modify: `src/packages/contracts/monitoring.py:29-49,164-180`
- Modify: `src/packages/core/monitoring/application/service.py:549-564`
- Modify: `src/apps/web/src/lib/types.ts:419-455`
- Modify: `src/apps/web/src/lib/api.ts:375-398`
- Modify: `src/apps/web/src/components/TripMonitoringDashboard.tsx:75-150,315-410`
- Modify: `tests/test_core/test_f3_monitoring.py`
- Modify: `tests/test_api/test_f4.py`
- Modify: `src/apps/web/src/lib/replanningPresentation.test.ts` or create `src/apps/web/src/lib/simulationControls.test.ts`

**Interfaces:**
- Consumes: `SimulatorStartRequest.seed: int` đã tồn tại.
- Produces: `SimulationState.seed: int`; `startSimulation(..., seed: number, ...)`; UI numeric seed input.

- [ ] **Step 1: Viết backend tests thất bại cho seed state và replay**

```python
def test_simulation_state_exposes_seed_and_reset_keeps_it():
    session = _scenario_session("ROUTE_DEVIATION", 2.01)
    session.request = session.request.model_copy(update={"seed": 210})
    service = _service_with_session(session)

    first = service.tick("trip-1", "owner-1")
    reset = service.reset("trip-1", "owner-1")

    assert first.seed == 210
    assert reset.seed == 210
    assert reset.tick_count == 0
    assert reset.events == []
```

Thêm API assertion `started.json()["seed"] == 210` và `reset.json()["seed"] == 210` trong `test_f3_active_simulator_exposes_pause_resume_and_reset_controls`.

- [ ] **Step 2: Chạy RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f3_monitoring.py tests/test_api/test_f4.py::test_f3_active_simulator_exposes_pause_resume_and_reset_controls
```

Expected: FAIL vì `SimulationState` chưa có field `seed`.

- [ ] **Step 3: Thêm seed vào authoritative state**

Trong `SimulationState`:

```python
seed: int
```

Trong `_state(session)`:

```python
seed=session.request.seed,
```

Không tạo seed mới khi pause/resume/reset.

- [ ] **Step 4: Viết frontend test thất bại cho payload builder**

Tách/export helper trong `api.ts`:

```ts
export function buildSimulationStartPayload(
  plan: PlanProposal,
  scenario: SimulationScenarioSelection,
  scenarioValue: number | undefined,
  scenarioEvents: CompositeMonitoringEventType[] | undefined,
  seed: number,
) {
  return {
    plan_id: plan.plan_id,
    plan,
    seed,
    scenario,
    scenario_value: scenarioValue,
    scenario_events: scenarioEvents,
    unhappy_probability: 0.5,
  };
}
```

Test với literal `seed: 210`; expected payload không chứa `Date.now()`-derived value.

- [ ] **Step 5: Chạy frontend RED**

Run:

```powershell
cd src/apps/web
node --experimental-strip-types --test src/lib/simulationControls.test.ts
```

Expected: FAIL vì helper/signature chưa tồn tại.

- [ ] **Step 6: Nối seed input vào UI và API**

Thêm state:

```ts
const [simulationSeed, setSimulationSeed] = useState(210);
```

Thêm numeric input `min={0}`, `step={1}`. Truyền seed vào `startSimulation`; hiển thị `Seed: {state.seed}` trong `monitor-source`. Cập nhật TS `SimulationState` với `seed: number`.

- [ ] **Step 7: Chạy GREEN và regression**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f3_monitoring.py tests/test_api/test_f4.py
cd src/apps/web
npm.cmd test
npm.cmd run build
```

Expected: tất cả pass.

- [ ] **Step 8: Commit task 1**

```powershell
git add src/packages/contracts/monitoring.py src/packages/core/monitoring/application/service.py src/apps/web/src/lib/types.ts src/apps/web/src/lib/api.ts src/apps/web/src/components/TripMonitoringDashboard.tsx tests/test_core/test_f3_monitoring.py tests/test_api/test_f4.py src/apps/web/src/lib/simulationControls.test.ts
git commit -m "feat: expose deterministic F3 simulation seed"
```

---

### Task 2: Khóa station-bearing plan precondition và station outage E2E

**Files:**
- Modify: `tests/test_api/test_planning.py`
- Modify: `tests/test_core/test_f3_monitoring.py`
- Modify: `tests/test_api/test_f4_candidate_planner.py`
- Modify: `tests/test_core/test_openai_station_search.py`
- Modify: `tests/test_core/test_environment_provider.py`
- Create: `docs/runbooks/f3_f4_station_scenario.md`

**Interfaces:**
- Consumes: F1 `PlanGenerationResponse` với persisted `PlanProposal.charging_stops`.
- Produces: repeatable fixture và live runbook cho confirmed plan có ít nhất một station.

- [ ] **Step 1: Viết characterization/E2E test cho station-bearing proposal**

Tạo controlled station provider fixture trả một station tương thích nằm trên route và yêu cầu SOC khiến direct route vi phạm reserve. Test phải thực hiện đủ create → generate → reload → confirm và assert:

```python
assert generated.status_code == 201
assert generated.json()["plan"]["charging_stops"]
assert reloaded_plan["charging_stops"][0]["station_id"] == "ST-CONTROLLED"
assert confirmed.json()["plan"]["status"] == "CONFIRMED"
```

- [ ] **Step 2: Chạy test station precondition**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_api/test_planning.py -k "station and confirmed"
```

Expected: PASS, xác nhận mismatch `detail_quality` trong review cũ không còn tồn tại trên workspace hiện tại. Nếu characterization này fail, dừng Task 2 và quay lại systematic debugging; không đoán sửa station algorithm.

- [ ] **Step 3: Khóa regression `detail_quality` và provider timeout**

Thêm assertions vào test hạ tầng hiện có: mọi `CandidateStation` từ catalog/search có `detail_quality` thuộc `VERIFIED|PARTIAL|UNVERIFIED`; Open-Meteo timeout tạo typed provider failure/ACTION_REQUIRED, không tạo proven infeasible. Đây là characterization của implementation hiện tại, không thay ranking/energy.

- [ ] **Step 4: Thêm F3 station event test đúng một lần**

```python
def test_station_outage_on_confirmed_station_plan_emits_once_with_simulated_source():
    state = run_station_session_to_completion_of_trigger()
    station_events = [e for e in state.events if e.event_type == "STATION_UNAVAILABLE"]
    assert len(station_events) == 1
    assert station_events[0].source == "SIMULATED"
    assert station_events[0].station_ids == ["ST-CONTROLLED"]
```

- [ ] **Step 5: Thêm F4 blacklist E2E**

Candidate từ station outage phải có `ST-CONTROLLED` trong excluded constraints và không có ID đó trong charging stops của candidate outcome.

- [ ] **Step 6: Viết live runbook**

Ghi origin/destination, SOC, vehicle, expected station, cách confirm, cách chạy `STATION_UNAVAILABLE`, expected event và candidate vào `docs/runbooks/f3_f4_station_scenario.md`.

- [ ] **Step 7: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_api/test_planning.py tests/test_core/test_f3_monitoring.py tests/test_api/test_f4_candidate_planner.py tests/test_core/test_openai_station_search.py tests/test_core/test_environment_provider.py
```

- [ ] **Step 8: Commit task 2**

Stage chỉ test, runbook và production files thực sự cần bởi RED; commit:

```powershell
git commit -m "test: make station outage flow reproducible"
```

---

### Task 3: Typed F4 fault injection tại composition boundary

**Files:**
- Modify: `.env.example`
- Modify: `src/apps/api/bootstrap/config.py:35-48`
- Modify: `src/packages/contracts/monitoring.py`
- Modify: `src/packages/contracts/replanning.py:62-65`
- Create: `src/packages/core/replanning/application/simulation_faults.py`
- Modify: `src/apps/api/routes/monitoring.py`
- Modify: `src/apps/api/routes/replanning.py:69-150,300-380`
- Modify: `src/apps/web/src/lib/types.ts`
- Modify: `src/apps/web/src/lib/api.ts`
- Modify: `src/apps/web/src/components/TripMonitoringDashboard.tsx`
- Create: `tests/test_core/test_f4_simulation_faults.py`
- Modify: `tests/test_api/test_f4.py`

**Interfaces:**
- Produces: `SimulationFault = Literal["NONE", "F1_PROVIDER_FAILURE", "F1_PROVEN_INFEASIBLE"]`.
- Produces: `SimulationFaultCandidatePlanner(delegate, fault)` implementing `project_remaining_plan` and `build_candidate`.
- Produces: `GET /api/v1/simulator/capabilities -> {"fault_injection_enabled": bool}`.

- [ ] **Step 1: Viết failing unit tests cho fault planner**

```python
def test_provider_failure_fault_is_insufficient_evidence():
    planner = SimulationFaultCandidatePlanner(delegate, "F1_PROVIDER_FAILURE")
    result = planner.build_candidate(strategy="FULL_REPLAN")
    assert result["feasibility_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["provider_status"] == "SIMULATED_PROVIDER_FAILURE"

def test_proven_infeasible_fault_is_not_provider_failure():
    planner = SimulationFaultCandidatePlanner(delegate, "F1_PROVEN_INFEASIBLE")
    result = planner.build_candidate(strategy="FULL_REPLAN")
    assert result["feasibility_verdict"] == "INFEASIBLE"
    assert result["reason_codes"] == ["SIMULATED_PROVEN_INFEASIBLE"]
```

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f4_simulation_faults.py
```

Expected: import/file missing.

- [ ] **Step 3: Implement wrapper, contract và config**

`project_remaining_plan` delegate nguyên trạng. `build_candidate` chỉ trả typed deterministic result cho hai fault modes; `NONE` delegate. Thêm:

```python
simulator_fault_injection_enabled: bool = False
```

và `.env.example`:

```dotenv
SIMULATOR_FAULT_INJECTION_ENABLED=false
```

- [ ] **Step 4: Viết API safety tests thất bại**

Các assertions bắt buộc:

```python
assert disabled_fault.status_code == 403
assert real_telemetry_fault.status_code == 422
assert provider_failure.json()["status"] == "INSUFFICIENT_EVIDENCE"
assert proven_infeasible.json()["status"] == "INFEASIBLE"
```

- [ ] **Step 5: Nối route composition**

Chỉ wrap `TripServiceCandidatePlanner` khi config bật, body fault khác `NONE` và telemetry source là `SIMULATED`. Không truyền fault xuống F1 service.

- [ ] **Step 6: Thêm capability endpoint và nối simulator UI**

`GET /api/v1/simulator/capabilities` đọc `Settings.simulator_fault_injection_enabled`. Frontend tải capability trước khi render form. Chỉ khi true mới hiện select “Kết quả F1 mô phỏng” với ba typed options. `SimulationState` giữ fault đã chọn; `submitF4Replan` gửi đúng field đó. Endpoint và fault request đều có API tests cho enabled/disabled.

- [ ] **Step 7: Chạy GREEN và regression**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f4_simulation_faults.py tests/test_core/test_f4_replanning_service.py tests/test_api/test_f4.py
cd src/apps/web
npm.cmd test
npm.cmd run build
```

- [ ] **Step 8: Commit task 3**

```powershell
git add .env.example src/apps/api/bootstrap/config.py src/packages/contracts/monitoring.py src/packages/contracts/replanning.py src/packages/core/replanning/application/simulation_faults.py src/apps/api/routes/monitoring.py src/apps/api/routes/replanning.py src/apps/web/src/lib/types.ts src/apps/web/src/lib/api.ts src/apps/web/src/components/TripMonitoringDashboard.tsx tests/test_core/test_f4_simulation_faults.py tests/test_api/test_f4.py
git commit -m "feat: add typed F4 simulator fault outcomes"
```

---

### Task 4: Reject unsafe replan không xóa decision state

**Files:**
- Modify: `src/apps/web/src/lib/f4Confirmation.ts`
- Modify: `src/apps/web/src/lib/f4Confirmation.test.ts`
- Modify: `src/apps/web/src/components/TripMonitoringDashboard.tsx:230-270,410-445`
- Modify: `src/apps/web/src/components/ReplanningSupervisorPanel.tsx`
- Modify: `src/apps/web/src/styles.css`

**Interfaces:**
- Produces: `completeF4Rejection(run, planId) -> { run, rejectedPlanId }`.
- Produces: `rejectedPlanId?: string` prop cho `ReplanningSupervisorPanel`.

- [ ] **Step 1: Viết failing rejection tests**

```ts
test("keeps the F4 run after rejecting an unsafe replacement", () => {
  const run = { agent_run_id: "run-1" };
  assert.deepEqual(completeF4Rejection(run as never, "plan-v2"), {
    run,
    rejectedPlanId: "plan-v2",
  });
});
```

Thêm assertion presentation rằng candidate bị từ chối không còn nút confirm/reject nhưng F4 explanation vẫn tồn tại.

- [ ] **Step 2: Chạy RED**

```powershell
cd src/apps/web
node --experimental-strip-types --test src/lib/f4Confirmation.test.ts
```

- [ ] **Step 3: Implement local rejected lifecycle**

Trong `rejectReplacementPlan`:

- không gọi `setState(null)`;
- không gọi `setF4Run(null)`;
- lưu `rejectedPlanId`;
- giữ simulator ở `AWAITING_DECISION`;
- đặt warning về SOC/station risk.

Panel nhận `rejectedPlanId`, disable decision actions và hiện “Phương án đã bị từ chối”.

- [ ] **Step 4: Giữ stop/assistance controls**

Khi state là `AWAITING_DECISION` sau reject, render nút `Dừng chuyến đi` gọi existing `decide("STOP")` và hướng dẫn yêu cầu hỗ trợ. Không tự gọi `CONTINUE`.

- [ ] **Step 5: Chạy GREEN/build**

```powershell
cd src/apps/web
npm.cmd test
npm.cmd run build
```

- [ ] **Step 6: Commit task 4**

```powershell
git add src/apps/web/src/lib/f4Confirmation.ts src/apps/web/src/lib/f4Confirmation.test.ts src/apps/web/src/components/TripMonitoringDashboard.tsx src/apps/web/src/components/ReplanningSupervisorPanel.tsx src/apps/web/src/styles.css
git commit -m "fix: preserve safety decision after F4 rejection"
```

---

### Task 5: Khóa các case F3/F4 đã sửa bằng API E2E

**Files:**
- Modify: `tests/test_api/test_f4.py`
- Modify: `tests/test_core/test_f4_supervisor_loop.py`
- Modify: `tests/test_core/test_f4_replanning_service.py`
- Modify: `tests/test_api/test_f2.py`
- Modify: `src/apps/web/src/lib/f4Confirmation.test.ts`

**Interfaces:**
- Consumes: seed/fault/station/reject contracts từ Tasks 1-4.
- Produces: executable coverage mapping cho mentor IDs.

- [ ] **Step 1: Thêm multi-event closed-loop test**

Test route + SOC + station cùng telemetry snapshot và assert:

```python
assert len(outcome.epoch.event_ids) == 3
assert len([r for r in outcome.tool_runs if r.tool.startswith("build_")]) == 1
assert outcome.candidate is not None
assert outcome.plan_diff is not None
assert outcome.action.requires_owner_confirmation is True
```

- [ ] **Step 2: Thêm trace completeness test**

Assert trace stages chứa `ASSESSING`, `DIAGNOSING`, `REFLECTING`, `BUILDING_CANDIDATE`, `COMPARING_PLANS`, `PROPOSING_ACTION`, `GUARDING_ACTION`; ít nhất một reflection có `response_source="OPENAI"` trong adapter test, còn API test mode được phép `SAFE_FALLBACK`.

- [ ] **Step 3: Thêm stale/concurrency tests**

Tạo PENDING F4 candidate, submit context mới, assert old status `STALE_BY_NEW_CONTEXT`, old confirm/reject 409. Hai confirm đồng thời phải trả `[200, 409]`.

- [ ] **Step 4: Thêm cross-user mutation tests**

User B gọi:

- `/api/v1/plans/{plan_id}/confirm`;
- `/api/v1/plans/{plan_id}/reject`;
- `/api/v1/trips/{trip_id}/plans/{version}/confirm`;
- `/api/v1/trips/{trip_id}/plans/{version}/reject`.

Mọi request trả 403/404; đọc lại bằng owner vẫn thấy PENDING/context không đổi.

- [ ] **Step 5: Chạy focused suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f3_monitoring.py tests/test_core/test_monitoring_service.py tests/test_agents/test_f4_supervisor.py tests/test_agents/test_f4_guards.py tests/test_core/test_f4_event_coordinator.py tests/test_core/test_f4_context_manager.py tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_runtime_store.py tests/test_core/test_f4_replanning_service.py tests/test_core/test_f4_plan_diff.py tests/test_core/test_f4_persistence.py tests/test_core/test_f4_periodic_risk.py tests/test_api/test_f4_candidate_planner.py tests/test_api/test_f4.py tests/test_api/test_f2.py
```

Expected: zero failures.

- [ ] **Step 6: Commit task 5**

```powershell
git add tests/test_api/test_f4.py tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_replanning_service.py tests/test_api/test_f2.py src/apps/web/src/lib/f4Confirmation.test.ts
git commit -m "test: cover F3 F4 mentor review scenarios"
```

---

### Task 6: Cập nhật tài liệu F3/F4 bắt buộc

**Files:**
- Modify: `docs/FEATURE_3_IMPLEMENT.md`
- Modify: `docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md`

**Interfaces:**
- Consumes: implementation và final test evidence từ Tasks 1-5.
- Produces: source-of-truth documentation đúng với runtime đã triển khai.

- [ ] **Step 1: Cập nhật FEATURE_3_IMPLEMENT.md**

Thêm mục “Mentor review deterministic controls — 2026-09-01” dưới simulator runtime/frontend/test sections, ghi chính xác:

- seed input/state/reset behavior;
- threshold presets và strict `>` semantics;
- pause/resume/reset replay;
- multi-event shared snapshot;
- station-bearing plan precondition;
- typed fault mode chỉ phục vụ simulator có config.

- [ ] **Step 2: Cập nhật FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md**

Thêm mục “Mentor review hardening — 2026-09-01” gần provider failure/acceptance catalog, ghi:

- GPT reflection + semantic retry + mandatory F1/compare behavior;
- typed provider failure vs proven infeasible;
- stale candidate/concurrency/ownership invariants;
- reject unsafe candidate giữ `AWAITING_DECISION` và không auto-continue;
- 15 mentor case IDs được ánh xạ tới tests.

- [ ] **Step 3: Kiểm tra docs không mâu thuẫn**

```powershell
rg -n "inspect_telemetry|GPS-validation|auto-apply|Date\.now\(\).*seed" docs/FEATURE_3_IMPLEMENT.md docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md
```

Expected: không có hướng dẫn khôi phục telemetry validation tool hoặc auto-apply; mọi mô tả cũ mâu thuẫn được sửa tại chỗ.

- [ ] **Step 4: Commit docs**

```powershell
git add docs/FEATURE_3_IMPLEMENT.md docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md
git commit -m "docs: record F3 F4 mentor review hardening"
```

---

### Task 7: Verification, live retest và báo cáo

**Files:**
- Create: `mentor_feedback/f3_f4_retest_20260901.md`

**Interfaces:**
- Consumes: deployed SHA, test outputs và screenshots/API evidence.
- Produces: authoritative 15-case PASS report không sửa review gốc.

- [ ] **Step 1: Chạy backend verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_core/test_f3_monitoring.py tests/test_core/test_monitoring_service.py tests/test_agents/test_f4_supervisor.py tests/test_agents/test_f4_guards.py tests/test_core/test_f4_event_coordinator.py tests/test_core/test_f4_context_manager.py tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_runtime_store.py tests/test_core/test_f4_replanning_service.py tests/test_core/test_f4_plan_diff.py tests/test_core/test_f4_persistence.py tests/test_core/test_f4_periodic_risk.py tests/test_core/test_f4_simulation_faults.py tests/test_api/test_f4_candidate_planner.py tests/test_api/test_f4.py tests/test_api/test_f2.py
```

- [ ] **Step 2: Chạy lint/frontend verification**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
cd src/apps/web
npm.cmd test
npm.cmd run build
```

- [ ] **Step 3: Deploy và xác minh SHA**

Đây là external mutation checkpoint: chỉ deploy khi người dùng cấp quyền/credentials cho môi trường live. Ghi commit SHA local, SHA live build và timestamp. Không retest nếu hai SHA không khớp. Nếu chưa được cấp quyền deploy, hoàn tất local verification và báo rõ Task 7 Steps 3-5 đang chờ external authorization; không giả lập live evidence.

- [ ] **Step 4: Retest đủ 15 case**

Chạy đúng boundary values, station route, multi-event, provider fault/proven infeasible, stale/concurrency, cross-user và reject unsafe. Mỗi case lưu expected, actual, HTTP/status, screenshot hoặc sanitized JSON.

- [ ] **Step 5: Viết báo cáo retest**

`mentor_feedback/f3_f4_retest_20260901.md` phải có bảng 15 IDs, tất cả verdict `PASS`, deployment SHA và link evidence. Không sửa `mentor_feedback/review.md`.

- [ ] **Step 6: Final diff audit**

```powershell
git diff --check
git status --short
```

Xác nhận không có secret, generated build asset hoặc unrelated user file trong diff.

- [ ] **Step 7: Commit retest report**

```powershell
git add mentor_feedback/f3_f4_retest_20260901.md
git commit -m "docs: record F3 F4 mentor retest evidence"
```
