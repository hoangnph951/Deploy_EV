# Kế Hoạch Hoàn Tất Các Case Review Không Liên Quan Station Graph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sửa các lỗi F2/planning/persistence còn liên quan trực tiếp tới `mentor_feedback/review.md`, giữ nguyên thuật toán và agent F1/F4, đồng thời không khôi phục station graph.

**Architecture:** Dùng current branch làm nguồn chuẩn cho F3/F4 mới. Chỉ bổ sung contract đầu ra, persistence nhóm plan và trạng thái trip mà frontend reload/xác nhận/từ chối cần; provider failure được phân loại ở service layer trước khi trả API.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Pytest, React/Vite/TypeScript.

**Spec:** `docs/superpowers/specs/2026-08-31-mentor-review-test-reconciliation-design.md`

## Global Constraints

- Không sửa bất kỳ graph, planning node, adaptive planner, F1/F4 agent hoặc supervisor loop nào.
- Không sửa station graph builder/repository/model/config/worker/migration.
- Không sửa station catalog ingestion hoặc routing cache.
- Không đổi công thức năng lượng, feasibility, station ranking, ngưỡng an toàn hoặc replanning policy.
- Không sửa assertion của test hiện có.

---

### Task 1: Khôi Phục Persistence Nhóm Plan Và Vòng Đời Trip

**Files:**
- Modify: `src/packages/core/trips/infrastructure/models.py` chỉ trong `PlanVersionModel`
- Modify: `src/packages/core/trips/infrastructure/sqlalchemy_repository.py`
- Modify: `src/packages/core/trips/application/service.py`
- Modify: `src/packages/contracts/trips.py`
- Create: `migrations/versions/20260831_1400_restore_f2_plan_persistence.py`
- Test: `tests/test_core/test_plan_persistence.py`
- Test: `tests/test_api/test_f2.py`
- Test: `tests/test_api/test_planning.py`

**Interfaces:**
- Produces: `save_plan_group(plans)->int`, ranked alternatives, proposal JSON tách khỏi assumptions, trip status có thẩm quyền sau reload.
- Preserves: Existing confirm/reject optimistic concurrency, F4 context columns và stale-plan handling.

- [ ] **Step 1: Xác nhận RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_core/test_plan_persistence.py tests/test_api/test_f2.py tests/test_api/test_planning.py -q
```

Expected: thiếu `save_plan_group`, thiếu các column proposal/rank, sai trạng thái conditional/pending và trip vẫn `DRAFT` sau planning.

- [ ] **Step 2: Mở rộng riêng PlanVersionModel**

Giữ `base_plan_version`, `context_version`, `decision_reason`; bổ sung:

```python
UniqueConstraint("trip_id", "version", "rank", name="uq_plan_versions_trip_version_rank")
planning_run_id: Mapped[str | None]
rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="BALANCED")
is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
proposal: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
```

Không thêm bất kỳ station model nào.

- [ ] **Step 3: Implement atomic plan-group persistence**

```python
def save_plan_version(self, plan: PlanVersionRecord) -> None:
    self.save_plan_group([plan])

def save_plan_group(self, plans: list[PlanVersionRecord]) -> int:
    # validate one trip and unique ranks
    # BEGIN IMMEDIATE on SQLite; row lock elsewhere
    # allocate max(version) + 1
    # strip legacy assumptions["proposal"]
    # persist proposal in PlanVersionModel.proposal
    # update serialized proposal version/status
    # retry bounded IntegrityError races
```

Reads must order by `version ASC, rank ASC`, map all lifecycle fields and fall back to legacy nested proposal for one release.

- [ ] **Step 4: Persist all alternatives and authoritative trip status**

In `TripService.generate_trip_plan`:

```python
plan_status = "CONDITIONAL" if recovery_mode or conditional_reason_codes else "PENDING"
allocated_version = repository.save_plan_group(records)
repository.update_trip_status(trip_id, "PLANNED")
```

Apply `allocated_version` and `plan_status` to every returned alternative. On hard provider exception persist `PLANNING_FAILED`. Do not auto-confirm any plan.

- [ ] **Step 5: Preserve F2 explanation response**

Keep top-level `selection_reason` and add/retain the structured `explanation` object derived from already-computed deterministic proposal metadata. Do not invoke or edit the agent.

- [ ] **Step 6: Chạy lại test tập trung**

Run the command from Step 1. Expected: persistence, reload, confirm/reject and F2 explanation tests pass; remaining outcome-classification failures move to Task 2.

Chạy migration F2 trên database SQLite tạm được dựng tới F4 base. Expected: `plan_versions` có `planning_run_id`, `rank`, `strategy`, `is_primary`, `proposal` và unique constraint `(trip_id, version, rank)`. Không có bảng station graph nào được tạo bởi revision mới.

- [ ] **Step 7: Commit**

```powershell
git add src/packages/core/trips/infrastructure/models.py src/packages/core/trips/infrastructure/sqlalchemy_repository.py src/packages/core/trips/application/service.py src/packages/contracts/trips.py
git commit -m "fix: restore f2 plan persistence"
```

### Task 2: Đồng Bộ Outcome Và Phân Loại Lỗi Provider

**Files:**
- Modify: `src/packages/contracts/trips.py`
- Modify: `src/packages/core/trips/application/service.py`
- Modify: `src/apps/api/routes/trips.py` only if response status selection requires it
- Test: `tests/test_api/test_planning.py`
- Test: `tests/test_api/test_f2.py`
- Test: `tests/test_core/test_plan_persistence.py`
- Test: `tests/test_core/test_planning_detour.py`
- Test-only regression: `tests/test_agents/test_graph.py`

**Interfaces:**
- Produces: public outcomes `PROVEN_INFEASIBLE`, `CONDITIONAL`, `ACTION_REQUIRED` and provider metadata.
- Preserves: Existing risk verdict and every route/energy/feasibility decision.
- `tests/test_agents/test_graph.py` chỉ được chạy để kiểm tra contract; không sửa graph source.

- [ ] **Step 1: Xác nhận RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api/test_planning.py tests/test_api/test_f2.py tests/test_core/test_plan_persistence.py tests/test_core/test_planning_detour.py tests/test_agents/test_graph.py -q
```

- [ ] **Step 2: Đồng bộ NoFeasiblePlan contract**

```python
outcome: Literal["PROVEN_INFEASIBLE"] = "PROVEN_INFEASIBLE"
direct_route_distance_km: float | None = None
direct_route_required_soc_percent: float | None = None
```

Các field chỉ đọc kết quả route/energy đã tính sẵn; không sửa node hoặc thuật toán.

- [ ] **Step 3: Phân loại provider state trước refusal**

```python
if state.get("station_routing_rate_limited"):
    return ActionRequiredResponse(
        outcome="ACTION_REQUIRED",
        failure_category="ROUTING_DATA",
        provider_status="RATE_LIMITED",
        http_status=429,
        retry_after_seconds=state.get("routing_retry_after_seconds"),
        ...
    )
```

Station outage trả `ACTION_REQUIRED` với `failure_category="STATION_DATA"`; không biến provider failure thành infeasible.

- [ ] **Step 4: Đồng bộ HTTP status**

```text
PLAN_CREATED -> 201
CONDITIONAL -> 200
PROVEN_INFEASIBLE -> 200
ACTION_REQUIRED -> 200
hard routing provider exception -> existing 503 response
```

- [ ] **Step 5: Chạy lại test outcome**

Run the command from Step 1. Expected: toàn bộ module pass.

- [ ] **Step 6: Commit**

```powershell
git add src/packages/contracts/trips.py src/packages/core/trips/application/service.py src/apps/api/routes/trips.py
git commit -m "fix: classify planning outcomes correctly"
```

### Task 3: Hồi Quy F3/F4, Frontend Và Protected Files

**Files:**
- Verify only.

- [ ] **Step 1: Chạy backend liên quan review**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api/test_f2.py tests/test_api/test_planning.py tests/test_api/test_simulation.py tests/test_api/test_f4.py tests/test_core/test_plan_persistence.py tests/test_core/test_simulator_service.py tests/test_core/test_f4_persistence.py tests/test_core/test_f4_replanning_service.py -q
```

Expected: all pass.

- [ ] **Step 2: Chạy frontend**

From `src/apps/web`:

```powershell
npm test
npm run build
```

Expected: 18 tests pass and production build succeeds.

- [ ] **Step 3: Kiểm tra vùng cấm**

```powershell
git diff 651eb23 --name-only
```

Expected: không có graph/node/agent/supervisor/station-graph path.

- [ ] **Step 4: Ghi nhận lỗi legacy ngoài phạm vi**

Chạy full backend suite ở chế độ chỉ báo cáo. Nếu station graph/catalog legacy vẫn lỗi collect, ghi rõ trong kết quả cuối; không sửa chúng.
