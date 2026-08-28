# F4 AI Replanning Supervisor Design

**Date:** 2026-08-26  
**Status:** Approved  
**Source of truth:** `docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md`

## Goal

Implement F4 as a policy-constrained AI replanning subsystem that consumes F3 monitoring events, coordinates concurrent context changes, investigates through guarded deterministic tools, delegates candidate calculation to F1, and submits confirmable plan versions through F2 lifecycle rules. OpenAI is used when configured; an equivalent conservative deterministic fallback preserves every safety invariant when the model is unavailable.

## Authority and scope

`FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md` overrides older F4 backlog, PRD, and architecture text when they conflict. The implementation covers the four canonical events, multi-event coordination, context continuity, pending-plan races, provider and LLM failures, proactive SOC risk, audit persistence, required APIs, and the F4 operator UI.

The existing F1 planner, F2 trip lifecycle, and F3 simulator remain supported. Compatibility endpoints may remain, but their behavior must enter the same F4 application boundary.

## Chosen approach

Use vertical slices on the current modular monolith. Add focused `core/replanning` and `agent/replanning` packages, reuse the injected `PlanningOrchestrator`, and connect existing monitoring and trip services through explicit application ports. Deliver foundation, supervisor, lifecycle, API, UI, and hardening as independently tested slices.

Rejected alternatives:

- A big-bang scaffold would defer integration feedback and make safety failures difficult to isolate.
- Adding F4 logic directly to `MonitoringSimulatorService` or `TripService` would mix F3/F4/F2 ownership and undermine auditability.

## Architecture

```text
F3 MonitoringEvent
    -> EventCoordinator -> DecisionEpoch
    -> TripContextManager -> immutable TripContextSnapshot
    -> ReplanningService -> AgentRun
    -> AI Supervisor <-> ToolPolicyGuard <-> deterministic diagnostic tools
    -> F1 PlanningOrchestrator -> candidate
    -> CurrentPlanProjector -> PlanDiffEngine
    -> AI ActionProposal -> ActionGuard -> ContextVersionGuard
    -> TripService transaction -> PENDING PlanVersion
    -> owner confirm/reject
```

F4 code lives under `src/packages/core/replanning` and `src/packages/agent/replanning`. F4 depends on the F1 `PlanningOrchestrator` protocol through injection and never imports a mutable global planning agent. The API layer performs authentication and delegates business writes to application services.

## Ownership and safety boundary

- F3 owns telemetry facts, threshold detection, risk state, and canonical event creation.
- Event coordination owns validation, event-time ordering, deduplication, coalescing, obsolescence, and epoch creation.
- Context management owns monotonic `context_version`, latest confirmed base plan, pending-plan staleness, and unresolved constraint carry-forward.
- OpenAI owns only structured assessment, strategy, allowed next-tool selection, reflection, trade-off interpretation, and action drafting.
- Deterministic providers and F1 own route geometry, station truth, energy/SOC, reachability, reserve margin, and feasibility.
- Guards enforce allowlists, evidence freshness, blacklist propagation, budgets, context consistency, and permitted actions.
- F2/TripService owns transactional persistence, plan status changes, and owner confirm/reject.
- The owner remains the only authority that confirms a candidate.

Missing or stale safety-critical evidence fails closed. Provider failure and search exhaustion are never converted to `INFEASIBLE`. No chain-of-thought is persisted or displayed.

## Domain and persistence

Introduce database-backed records for monitoring events, decision epochs and their event mapping, trip context snapshots, agent runs and event mapping, tool runs, planning runs, plan diffs, and plan-version event mapping. Existing plan-version persistence gains base/context metadata and the states `CONFIRMED`, `REJECTED`, `SUPERSEDED`, `INVALIDATED_BY_SAFETY`, and `STALE_BY_NEW_CONTEXT` in addition to `PENDING`.

`MonitoringEvent` carries `occurred_at`, `received_at`, optional `source_sequence`, telemetry snapshot, related plan version, severity, evidence refs, correlation/causation IDs, and affected station IDs. Event ordering uses occurrence time and sequence rather than receipt time alone.

A `DecisionEpoch` groups related events for the same trip and authoritative context. Its invariant is N events to one agent run to zero or one effective candidate. The idempotency key is `(trip_id, decision_epoch_id, telemetry_snapshot_id, context_version, base_plan_version)`.

`TripContextSnapshot` is immutable. Each accepted context change increments the version and carries active constraints until newer deterministic evidence resolves them. A new context atomically marks an older pending candidate `STALE_BY_NEW_CONTEXT`. A new candidate always bases on the last confirmed plan, never an unconfirmed candidate.

## Event coordination and proactive monitoring

The coordinator validates trusted event input, deduplicates by event ID, orders by event time, coalesces within the configured window, classifies late events as obsolete or still relevant, and seals epochs for execution. It selects no business action.

SOC risk evaluation maintains residual, slope, consecutive negative samples, consecutive breaches, and warning level. Thresholds, debounce, and hysteresis live in policy configuration rather than prompts. Warnings do not invoke F4; canonical events do.

## Supervisor runtime

The OpenAI adapter returns validated structured schemas for `SituationAssessment`, `ToolDecision`, `ReflectionDecision`, and `ActionProposalDraft`. A run is bounded to four model turns, six tool calls, one structured-output retry per turn, a 30-second soft budget, and a 60-second hard deadline.

The diagnostic registry exposes projection, routing, energy, station, telemetry, candidate construction through F1, and plan comparison. `ToolPolicyGuard` checks allowlist, dependency order, telemetry freshness, active station exclusions, remaining budget, schema, and provenance before execution. Typed observations feed reflection without exposing chain-of-thought.

When OpenAI is missing, times out, or returns invalid output after retry, a deterministic conservative supervisor produces the same output schemas. It may request telemetry, preserve a proven-safe current plan, or run a fixed safe diagnostic path, but cannot create safety facts.

## Candidate, comparison, and action

Candidate creation passes current verified telemetry and all active excluded station IDs into F1. F1 remains the sole feasibility authority. `CurrentPlanProjector` evaluates the remaining confirmed plan at the same telemetry snapshot. `PlanDiffEngine` deterministically compares distance, duration, SOC/reserve, charging stops, and route changes.

The final supervisor turn interprets the diff and drafts an action. `ActionGuard` either accepts the exact action or rejects it with reason codes; it does not silently rewrite the action. One correction is allowed. `ContextVersionGuard` prevents persistence when the run has been superseded.

Outcomes remain distinct: `SUCCEEDED`, `INFEASIBLE`, `INSUFFICIENT_EVIDENCE`, `SEARCH_EXHAUSTED`, `FAILED`, `TIMED_OUT`, and `SUPERSEDED_BY_NEW_CONTEXT`. Assistance is proposed only after deterministic proof that no feasible plan exists.

## Lifecycle and concurrency

Plan confirm/reject requires ownership plus `expected_plan_version` and `expected_context_version`. The transaction validates pending status and current context and ensures exactly one concurrent confirmation succeeds. A context mismatch returns `409 PLAN_CONTEXT_CHANGED` and stales the candidate. Confirm supersedes the previous confirmed version; reject preserves it unless deterministic policy has already proven it unsafe.

Workers claim queued planning runs atomically with a lease, bounded retry, and idempotent lookup. A context change during execution supersedes the old run and prevents a confirmable proposal from being persisted.

## API compatibility

Implement the F4 endpoints described in the source spec for replans, planning runs, agent runs, events, epochs, context, diffs, confirm/reject, and telemetry refresh. The existing `/api/v1/trips/{trip_id}/plans/replan` route remains temporarily but delegates to `ReplanningService`; it must propagate station exclusions rather than discard them.

Public clients cannot authoritatively declare event type, trip ownership, or blacklist facts. Simulator-only event injection stays visibly marked `SIMULATED` and is restricted to demo/test configuration.

## UI

Add an F4 panel alongside monitoring. It displays plan and context versions, event timeline and occurrence time, epoch grouping, assessment, strategy, structured reason codes, confidence, tool sequence/status/provenance/freshness, active blacklist, safety gate, current-plan projection, candidate, deterministic diff, limitations, action, and confirm/reject controls.

It visibly distinguishes `STALE_BY_NEW_CONTEXT`, missing/stale evidence, search exhaustion, provider failures, and proven no-feasible assistance. It never displays hidden chain-of-thought.

## Testing

Development follows red-green-refactor. Domain tests cover ordering, deduplication, coalescing, constraints, context versions, guards, budgets, risk trend, and outcome separation. Service/API tests cover all F4-01 through F4-32 scenarios, owner authorization, idempotency, context races, concurrent confirmation, worker recovery, and compatibility routing. Agent tests use injected deterministic/OpenAI fakes and assert schemas and guard behavior rather than model prose. Frontend tests/type checks cover state rendering and action enablement.

Verification includes migration upgrade/validation, the complete Python suite, lint/type checks available in the repository, and frontend build. Network calls are excluded from the automated suite; a separately configured smoke path can exercise real OpenAI.

## Delivery order

1. Foundation schemas, persistence, epochs, context, and staleness.
2. Supervisor schemas, OpenAI/fallback adapters, tool/action guards, and audit records.
3. Single-event vertical flows.
4. Multi-event arbitration and constraint carry-forward.
5. Confirm/reject and concurrency/race handling.
6. Proactive SOC risk.
7. API and complete F4 UI.
8. Provider/worker/LLM hardening and complete acceptance regression.

Each slice must be independently testable and preserve the existing F1-F3 regression suite.
