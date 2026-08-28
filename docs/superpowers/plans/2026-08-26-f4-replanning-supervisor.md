# F4 AI Replanning Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete F4 v2 policy-constrained replanning flow from monitoring events through a guarded AI supervisor to a confirmable, context-safe PlanVersion and auditable UI.

**Architecture:** Add isolated replanning domain/application/agent packages to the existing modular monolith. F3 supplies facts, F4 coordinates context and investigations, injected F1 computes deterministic candidates, and F2 owns transactional lifecycle; OpenAI structured output has a schema-compatible conservative fallback.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, LangGraph-compatible orchestration, OpenAI SDK, pytest, React 19, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-08-26-f4-replanning-supervisor-design.md`

## Global Constraints

- `docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md` overrides older F4 documents on conflict.
- Maximum 6 tool calls, 4 LLM turns, 1 structured-output retry per turn, 30-second soft budget, and 60-second hard deadline.
- OpenAI never creates route, station, telemetry, SOC, reachability, reserve, or feasibility facts.
- Missing/stale safety evidence fails closed; provider failure and exhausted search never become `INFEASIBLE`.
- One DecisionEpoch creates zero or one effective candidate; candidates always require owner confirmation.
- No chain-of-thought is persisted or displayed.
- Existing F1-F3 tests and public behavior remain compatible.

---

### Task 1: Replanning domain contracts and event coordination

**Files:**
- Create: `src/packages/contracts/replanning.py`
- Create: `src/packages/core/replanning/__init__.py`
- Create: `src/packages/core/replanning/domain/__init__.py`
- Create: `src/packages/core/replanning/domain/entities.py`
- Create: `src/packages/core/replanning/application/__init__.py`
- Create: `src/packages/core/replanning/application/event_coordinator.py`
- Modify: `src/packages/contracts/monitoring.py`
- Test: `tests/test_core/test_f4_event_coordinator.py`

**Interfaces:**
- Produces `ActiveConstraintContext`, `DecisionEpoch`, `TripContextSnapshot`, expanded `MonitoringEvent`, and `EventCoordinator.coordinate(events, current_context) -> CoordinationResult`.
- Event ordering key is `(occurred_at, source_sequence or max-int, received_at, event_id)`; duplicate IDs are ignored.

- [ ] Write failing tests proving four-event schema validation, event-time ordering, duplicate suppression, coalescing, late obsolete handling, station blacklist merging, and one epoch for three related events.
- [ ] Run `python -m pytest tests/test_core/test_f4_event_coordinator.py -q` and verify failures are missing F4 types/behavior.
- [ ] Implement immutable Pydantic/domain types and the minimal pure coordinator to pass.
- [ ] Re-run the focused tests and `tests/test_core/test_f3_monitoring.py`.
- [ ] Refactor ordering/constraint helpers while keeping both suites green.

### Task 2: Context manager, persistence models, and migration

**Files:**
- Create: `src/packages/core/replanning/application/context_manager.py`
- Create: `src/packages/core/replanning/infrastructure/__init__.py`
- Create: `src/packages/core/replanning/infrastructure/models.py`
- Create: `src/packages/core/replanning/infrastructure/repository.py`
- Create: `migrations/versions/20260826_1200_add_f4_replanning.py`
- Modify: `src/packages/core/trips/infrastructure/models.py`
- Modify: `src/packages/core/trips/domain/entities.py`
- Test: `tests/test_core/test_f4_context_manager.py`
- Test: `tests/test_core/test_f4_persistence.py`

**Interfaces:**
- Produces `TripContextManager.advance(trip_id, telemetry, events) -> TripContextSnapshot` and repository operations for events, epochs, contexts, runs, tools, diffs, and plan-event mappings.
- Plan version records gain `base_plan_version`, `context_version`, and legal F4 lifecycle statuses.

- [ ] Write failing tests for monotonic context versions, unresolved constraint carry-forward/removal, base-on-last-confirmed, pending-plan staleness, immutable snapshots, and repository round trips.
- [ ] Run both focused test modules and verify expected missing-model/service failures.
- [ ] Add SQLAlchemy models and an Alembic migration for all F4 tables and plan-version metadata.
- [ ] Implement transaction-scoped repository/context methods, including atomic stale marking.
- [ ] Run focused tests plus `tests/test_api/test_f2.py`; validate Alembic upgrade on a temporary SQLite database.

### Task 3: Supervisor schemas, fallback, and guards

**Files:**
- Create: `src/packages/agent/replanning/__init__.py`
- Create: `src/packages/agent/replanning/schemas.py`
- Create: `src/packages/agent/replanning/supervisor.py`
- Create: `src/packages/agent/replanning/openai_adapter.py`
- Create: `src/packages/agent/replanning/fallback.py`
- Create: `src/packages/agent/replanning/policy_guard.py`
- Create: `src/packages/agent/replanning/action_guard.py`
- Create: `src/packages/agent/replanning/state.py`
- Modify: `src/apps/api/bootstrap/config.py`
- Test: `tests/test_agents/test_f4_supervisor.py`
- Test: `tests/test_agents/test_f4_guards.py`

**Interfaces:**
- Produces validated `SituationAssessment`, `ToolDecision`, `ReflectionDecision`, `ActionProposalDraft`, `SupervisorPort`, `OpenAISupervisor`, and `ConservativeSupervisor`.
- `ToolPolicyGuard.validate(decision, state) -> GuardResult`; `ActionGuard.validate(draft, facts) -> GuardResult` never rewrites rejected input.

- [ ] Write failing tests for structured schemas, stale telemetry blocking all planning tools, mandatory blacklist propagation, dependency/allowlist/budget rejection, infeasible override rejection, and conservative fallback actions.
- [ ] Run focused tests and verify they fail because agent contracts do not exist.
- [ ] Implement schemas and pure guards first; run guards tests green.
- [ ] Implement OpenAI structured parsing with one retry and a dependency-injected client, plus deterministic fallback on missing key/timeout/invalid output.
- [ ] Run both modules and verify no test performs a network request or stores free-form reasoning.

### Task 4: Diagnostic loop, F1 adapter, projection, and plan diff

**Files:**
- Create: `src/packages/core/replanning/application/ports.py`
- Create: `src/packages/core/replanning/application/plan_projector.py`
- Create: `src/packages/core/replanning/application/plan_diff.py`
- Create: `src/packages/agent/replanning/orchestrator.py`
- Create: `src/packages/agent/replanning/tools.py`
- Modify: `src/packages/core/planning/application/orchestrator.py`
- Modify: `src/packages/core/trips/application/service.py`
- Modify: `src/packages/contracts/trips.py`
- Test: `tests/test_core/test_f4_plan_diff.py`
- Test: `tests/test_agents/test_f4_orchestrator.py`

**Interfaces:**
- Produces `ReplanningAgentOrchestrator.run(state) -> ReplanningOutcome`, `CurrentPlanProjector.project(...)`, and `PlanDiffEngine.compare(...)`.
- Extends `PlanningRequest` with `excluded_station_ids` and verifies every station discovery path honors it.

- [ ] Write failing tests for deterministic diff metrics, current-plan projection at the same snapshot, tool/turn budget stopping, typed observations, F1-only feasibility, and blacklist propagation to candidate generation.
- [ ] Run focused tests and confirm expected behavior failures, including the current discarded `excluded_station_ids` bug.
- [ ] Implement projection/diff as pure services and pass their tests.
- [ ] Implement the bounded supervisor loop and injected F1 tool adapter; preserve distinct insufficient-evidence/search-exhausted/infeasible outcomes.
- [ ] Run focused tests and all existing planning/energy/feasibility tests.

### Task 5: Replanning service, lifecycle, idempotency, and concurrency

**Files:**
- Create: `src/packages/core/replanning/application/service.py`
- Create: `src/packages/core/replanning/application/worker.py`
- Modify: `src/packages/core/trips/application/service.py`
- Modify: `src/packages/core/trips/infrastructure/sqlalchemy_repository.py`
- Modify: `src/packages/core/trips/infrastructure/sqlite_repository.py`
- Test: `tests/test_core/test_f4_replanning_service.py`
- Test: `tests/test_core/test_f4_lifecycle.py`

**Interfaces:**
- Produces `ReplanningService.submit(...)`, `process_epoch(...)`, `confirm_plan(...)`, `reject_plan(...)`, and worker atomic claim/lease methods.
- Confirm/reject consumes both `expected_plan_version` and `expected_context_version`.

- [ ] Write failing tests for F4-01 through F4-29 service scenarios, same-key idempotency, one candidate per epoch, new-context supersession, atomic double-confirm, owner enforcement, and worker retry/lease recovery.
- [ ] Run focused suites and verify missing-service/lifecycle failures.
- [ ] Implement event-to-context-to-run orchestration and audit persistence with transaction boundaries.
- [ ] Implement confirm/reject state machine and exact `409 PLAN_CONTEXT_CHANGED` behavior.
- [ ] Implement bounded worker claim/retry and run focused tests plus F2 regression tests.

### Task 6: Periodic SOC risk and monitoring integration

**Files:**
- Create: `src/packages/core/monitoring/domain/risk.py`
- Create: `src/packages/core/monitoring/application/periodic_risk.py`
- Modify: `src/packages/core/monitoring/application/service.py`
- Modify: `src/packages/core/policies/domain/entities.py`
- Modify: `src/packages/core/policies/infrastructure/models.py`
- Modify: `src/packages/core/policies/infrastructure/sqlalchemy_repository.py`
- Modify: `src/packages/contracts/monitoring.py`
- Test: `tests/test_core/test_f4_periodic_risk.py`

**Interfaces:**
- Produces `PeriodicRiskEvaluator.observe(sample, prior_state) -> SOCRiskState` with `NONE|WATCH|WARNING|EVENT` levels.
- Monitoring emits a canonical event only at `EVENT`; warning states never invoke replanning.

- [ ] Write failing F4-30 through F4-32 tests for declining residual warning, one-sample noise suppression, consecutive breach event, hysteresis recovery, and policy-sourced thresholds.
- [ ] Run focused tests and observe expected missing evaluator failures.
- [ ] Implement immutable risk state and pure evaluator, then integrate it into monitoring sessions.
- [ ] Run risk tests plus all F3 tests.

### Task 7: F4 API and application wiring

**Files:**
- Create: `src/apps/api/routes/replanning.py`
- Create: `src/packages/core/replanning/api/__init__.py`
- Create: `src/packages/core/replanning/api/dependencies.py`
- Modify: `src/apps/api/main.py`
- Modify: `src/apps/api/routes/trips.py`
- Modify: `src/apps/api/routes/monitoring.py`
- Test: `tests/test_api/test_f4.py`

**Interfaces:**
- Implements every endpoint in F4 spec section 33 and keeps the old plan-replan endpoint as a delegate.
- GET endpoints expose structured audit summaries; simulator event ingestion remains trusted/test-only.

- [ ] Write failing API tests for submit/poll/audit/events/epoch/context/diff/refresh/confirm/reject, authorization, validation, compatibility route, and status-code mapping.
- [ ] Run the focused API suite and verify route-not-found/behavior failures.
- [ ] Wire repositories, supervisor selection, F1 adapter, and ReplanningService through FastAPI dependencies.
- [ ] Implement routes with typed response models and error envelopes.
- [ ] Run all API tests and confirm compatibility clients still pass.

### Task 8: F4 UI and frontend integration

**Files:**
- Create: `src/apps/web/src/components/ReplanningSupervisorPanel.tsx`
- Create: `src/apps/web/src/components/PlanDiffPanel.tsx`
- Create: `src/apps/web/src/components/EventTimeline.tsx`
- Modify: `src/apps/web/src/lib/types.ts`
- Modify: `src/apps/web/src/lib/api.ts`
- Modify: `src/apps/web/src/components/TripMonitoringDashboard.tsx`
- Modify: `src/apps/web/src/App.tsx`
- Modify: `src/apps/web/src/styles.css`
- Test: `src/apps/web/src/components/ReplanningSupervisorPanel.test.tsx` if the existing frontend test runner supports it; otherwise type/build verification is mandatory.

**Interfaces:**
- Polls run/context/agent/diff endpoints and calls confirm/reject with expected versions.
- Displays only structured assessment/reason codes/tool observations, never chain-of-thought.

- [ ] Add failing component tests where supported, covering stale candidate controls, safety gate, tool trace, provider/search outcomes, and confirm/reject payloads.
- [ ] Extend frontend contracts and API functions, then make typecheck fail until components consume them correctly.
- [ ] Implement the event timeline, supervisor trace, provenance, active blacklist, old-vs-candidate diff, limitations, safety gate, and lifecycle controls.
- [ ] Integrate into the existing dashboard without removing F3 telemetry or current planning views.
- [ ] Run `npm run build` from `src/apps/web` and fix all TypeScript/build errors.

### Task 9: Full acceptance and hardening

**Files:**
- Create: `tests/test_api/test_f4_acceptance.py`
- Modify: `README.md`
- Modify: `.env.example` if present, otherwise document variables in `README.md`

**Interfaces:**
- Acceptance dataset maps F4-01 through F4-32 to explicit event, constraint, allowed/forbidden tool, action, and lifecycle assertions.

- [ ] Add any missing failing acceptance cases after mapping every catalog row to an automated test.
- [ ] Run focused acceptance tests and close only implementation gaps exposed by those failures.
- [ ] Document `OPENAI_REPLANNING_MODEL`, `OPENAI_REPLANNING_PROMPT_VERSION=f4-supervisor-v2`, budgets, fallback behavior, migration, and demo flow without exposing secrets.
- [ ] Run migration validation, full `pytest -q`, configured lint checks, and frontend `npm run build`.
- [ ] Run `git diff --check`, inspect `git status --short`, and report any unrelated user-owned changes without staging or reverting them.
