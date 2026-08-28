# F1–F4 Closed-Loop Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make F4 run a bounded multi-step diagnostic/reflection loop, automatically consume F3 canonical events, require F2 confirmation before F3 starts, and present the F4 decision audit in clear Vietnamese.

**Architecture:** Add a typed diagnostic runtime around the existing `ReplanningService`; deterministic tools and guards remain the safety authority while OpenAI or the conservative fallback chooses allowed next steps. Tighten the persisted plan lifecycle at the monitoring boundary, then connect a deduplicated event-driven frontend flow and a Vietnamese presentation mapper.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, React 18, TypeScript, Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-28-f1-f4-closed-loop-integration-design.md`

## Global Constraints

- Every F1 and F4 plan remains `PENDING` until its owner explicitly confirms it through F2.
- F3 accepts only the exact currently `CONFIRMED` persisted plan version.
- OpenAI never supplies route, energy, station, telemetry, feasibility, or final safety truth.
- F4 permits at most four supervisor turns, six tool calls, one structured-output retry per turn, a 30-second soft budget, and a 60-second hard deadline.
- Provider failure and search exhaustion never become deterministic infeasibility.
- Canonical events auto-submit once by event ID in the client and remain idempotent at the API boundary.
- The primary F4 UI uses Vietnamese explanations and never displays hidden chain-of-thought.

---

## File Structure

- Create `src/packages/core/replanning/application/diagnostics.py`: typed observations, diagnostic registry, event prerequisites, and deterministic tool implementations/adapters.
- Create `src/packages/core/replanning/application/supervisor_loop.py`: bounded assess/diagnose/reflect/candidate/compare/action state machine.
- Modify `src/packages/agent/replanning/schemas.py`: structured next-turn and public audit schemas.
- Modify `src/packages/agent/replanning/fallback.py`: conservative multi-turn supervisor protocol.
- Modify `src/packages/agent/replanning/openai_adapter.py`: separate structured assessment, reflection, and action turns.
- Modify `src/packages/agent/replanning/policy_guard.py`: dependency, allowlist, freshness, exclusion, and budget validation.
- Modify `src/packages/core/replanning/application/service.py`: coordinate context then delegate to the diagnostic loop.
- Modify `src/apps/api/routes/replanning.py`: wire the concrete diagnostic adapters and persist returned candidate lifecycle metadata.
- Modify `src/packages/core/monitoring/application/service.py`: resolve the persisted plan and reject non-confirmed versions before session creation.
- Modify `src/packages/contracts/monitoring.py`: require an exact plan identity/version and expose authoritative canonical event data.
- Modify `src/apps/web/src/lib/api.ts`: add F2 confirm/reject calls and send exact confirmed plan identity to F3.
- Modify `src/apps/web/src/lib/types.ts`: add decision trace, lifecycle response, and canonical event types.
- Create `src/apps/web/src/lib/replanningPresentation.ts`: exhaustive Vietnamese mappings and event-submission key helper.
- Modify `src/apps/web/src/App.tsx`: own selected/confirmed plan state and automatic F4 submission.
- Modify `src/apps/web/src/components/TripMonitoringDashboard.tsx`: emit canonical events, remove manual proposal flow, and show retry state.
- Modify `src/apps/web/src/components/ReplanningSupervisorPanel.tsx`: render the Vietnamese decision audit.
- Modify `src/apps/web/src/components/DashboardPanels.tsx`: replace journey selection/activation behavior with explicit confirmation UI.
- Modify `src/apps/web/src/styles.css`: style confirmation, audit timeline, evidence, and retry states.
- Add focused backend and frontend tests alongside the affected boundaries.

---

### Task 1: Typed Multi-Turn Diagnostic Runtime

**Files:**
- Create: `src/packages/core/replanning/application/diagnostics.py`
- Create: `src/packages/core/replanning/application/supervisor_loop.py`
- Modify: `src/packages/agent/replanning/schemas.py`
- Modify: `src/packages/agent/replanning/fallback.py`
- Modify: `src/packages/agent/replanning/policy_guard.py`
- Modify: `src/packages/core/replanning/application/service.py`
- Test: `tests/test_core/test_f4_supervisor_loop.py`
- Test: `tests/test_core/test_f4_replanning_service.py`
- Test: `tests/test_agents/test_f4_guards.py`

**Interfaces:**
- Consumes: `TripContextSnapshot`, `MonitoringEvent`, `TelemetrySnapshot`, existing `CandidatePlanner.build_candidate(**kwargs) -> dict`, and `PlanDiffEngine` output.
- Produces: `DiagnosticObservation`, `DecisionTraceItem`, `DiagnosticRegistry.execute(name, context)`, and `SupervisorLoop.run(...) -> LoopResult` used by `ReplanningService.process`.

- [ ] **Step 1: Read the test-quality rules before changing tests**

Read `C:\Users\Nguyen Ngoc Anh\.codex\plugins\cache\openai-curated-remote\superpowers\6.3.0\skills\test-driven-development\writing-good-tests.md` completely. For each new test, identify the production behavior whose removal would make that test fail.

- [ ] **Step 2: Write failing loop-order and event-prerequisite tests**

Add tests with a recording supervisor and recording registry:

```python
def test_soc_event_collects_telemetry_projection_and_energy_before_candidate():
    outcome = service_for("SOC_UNDERPERFORMANCE").process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("soc-1", "SOC_UNDERPERFORMANCE")],
    )
    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_telemetry", "project_current_plan", "inspect_energy",
        "build_f1_candidate", "compare_plans",
    ]
    assert len(outcome.decision_trace) >= 5


def test_station_event_preserves_exclusion_through_station_check_and_f1():
    planner = RecordingPlanner("FEASIBLE")
    outcome = service_for("STATION_UNAVAILABLE", planner=planner).process(...)
    assert planner.calls[0]["excluded_station_ids"] == ["station-closed"]
    assert "station-closed" in observation_for(outcome, "inspect_stations").facts["excluded_station_ids"]


def test_stale_telemetry_stops_before_projection_or_f1():
    outcome = service_for("STALE_TELEMETRY").process(...)
    assert outcome.status == "INSUFFICIENT_EVIDENCE"
    assert [run.tool for run in outcome.tool_runs] == ["inspect_telemetry"]
    assert outcome.candidate is None
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_replanning_service.py tests/test_agents/test_f4_guards.py -q
```

Expected: FAIL because `decision_trace`, the diagnostic registry, and multi-turn execution do not exist; the existing service calls only `build_candidate`.

- [ ] **Step 4: Add typed diagnostic and trace schemas**

Define schemas equivalent to:

```python
class DiagnosticObservation(BaseModel):
    tool: str
    status: Literal["SUCCEEDED", "BLOCKED", "FAILED"]
    facts: dict[str, object] = Field(default_factory=dict)
    freshness: str
    evidence_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class DecisionTraceItem(BaseModel):
    sequence: int
    stage: Literal[
        "ASSESSING", "DIAGNOSING", "REFLECTING", "BUILDING_CANDIDATE",
        "COMPARING_PLANS", "PROPOSING_ACTION", "GUARDING_ACTION",
    ]
    summary_code: str
    tool: str | None = None
    status: str
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
```

Do not add a `thoughts`, `reasoning`, `chain_of_thought`, or arbitrary model-prose field.

- [ ] **Step 5: Implement guarded diagnostic dependencies**

Implement an event prerequisite map:

```python
EVENT_DIAGNOSTICS = {
    "ROUTE_DEVIATION": ("inspect_route",),
    "SOC_UNDERPERFORMANCE": ("inspect_energy",),
    "STATION_UNAVAILABLE": ("inspect_stations",),
    "STALE_TELEMETRY": (),
}
```

Always require `inspect_telemetry` first and `project_current_plan` before non-stale candidate construction. Require the union for coalesced events. Update `ToolPolicyGuard` so `build_f1_candidate` is rejected until prerequisites have successful, fresh observations and active station exclusions are present in its arguments.

- [ ] **Step 6: Implement the bounded loop and conservative fallback**

Implement `SupervisorLoop.run` with explicit counters and elapsed-time checks. It must append one audit item per stage/tool/reflection, stop on blocked evidence, call F1 only after prerequisites, compare only after a candidate, and send the final draft through `ActionGuard`. The deterministic fallback uses the same registry and fixed prerequisite sequence; it does not bypass the loop.

- [ ] **Step 7: Verify GREEN and preserve outcome distinctions**

Run:

```powershell
python -m pytest tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_replanning_service.py tests/test_agents/test_f4_guards.py -q
```

Expected: PASS, including existing `INFEASIBLE`, `INSUFFICIENT_EVIDENCE`, and `SEARCH_EXHAUSTED` assertions.

- [ ] **Step 8: Commit the diagnostic runtime slice**

```powershell
git add src/packages/agent/replanning src/packages/core/replanning/application tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_replanning_service.py tests/test_agents/test_f4_guards.py
git commit -m "feat: run F4 bounded diagnostic loop"
```

---

### Task 2: Structured OpenAI Assessment, Reflection, and Action Turns

**Files:**
- Modify: `src/packages/agent/replanning/openai_adapter.py`
- Modify: `src/packages/agent/replanning/schemas.py`
- Modify: `src/packages/core/replanning/application/supervisor_loop.py`
- Test: `tests/test_agents/test_f4_supervisor.py`
- Test: `tests/test_core/test_f4_supervisor_loop.py`

**Interfaces:**
- Consumes: typed event/context payloads and `DiagnosticObservation` values from Task 1.
- Produces: `assess(...) -> SupervisorStructuredTurn`, `reflect(...) -> ReflectionDecision`, and `draft_action(...) -> ActionProposalDraft`; all have conservative fallback behavior.

- [ ] **Step 1: Write failing structured-turn tests**

Add a fake parsed-response client and assert three distinct calls:

```python
def test_openai_supervisor_reflects_after_each_typed_observation():
    supervisor = OpenAISupervisor(..., client=client_with_assessment_reflections_action())
    outcome = loop_with(supervisor).run(...)
    assert client.request_kinds == ["ASSESS", "REFLECT", "REFLECT", "DRAFT_ACTION"]
    assert all("chain_of_thought" not in payload for payload in client.payloads)


def test_invalid_reflection_retries_once_then_uses_conservative_fallback():
    supervisor = OpenAISupervisor(..., client=always_invalid_client())
    decision = supervisor.reflect(...)
    assert always_invalid_client.calls == 2
    assert decision.next_step in {"CALL_TOOL", "STOP_INSUFFICIENT_EVIDENCE"}
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_agents/test_f4_supervisor.py tests/test_core/test_f4_supervisor_loop.py -q
```

Expected: FAIL because `OpenAISupervisor` currently exposes only `assess`.

- [ ] **Step 3: Split the adapter into three schema-constrained operations**

Use operation-specific system/user payloads. Pass only facts, constraints, prior public decisions, observations, budgets, and allowed tools. Preserve `SYSTEM_PROMPT`'s prohibition on invented facts and add an explicit instruction to return decisions without hidden reasoning.

- [ ] **Step 4: Connect reflection output to the loop without granting safety authority**

Allow model-selected `next_tool` only if `ToolPolicyGuard` accepts it. If the model tries to build early, use a public blocked trace item and one correction opportunity; after that, fail closed. Always calculate the final feasibility status and action permission from deterministic observations and `ActionGuard`.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_agents/test_f4_supervisor.py tests/test_core/test_f4_supervisor_loop.py -q
```

Expected: PASS with assessment, repeated reflection, final drafting, retry, and fallback covered.

- [ ] **Step 6: Commit the OpenAI multi-turn slice**

```powershell
git add src/packages/agent/replanning/openai_adapter.py src/packages/agent/replanning/schemas.py src/packages/core/replanning/application/supervisor_loop.py tests/test_agents/test_f4_supervisor.py tests/test_core/test_f4_supervisor_loop.py
git commit -m "feat: add structured F4 reflection turns"
```

---

### Task 3: Enforce F2 Confirmation Before F3

**Files:**
- Modify: `src/packages/core/monitoring/application/service.py`
- Modify: `src/packages/contracts/monitoring.py`
- Modify: `src/apps/api/routes/monitoring.py`
- Modify: `src/apps/api/routes/replanning.py`
- Test: `tests/test_core/test_f3_monitoring.py`
- Test: `tests/test_api/test_f2.py`
- Test: `tests/test_api/test_f4.py`

**Interfaces:**
- Consumes: `SimulatorStartRequest.plan_id`, exact plan version, repository `get_plan_versions`, and F2 `confirm_plan` response.
- Produces: F3 conflict `AppError("PLAN_NOT_CONFIRMED", 409, ...)` and a context synchronized to the newly confirmed version.

- [ ] **Step 1: Replace obsolete xfail coverage with current lifecycle tests**

Add API tests using the existing context-aware endpoints:

```python
async def test_f3_rejects_pending_plan_until_f2_confirms_it(client):
    trip_id, plan = await create_trip_and_plan(client)
    blocked = await client.post(f"/api/v1/simulator/trips/{trip_id}/start", json=start_body(plan))
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PLAN_NOT_CONFIRMED"

    confirmed = await confirm_current_context(client, trip_id, plan["version"])
    assert confirmed.json()["status"] == "CONFIRMED"
    started = await client.post(f"/api/v1/simulator/trips/{trip_id}/start", json=start_body(plan))
    assert started.status_code == 200


async def test_f3_rejects_embedded_plan_that_is_not_the_confirmed_persisted_version(client):
    ...
    assert response.json()["error"]["code"] == "PLAN_NOT_CONFIRMED"
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run:

```powershell
python -m pytest tests/test_core/test_f3_monitoring.py tests/test_api/test_f2.py tests/test_api/test_f4.py -q
```

Expected: FAIL because `MonitoringSimulatorService.start` currently trusts an embedded pending proposal.

- [ ] **Step 3: Make persisted lifecycle state authoritative**

Resolve the exact persisted record for `plan_id` and version even when the request contains an embedded proposal. Reject missing, mismatched, stale, rejected, superseded, or pending records. Validate route/scenario only after confirmation validation succeeds.

- [ ] **Step 4: Synchronize F4 context after confirmation**

After `trip_service.decide_plan(..., "CONFIRMED")`, update the runtime context's `current_confirmed_plan_version` and clear the matching pending version. Preserve optimistic context checks and exactly-one concurrent winner behavior.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_core/test_f3_monitoring.py tests/test_api/test_f2.py tests/test_api/test_f4.py -q
```

Expected: PASS; pending plans cannot enter F3 and the exact confirmed version can.

- [ ] **Step 6: Commit the lifecycle slice**

```powershell
git add src/packages/core/monitoring/application/service.py src/packages/contracts/monitoring.py src/apps/api/routes/monitoring.py src/apps/api/routes/replanning.py tests/test_core/test_f3_monitoring.py tests/test_api/test_f2.py tests/test_api/test_f4.py
git commit -m "fix: require F2 confirmation before F3"
```

---

### Task 4: Automatic Canonical-Event Submission and Explicit Confirmation UI

**Files:**
- Modify: `src/apps/web/src/App.tsx`
- Modify: `src/apps/web/src/components/TripMonitoringDashboard.tsx`
- Modify: `src/apps/web/src/components/DashboardPanels.tsx`
- Modify: `src/apps/web/src/lib/api.ts`
- Modify: `src/apps/web/src/lib/types.ts`
- Modify: `src/apps/web/package.json`
- Modify: `src/apps/web/package-lock.json`
- Create: `src/apps/web/src/components/TripMonitoringDashboard.test.tsx`
- Create: `src/apps/web/src/lib/replanningSubmission.ts`
- Create: `src/apps/web/src/lib/replanningSubmission.test.ts`

**Interfaces:**
- Consumes: F2 confirm response, `SimulationState.events`, `TelemetrySnapshot`, and `submitF4Replan`.
- Produces: `canonicalEventKey(tripId, event)`, one in-flight/completed submission per key, and `confirmedPlanVersion` state controlling tracking/simulation.

- [ ] **Step 1: Add Vitest test support and write failing client-flow tests**

Add `vitest`, `jsdom`, and Testing Library development dependencies and a `test` script. Test the pure submission guard and dashboard behavior:

```ts
it("returns one stable key for repeated delivery of the same canonical event", () => {
  expect(canonicalEventKey("trip-1", event("event-1")))
    .toBe(canonicalEventKey("trip-1", event("event-1")));
});

it("automatically requests F4 once when a canonical event appears", async () => {
  renderDashboardWithTicks([canonicalState("event-1"), canonicalState("event-1")]);
  await waitFor(() => expect(onCanonicalEvent).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("Lập proposal mới")).not.toBeInTheDocument();
});

it("offers a Vietnamese retry after automatic submission fails", async () => {
  ...
  expect(await screen.findByRole("button", { name: "Thử phân tích lại" })).toBeVisible();
});
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
npm test -- --run
```

from `src/apps/web`.

Expected: FAIL because the automatic event callback, submission guard, and test setup do not exist.

- [ ] **Step 3: Add explicit plan confirmation state in `App`**

Add `confirmPlan(tripId, version, contextVersion)` to `lib/api.ts`. Track the selected pending proposal separately from `confirmedPlanVersion`. Change `onChooseJourney` to select only. Render `Xác nhận hành trình`; only a successful F2 response enables/switches to tracking. Reset confirmation state when a new trip or replacement candidate is generated.

- [ ] **Step 4: Replace manual F4 request with canonical-event callback**

Change dashboard props to receive `onCanonicalEvent(state, event)` and `planConfirmed`. When the newest canonical event changes, call the callback automatically. Use a ref/set keyed by trip and event ID to prevent duplicate in-flight or completed calls. On failure, remove only the failed in-flight marker and show `Thử phân tích lại`.

- [ ] **Step 5: Keep the API as final idempotency authority**

Make `App` submit the exact event and matching telemetry rather than reconstructing all historical events. Preserve `event_id`, timestamps, related plan version, station IDs, evidence, correlation, and snapshot ID. Do not call the simulator's `REQUEST_REPLAN` decision as a prerequisite for F4.

- [ ] **Step 6: Verify GREEN and build**

Run from `src/apps/web`:

```powershell
npm test -- --run
npm run build
```

Expected: tests PASS and TypeScript/Vite build completes without errors.

- [ ] **Step 7: Commit the frontend lifecycle slice**

```powershell
git add src/apps/web/src/App.tsx src/apps/web/src/components/TripMonitoringDashboard.tsx src/apps/web/src/components/DashboardPanels.tsx src/apps/web/src/lib/api.ts src/apps/web/src/lib/types.ts src/apps/web/src/lib/replanningSubmission.ts src/apps/web/src/components/TripMonitoringDashboard.test.tsx src/apps/web/src/lib/replanningSubmission.test.ts src/apps/web/package.json src/apps/web/package-lock.json
git commit -m "feat: auto-submit F4 events after confirmed plans"
```

---

### Task 5: Vietnamese Feature 4 Decision Audit

**Files:**
- Create: `src/apps/web/src/lib/replanningPresentation.ts`
- Create: `src/apps/web/src/lib/replanningPresentation.test.ts`
- Modify: `src/apps/web/src/components/ReplanningSupervisorPanel.tsx`
- Modify: `src/apps/web/src/lib/types.ts`
- Modify: `src/apps/web/src/styles.css`
- Test: `src/apps/web/src/components/ReplanningSupervisorPanel.test.tsx`

**Interfaces:**
- Consumes: `ReplanningOutcome.decision_trace`, tool runs, reflection, action, constraints, candidate, and plan diff.
- Produces: exhaustive `labelStage`, `labelStatus`, `labelAction`, `labelTool`, `explainReasonCode`, and the user-facing F4 timeline.

- [ ] **Step 1: Write failing mapping and rendering tests**

Cover every current union member and primary section:

```ts
it.each([
  ["ASSESSING", "Đang xác định tình huống"],
  ["DIAGNOSING", "Đang kiểm tra dữ liệu"],
  ["REFLECTING", "Đang đánh giá bằng chứng"],
  ["PROPOSING_ACTION", "Đang chuẩn bị đề xuất"],
])("translates %s", (code, expected) => expect(labelStage(code)).toBe(expected));

it("renders the Vietnamese decision audit without legacy English headings", () => {
  render(<ReplanningSupervisorPanel run={completeRun} />);
  expect(screen.getByText("Các bước kiểm tra của trợ lý")).toBeVisible();
  expect(screen.getByText("Kết luận an toàn")).toBeVisible();
  expect(screen.queryByText("Structured reflection")).not.toBeInTheDocument();
  expect(screen.queryByText("Tool sequence")).not.toBeInTheDocument();
  expect(screen.queryByText("Safety Gate")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify RED**

Run from `src/apps/web`:

```powershell
npm test -- --run src/lib/replanningPresentation.test.ts src/components/ReplanningSupervisorPanel.test.tsx
```

Expected: FAIL because mappings and the Vietnamese audit sections do not exist.

- [ ] **Step 3: Implement exhaustive presentation mappings**

Map stages, objectives, urgency, statuses, hypothesis states, next steps, action types, freshness, tool names, and known reason codes. Use an understandable Vietnamese fallback such as `Mã kỹ thuật: <code>` only inside a collapsed `Chi tiết kỹ thuật` section; never surface raw codes as the primary explanation.

- [ ] **Step 4: Rebuild the panel as an evidence-backed timeline**

Render these primary headings exactly: `Tình huống được phát hiện`, `Mục tiêu an toàn`, `Các bước kiểm tra của trợ lý`, `Bằng chứng đã thu thập`, `Điều còn thiếu hoặc chưa chắc chắn`, `So sánh hành trình hiện tại và phương án mới`, `Kết luận an toàn`, and `Hành động đề xuất`. Show sequence, purpose, observed result, freshness, and evidence reference for each step. Do not render any field resembling model thoughts.

- [ ] **Step 5: Add accessible states and responsive styling**

Use ordered list semantics for the decision timeline, visible status text in addition to color, `aria-live="polite"` for automatic analysis progress, and responsive wrapping for evidence/diff blocks.

- [ ] **Step 6: Verify GREEN and build**

Run from `src/apps/web`:

```powershell
npm test -- --run
npm run build
```

Expected: all frontend tests PASS and the production build succeeds.

- [ ] **Step 7: Commit the Vietnamese audit slice**

```powershell
git add src/apps/web/src/lib/replanningPresentation.ts src/apps/web/src/lib/replanningPresentation.test.ts src/apps/web/src/components/ReplanningSupervisorPanel.tsx src/apps/web/src/components/ReplanningSupervisorPanel.test.tsx src/apps/web/src/lib/types.ts src/apps/web/src/styles.css
git commit -m "feat: explain F4 decisions in Vietnamese"
```

---

### Task 6: End-to-End Regression and Documentation

**Files:**
- Modify: `tests/test_api/test_f4.py`
- Modify: `README.md`
- Modify: `docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: all completed backend and frontend interfaces.
- Produces: one acceptance scenario demonstrating confirmed F1 → F3 canonical event → automatic/idempotent F4 → pending replacement → F2 confirmation.

- [ ] **Step 1: Write the failing end-to-end API lifecycle test**

Add a deterministic test that creates F1 plan v1, confirms it, starts F3, advances until one canonical event is emitted, submits that event twice to F4, verifies one `agent_run_id`, verifies the replacement is pending, confirms it with the returned context, and proves the old version can no longer start a new simulation.

- [ ] **Step 2: Run the acceptance test and verify RED if any integration is missing**

Run:

```powershell
python -m pytest tests/test_api/test_f4.py -q
```

Expected before final integration fixes: FAIL at the first unconnected boundary. If it passes immediately, identify which lower-level test already proves each asserted transition and add only missing observable behavior.

- [ ] **Step 3: Make minimal integration fixes and update documentation**

Fix only failures exposed by the acceptance test. Document the confirmation-first flow, automatic F4 trigger, bounded diagnostic trace, Vietnamese terminology, and local test commands. Mark the four reported implementation gaps resolved in `WORKLOG.md` with test evidence.

- [ ] **Step 4: Run focused verification**

Run:

```powershell
python -m pytest tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_replanning_service.py tests/test_core/test_f3_monitoring.py tests/test_agents/test_f4_supervisor.py tests/test_agents/test_f4_guards.py tests/test_api/test_f2.py tests/test_api/test_f4.py -q
```

Expected: PASS with no unexpected warnings.

- [ ] **Step 5: Run complete backend verification**

Run:

```powershell
python -m pytest -q
python -m ruff check src tests
```

Expected: all tests and lint checks PASS. Investigate any failure instead of excluding it.

- [ ] **Step 6: Run complete frontend verification**

Run from `src/apps/web`:

```powershell
npm test -- --run
npm run build
```

Expected: all tests PASS and Vite creates the production bundle without TypeScript errors.

- [ ] **Step 7: Review the final diff for scope and secrets**

Run:

```powershell
git diff --check
git status --short
git diff --stat
git diff -- . ':!*.lock'
```

Confirm `.env`, API keys, generated build output, caches, and unrelated user files are absent.

- [ ] **Step 8: Commit the acceptance and documentation slice**

```powershell
git add tests/test_api/test_f4.py README.md docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md WORKLOG.md
git commit -m "docs: record closed F1-F4 workflow"
```
