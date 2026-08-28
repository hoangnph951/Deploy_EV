# F1–F4 Closed-Loop Integration Design

**Date:** 2026-08-28  
**Status:** Approved in chat; awaiting written-spec review  
**Extends:** `docs/superpowers/specs/2026-08-26-f4-replanning-supervisor-design.md`

## Goal

Close the operational gaps between planning, confirmation, monitoring, and replanning so that F4 investigates canonical F3 events through a bounded multi-turn diagnostic loop, F2 is the mandatory plan-activation boundary, F3 accepts only confirmed plans, and the Vietnamese UI automatically starts and clearly explains each F4 decision.

## Product invariants

- Every F1 plan and F4 replacement plan starts as `PENDING`.
- Only an explicit owner action through F2 may change a pending plan to `CONFIRMED`.
- F3 must reject simulation start for a plan whose persisted status is not `CONFIRMED`.
- F3 canonical events automatically submit one F4 run. Re-renders, polling, and duplicate delivery must not create duplicate runs.
- F4 may call F1 only after completing the diagnostic prerequisites selected by the supervised loop and permitted by the deterministic tool guard.
- OpenAI may assess, choose an allowed next diagnostic step, reflect over typed observations, interpret trade-offs, and draft an action. It never determines route truth, energy feasibility, station availability, telemetry freshness, or final safety permission.
- The final action must pass deterministic feasibility, freshness, exclusion, evidence, context-version, and ownership guards.
- The UI exposes a concise decision audit, not hidden chain-of-thought or private model reasoning.

## Chosen architecture

Keep the existing modular-monolith boundaries and replace `ReplanningService`'s direct candidate call with a bounded supervisor runtime. The runtime alternates between a structured supervisor decision and a guarded diagnostic tool execution. Each tool produces a typed observation and audit summary; reflection decides whether evidence is sufficient, another tool is required, candidate construction is allowed, or the run must stop.

F3 remains the source of canonical monitoring facts. The web client reacts to a newly emitted canonical event and submits the corresponding telemetry and event payload to the existing idempotent F4 endpoint. The API remains authoritative for deduplication and lifecycle validation.

F2 remains the only activation boundary. Selecting a displayed journey changes only the candidate currently shown in the UI. It does not start F3. A separate explicit confirmation calls F2, refreshes the confirmed plan state, and only then enables simulation.

## Bounded diagnostic loop

### Runtime states

The runtime proceeds through these public stages:

1. `ASSESSING`: establish objective, urgency, known facts, constraints, and missing evidence.
2. `DIAGNOSING`: select and execute one allowed diagnostic tool.
3. `REFLECTING`: evaluate whether the new typed evidence supports or rejects the working safety hypothesis.
4. `BUILDING_CANDIDATE`: delegate candidate construction to the existing F1 planning boundary.
5. `COMPARING_PLANS`: compare the candidate with the remaining confirmed plan at the same telemetry snapshot.
6. `PROPOSING_ACTION`: draft an action from verified observations and deterministic comparison.
7. `GUARDING_ACTION`: apply deterministic safety and lifecycle checks.
8. Terminal: success, infeasible, insufficient evidence, search exhausted, timed out, failed, or superseded by newer context.

The loop permits at most four supervisor turns and six tool executions. One retry is allowed for invalid structured model output. Existing soft and hard time budgets remain authoritative. Reaching any budget terminates conservatively and never fabricates infeasibility.

### Diagnostic registry and dependency order

The guarded registry exposes focused operations:

- `inspect_telemetry`: validate snapshot identity, freshness, position, SOC, and required telemetry evidence.
- `project_current_plan`: project the remaining last-confirmed plan from the same verified telemetry snapshot.
- `inspect_route`: obtain deterministic route evidence for the current context.
- `inspect_stations`: validate relevant station evidence while preserving every active excluded station ID.
- `inspect_energy`: calculate deterministic reachability and reserve evidence.
- `build_f1_candidate`: invoke F1 with verified current state, confirmed base version, context version, and station exclusions.
- `compare_plans`: produce the deterministic difference between current-plan projection and candidate.

The guard enforces this minimum dependency chain:

```text
inspect_telemetry
  -> project_current_plan
  -> inspect_route / inspect_stations / inspect_energy as required by event and evidence gaps
  -> build_f1_candidate
  -> compare_plans
  -> propose and guard action
```

The exact diagnostic branches depend on the event set. Stale telemetry stops before planning. Station unavailability requires station exclusion evidence. SOC underperformance requires energy evidence. Route deviation requires route evidence. Coalesced events require the union of their evidence prerequisites.

### Supervisor protocol

The supervisor interface gains separate structured operations for initial assessment, next-step choice/reflection, and final action drafting. The OpenAI adapter receives only typed context and observations. The deterministic fallback implements the same interface with a conservative fixed diagnostic sequence.

Every loop iteration records:

- sequence number and public stage;
- selected tool and Vietnamese display label;
- purpose/reason codes;
- status, provider, freshness, and evidence references;
- reflection result, missing evidence, and next step.

No free-form chain-of-thought is stored, returned, logged, or rendered.

## F1, F2, and F3 lifecycle

F1 persists a generated feasible plan as `PENDING`. The planning screen may display and let the user select among pending alternatives, but selection is presentation state only.

The UI provides an explicit `Xác nhận hành trình` action for the selected persisted plan version. It calls the context-aware F2 confirmation endpoint. On success the UI records the returned `CONFIRMED` status, switches to tracking, and allows F3 simulation to start. Rejection leaves the trip inactive and simulation unavailable.

The F3 start endpoint validates the requested plan against persisted trip history and returns `409 PLAN_NOT_CONFIRMED` unless the exact version is `CONFIRMED`. This validation is server-side and cannot be bypassed by client state. If a newly confirmed plan supersedes an earlier confirmed plan, only the current confirmed version can start a new simulation.

F4 candidates follow the same lifecycle. A successful run exposes a pending candidate and comparison; it does not silently activate it. Owner confirmation through F2 makes it current. A newer canonical context stales an older pending candidate before it can be confirmed.

## Automatic F4 submission

`TripMonitoringDashboard` reports a newly observed canonical event to its parent through a typed callback. `App` automatically submits F4 when all of the following hold:

- the event type is not `NORMAL`;
- the event contains its canonical `event_id` and telemetry snapshot;
- no successful or in-flight submission exists for that event ID;
- a confirmed plan and trip are active.

The client stores submitted/in-flight event IDs for the current trip and resets them when the trip changes. A failed request remains visibly retryable through a Vietnamese `Thử phân tích lại` control. There is no normal-flow `Lập proposal mới` button.

The server's existing idempotency boundary remains the final protection against duplicate requests. Duplicate submissions return the original agent run.

## Feature 4 user interface

The F4 panel is a decision-audit timeline written for Vietnamese end users. Public section names are:

- `Tình huống được phát hiện`
- `Mục tiêu an toàn`
- `Các bước kiểm tra của trợ lý`
- `Bằng chứng đã thu thập`
- `Điều còn thiếu hoặc chưa chắc chắn`
- `So sánh hành trình hiện tại và phương án mới`
- `Kết luận an toàn`
- `Hành động đề xuất`

Machine values are mapped to Vietnamese labels. Examples include:

- `ASSESSING` → `Đang xác định tình huống`
- `CALL_TOOL` → `Tiếp tục kiểm tra dữ liệu`
- `SUPPORTED` → `Bằng chứng ủng hộ phương án`
- `UNCERTAIN` → `Chưa đủ bằng chứng để kết luận`
- `INSUFFICIENT_EVIDENCE` → `Chưa đủ dữ liệu an toàn`
- `FRESH` → `Dữ liệu còn hiệu lực`
- `PROPOSE_REPLAN` → `Đề xuất hành trình thay thế`

Raw reason codes may be retained in an optional technical-details disclosure for debugging, but the primary UI always shows Vietnamese explanations. Labels such as `Context`, `Base plan`, `Epoch events`, `Confidence`, `Tool sequence`, `Structured reflection`, `Safety Gate`, and `Action proposal` are removed from the primary view.

The UI may say which evidence was checked, what result was observed, why another check was necessary, and which safety rule allowed or blocked the action. It must not claim to show the model's private thoughts or reveal hidden chain-of-thought.

## Error and concurrency behavior

- Stale telemetry returns a telemetry-refresh action without calling F1.
- Provider failure remains `INSUFFICIENT_EVIDENCE`; search-budget exhaustion remains `SEARCH_EXHAUSTED`; neither becomes `INFEASIBLE`.
- Invalid or unavailable model output falls back to the conservative deterministic loop and remains audited.
- A context change during the loop supersedes the run and prevents candidate confirmation.
- Repeated canonical event delivery is idempotent by the existing trip, snapshot, plan-version, and event identity boundary.
- Auto-submit failure is visible and retryable; it never starts a second concurrent request for the same event.
- F2 confirmation uses expected plan and context versions and permits exactly one winner under concurrent requests.

## API and contract changes

`ReplanningOutcome` gains a public ordered decision trace containing stage records and reflection records. Existing `tool_runs` remains available for compatibility and persistence. Each trace item contains machine codes plus stable display data needed for Vietnamese rendering; the backend does not return model chain-of-thought.

Monitoring simulation state must expose canonical events with their authoritative IDs and matching telemetry snapshots. Simulation start requires an exact plan version and returns the plan-not-confirmed conflict described above.

The web API client adds explicit confirm/reject methods and uses the returned lifecycle state. Existing F4 submission continues through `POST /trips/{trip_id}/replans`.

## Testing strategy

Development follows red-green-refactor.

Backend unit tests prove:

- the loop executes multiple diagnostic/reflection turns before F1;
- event-specific prerequisites and tool order are guarded;
- stale evidence blocks F1;
- budgets terminate conservatively;
- fallback follows the same structured loop;
- final safety permission is deterministic;
- the public trace contains evidence and decisions but no chain-of-thought field.

API tests prove:

- unconfirmed F1 and F4 plans cannot start F3;
- F2 confirmation enables the exact plan version;
- stale context and concurrent confirmation still fail safely;
- duplicate F4 event submission returns one run;
- canonical monitoring output contains everything required for automatic submission.

Frontend tests or extracted pure-function tests prove:

- one automatic submission per canonical event ID;
- retry behavior after failure;
- simulation controls are disabled until confirmation;
- every primary F4 machine status renders as Vietnamese user-facing text;
- no legacy English section heading remains in Feature 4.

Final verification runs the focused Python suites, the full Python suite, frontend type/build checks, and any configured frontend tests without real provider calls.

## Scope exclusions

- Displaying hidden chain-of-thought or raw private model reasoning.
- Allowing OpenAI to override deterministic feasibility or lifecycle rules.
- Automatically confirming or activating a candidate.
- Replacing the current F1 planner, F2 persistence model, or F3 simulator with new subsystems.
- Introducing a new queue or external workflow engine solely for this integration.
