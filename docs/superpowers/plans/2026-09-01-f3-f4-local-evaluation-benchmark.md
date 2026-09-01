# F3/F4 Local Evaluation Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng và chạy bộ evaluation F3/F4 có thể tái lập trên máy local hiện tại, tạo số đo thực tế về accuracy, LLM-as-judge, latency/CCU/scalability và availability/downtime, rồi chốt evidence vào một mục `Evaluation` trong tài liệu và presentation.

**Architecture:** Evaluation là một package độc lập dưới `eval/`, gọi trực tiếp các deterministic service/API contract hiện có thay vì sao chép thuật toán F3/F4. Golden JSONL được validate bằng Pydantic, runner tạo raw records trước rồi metrics/report chỉ tổng hợp từ raw artifacts. Performance dùng HTTP local thật với `httpx` và worker pool `asyncio`; availability runner quản lý một tiến trình Uvicorn local riêng để đo soak, typed provider degradation và forced restart. Live LLM và LLM-as-judge dùng OpenAI Responses structured output, nhưng mọi safety label vẫn do deterministic oracle quyết định.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, Pydantic v2, pytest/pytest-asyncio, httpx, asyncio, OpenAI Responses API, PowerShell, Markdown/CSV/JSONL.

**Spec:** `docs/superpowers/specs/2026-09-01-f3-f4-mentor-review-remediation-design.md` — Section 13 `Evaluation`.

## Global Constraints

- Chỉ báo cáo số đã đo với nhãn `MEASURED`; target luôn ở cột riêng và không được điền thay actual.
- Mỗi run phải khóa `run_id`, commit SHA, thời gian, dataset/runner/prompt/model version, machine/OS/Python/database/provider mode.
- Không đưa secret, OpenAI key, raw GPS chính xác, user ID thật hoặc dữ liệu nhận diện vào artifact.
- Golden safety labels đến từ deterministic oracle/executable assertions; LLM không được tự gán nhãn feasibility, lifecycle hoặc ownership.
- Báo cáo remediation cohort và holdout cohort riêng; không dùng holdout để sửa prompt/code trước lần benchmark đầu tiên.
- Safety violation phải được hiển thị riêng và bằng `0`; không che bằng macro average.
- F3 threshold giữ strict `>` tại `2.0 km`, `5.0% SOC`, `60 s`; evaluation không thay đổi policy sản phẩm.
- Typed degraded response như `INSUFFICIENT_EVIDENCE` là functionally available nếu HTTP/contract đúng; connection error/timeout mới là downtime.
- Kết quả availability local một instance không được gọi là production HA/SLO.
- Human audit 20% là checkpoint thật do một người duyệt; agent chỉ tạo blind sample và nhập kết quả đã ký, không tự nhận output của mình là human audit.
- Worktree hiện có nhiều thay đổi F3/F4 hợp lệ. Mỗi task chỉ stage đúng file của task, không reset hoặc ghi đè thay đổi ngoài phạm vi.

## Artifact Layout

```text
eval/
  contracts.py
  dataset.py
  adapters.py
  local_app.py
  metrics.py
  judge.py
  load_runner.py
  availability_runner.py
  report.py
  run_f3_f4_evaluation.py
  datasets/
    f3_f4_golden_v1.jsonl
    CHANGELOG.md
  prompts/
    f3_f4_judge_v1.md
  results/
    current.json
    f3_f4_local_<YYYYMMDD>_<short-sha>/
      manifest.json
      accuracy_raw.jsonl
      accuracy_summary.json
      judge_raw.jsonl
      judge_summary.json
      human_audit_sample.jsonl
      human_audit_completed.jsonl
      performance_samples.csv
      performance_summary.json
      availability_samples.csv
      availability_summary.json
tests/test_eval/
```

---

### Task 1: Khóa evaluation contracts, manifest và golden dataset schema

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/contracts.py`
- Create: `eval/dataset.py`
- Create: `tests/test_eval/__init__.py`
- Create: `tests/test_eval/test_dataset.py`
- Modify: `.gitignore` only if it currently ignores the committed result directory

**Interfaces:**

```python
class GoldenCase(BaseModel):
    case_id: str
    source: Literal["MENTOR_REMEDIATION", "BOUNDARY", "FAILURE_LIFECYCLE", "HOLDOUT"]
    category: Literal["F3_CLASSIFY", "F3_API", "F4_REPLAN", "F4_LIFECYCLE", "F4_SECURITY"]
    input_snapshot: dict[str, Any]
    expected_events: list[str]
    expected_constraints: dict[str, Any]
    required_tools: list[str]
    forbidden_tools: list[str]
    expected_outcome: str
    expected_action: str | None
    expected_lifecycle: str | None
    ground_truth_method: str
    label_notes: str
    dataset_version: Literal["f3-f4-golden-v1"]

class EvaluationManifest(BaseModel):
    run_id: str
    commit_sha: str
    dirty_worktree: bool
    started_at: datetime
    machine: MachineMetadata
    dataset_version: str
    runner_version: str
    judge_model: str | None
    judge_prompt_version: str | None
    provider_modes: dict[str, str]

def load_golden_cases(path: Path) -> list[GoldenCase]: ...
def build_manifest(*, dataset_version: str, judge_model: str | None) -> EvaluationManifest: ...
```

- [ ] **Step 1: Viết schema tests thất bại**

Test các invariant sau:

```python
def test_loader_rejects_duplicate_case_ids(tmp_path): ...
def test_loader_rejects_unknown_dataset_version(tmp_path): ...
def test_loader_requires_ground_truth_method_and_label_notes(tmp_path): ...
def test_manifest_records_sha_machine_and_dirty_state(monkeypatch): ...
```

`load_golden_cases` phải báo lỗi kèm số dòng JSONL, không nuốt record lỗi.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_dataset.py
```

Expected: FAIL vì package/module chưa tồn tại.

- [ ] **Step 3: Implement contracts và loader tối thiểu**

Dùng Pydantic `extra="forbid"`; đọc JSONL theo dòng; phát hiện ID trùng; yêu cầu ít nhất một case cho mỗi `source`. `build_manifest` dùng `git rev-parse HEAD`, `git status --porcelain`, `platform`, `sys.version`, `os.cpu_count`; nếu không lấy được SHA thì fail với thông báo rõ, không dùng `unknown`.

- [ ] **Step 4: Chạy GREEN và lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_dataset.py
.\.venv\Scripts\python.exe -m ruff check eval/contracts.py eval/dataset.py tests/test_eval/test_dataset.py
```

- [ ] **Step 5: Commit contracts**

```powershell
git add eval/__init__.py eval/contracts.py eval/dataset.py tests/test_eval/__init__.py tests/test_eval/test_dataset.py .gitignore
git commit -m "feat: define F3 F4 evaluation contracts"
```

---

### Task 2: Tạo golden dataset v1 tối thiểu 60 case và chống leakage

**Files:**
- Create: `eval/datasets/f3_f4_golden_v1.jsonl`
- Create: `eval/datasets/CHANGELOG.md`
- Modify: `tests/test_eval/test_dataset.py`
- Create: `tests/test_eval/test_golden_cases.py`

**Dataset composition:**

- 15 `MENTOR_REMEDIATION` cases, giữ đúng ID:
  - `P210-F3-EDGE-002`, `P210-F3-EDGE-003`, `P210-F3-HAPPY-004`, `P210-F3-EDGE-005`, `P210-F3-EDGE-006`;
  - `P210-F4-HAPPY-001`, `P210-F4-HAPPY-002`, `P210-F4-EDGE-003`, `P210-F4-UNHAPPY-005`, `P210-F4-HAPPY-006`, `P210-F4-EDGE-007`, `P210-F4-SEC-008`, `P210-F4-AI-009`, `P210-F4-AI-904`, `P210-F4-AI-905`.
- 21 `BOUNDARY` cases: `1.99/2.00/2.01 km`, `4.9/5.0/5.1%`, `59/60/61 s`, các single-axis case và systematic combinations để kiểm tra precedence.
- 12 `FAILURE_LIFECYCLE` cases: provider failure, proven infeasible, stale telemetry refresh, stale candidate, two-tab conflict, duplicate/idempotent event, reject unsafe, cross-user generic/F4 endpoints.
- 12 `HOLDOUT` cases: route/SOC/station-position/event combinations mới, không trùng input với remediation/boundary.

- [ ] **Step 1: Viết composition/leakage tests thất bại**

```python
def test_golden_v1_has_at_least_60_cases():
    cases = load_golden_cases(GOLDEN_V1)
    assert len(cases) >= 60

def test_golden_v1_has_exact_mentor_remediation_ids(): ...
def test_each_threshold_has_below_equal_above_cases(): ...
def test_holdout_inputs_do_not_duplicate_non_holdout_inputs(): ...
def test_safety_cases_have_executable_ground_truth(): ...
```

Fingerprint leakage bằng canonical JSON của `category + input_snapshot`, không dựa vào `case_id`.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_dataset.py tests/test_eval/test_golden_cases.py
```

Expected: FAIL vì JSONL/changelog chưa có.

- [ ] **Step 3: Viết JSONL labels từ contract hiện hữu**

Mỗi case phải có đủ expected events/constraints/tools/outcome/action/lifecycle; case không áp dụng field nào dùng `[]`, `{}` hoặc `null`, không dùng placeholder chưa chốt. Boundary labels phải thể hiện equality là `NORMAL`. F4 stale/provider/security labels phải thể hiện fail-closed và không candidate mutation.

- [ ] **Step 4: Viết changelog**

`CHANGELOG.md` ghi version, ngày, 4 cohort, nguồn 15 mentor IDs, quy tắc deterministic labeling, holdout freeze timestamp và quy tắc tạo v2 khi đổi label.

- [ ] **Step 5: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_dataset.py tests/test_eval/test_golden_cases.py
```

- [ ] **Step 6: Commit dataset**

```powershell
git add eval/datasets/f3_f4_golden_v1.jsonl eval/datasets/CHANGELOG.md tests/test_eval/test_dataset.py tests/test_eval/test_golden_cases.py
git commit -m "test: add F3 F4 golden evaluation dataset"
```

---

### Task 3: Thực thi golden cases qua F3/F4 thật và lưu raw predictions

**Files:**
- Create: `eval/adapters.py`
- Create: `eval/local_app.py`
- Create: `tests/test_eval/test_adapters.py`
- Modify: `src/apps/api/routes/replanning.py`
- Modify: `tests/test_api/test_f4.py`
- Reuse: `src/packages/core/monitoring/application/service.py:49-67`
- Reuse: `src/apps/api/main.py`
- Reuse: `tests/conftest.py` deterministic provider composition pattern

**Interfaces:**

```python
class CasePrediction(BaseModel):
    case_id: str
    cohort: str
    events: list[str]
    constraints: dict[str, Any]
    selected_tools: list[str]
    outcome: str
    action: str | None
    lifecycle: str | None
    candidate_count: int
    safety_violations: list[str]
    narrative: str | None
    supervisor_mode: Literal["OPENAI", "SAFE_FALLBACK", "DETERMINISTIC_ORACLE"]
    model: str | None
    prompt_version: str | None
    latency_ms: float
    raw_contract: dict[str, Any]

class EvaluationAdapter(Protocol):
    async def execute(self, case: GoldenCase) -> CasePrediction: ...

def adapter_for(case: GoldenCase, harness: EvaluationHarness) -> EvaluationAdapter: ...
async def run_accuracy_cases(cases: list[GoldenCase], harness: EvaluationHarness) -> list[CasePrediction]: ...
```

Adapters:

- `F3_CLASSIFY`: gọi trực tiếp `MonitoringEvaluator.classify` cho boundary oracle.
- `F3_API`: dùng `ASGITransport(app=app)` với SQLite temp và deterministic routing/station/environment providers.
- `F4_REPLAN`: create trip/confirmed plan rồi POST `/api/v1/trips/{trip_id}/replans` bằng unique owner/event/telemetry IDs. Measured accuracy dùng OpenAI supervisor thật; deterministic providers chỉ sở hữu route/station/environment evidence.
- `F4_LIFECYCLE`: thực hiện sequence replan → new context/confirm/reject và đọc lại authoritative plan/context.
- `F4_SECURITY`: tạo owner A/B, gọi cả generic và F4 mutation endpoints, đọc lại state của A.

- [ ] **Step 1: Viết adapter tests thất bại**

```python
@pytest.mark.asyncio
async def test_f3_classify_adapter_uses_strict_boundary(): ...

@pytest.mark.asyncio
async def test_f4_provider_failure_adapter_returns_typed_insufficient_evidence(): ...

@pytest.mark.asyncio
async def test_security_adapter_detects_any_cross_user_mutation(): ...

@pytest.mark.asyncio
async def test_adapter_sanitizes_dynamic_ids_from_raw_contract(): ...

def test_evaluation_app_keeps_deterministic_tools_but_allows_live_supervisor(): ...
```

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_adapters.py
```

- [ ] **Step 3: Tách supervisor composition thành FastAPI dependency**

Trong `src/apps/api/routes/replanning.py`, giữ nguyên `_build_supervisor(settings)` nhưng thêm dependency:

```python
def get_replanning_supervisor(settings: Settings = Depends(get_settings)):
    return _build_supervisor(settings)
```

Các replan endpoints nhận `supervisor=Depends(get_replanning_supervisor)` và truyền đúng instance vào `ReplanningService`. Characterization API tests phải chứng minh `APP_ENV=test` vẫn dùng conservative supervisor như trước; production behavior không đổi. Seam này chỉ cho evaluation app override provider tại composition boundary.

- [ ] **Step 4: Implement evaluation app factory và adapters**

`eval/local_app.py` cấu hình SQLite riêng, `InMemoryRoutingProvider`, `FixtureStationDataService`, `StaticEnvironmentProvider`, rồi override `get_replanning_supervisor` theo explicit mode:

- `live`: `OpenAISupervisor` với model/timeout từ Settings;
- `fallback`: `ConservativeSupervisor` cho deterministic load;
- `timeout`: supervisor có Responses client kiểm soát được, luôn vượt timeout rồi đi qua production fallback path.

Factory chạy với auth test isolation nhưng không được để nhánh `APP_ENV=test` âm thầm thay supervisor live. Start Uvicorn bằng `eval.local_app:create_app --factory`.

Sau đó implement harness/adapters. Mỗi case có database/harness isolation; unique IDs sinh từ `case_id` đã sanitize. Raw contract chỉ giữ field cần chấm, bỏ auth header, absolute GPS và free-form provider payload. Không mock `MonitoringEvaluator`, `ReplanningService`, guards hoặc repository; chỉ kiểm soát external routing/station/environment tại composition boundary. Unit tests dùng fake structured supervisor response; measured F4 accuracy dùng mode `live`.

- [ ] **Step 5: Khóa one-epoch/one-candidate và tool trace extraction**

Extract `selected_tools` từ authoritative `tool_runs`; candidate count từ persisted plan versions; lifecycle từ record sau khi sequence kết thúc. Ghi response source, model, prompt version và fallback rate. Thêm `safety_violations` cho blacklist leak, stale mutation, cross-user mutation, unconfirmed auto-apply và infeasible candidate proposal. Fallback vẫn tính vào system outcome/action accuracy, nhưng tool-selection report phải tách `OPENAI` khỏi `SAFE_FALLBACK` để không gọi deterministic fallback là GPT accuracy.

- [ ] **Step 6: Chạy GREEN và focused F3/F4 regression**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_adapters.py tests/test_core/test_f3_monitoring.py tests/test_core/test_f4_replanning_service.py tests/test_api/test_f4.py
```

- [ ] **Step 7: Commit adapters**

```powershell
git add eval/adapters.py eval/local_app.py tests/test_eval/test_adapters.py src/apps/api/routes/replanning.py tests/test_api/test_f4.py
git commit -m "feat: execute golden cases through F3 F4"
```

---

### Task 4: Tính accuracy, confusion matrices, safety gates và agreement

**Files:**
- Create: `eval/metrics.py`
- Create: `tests/test_eval/test_metrics.py`

**Interfaces:**

```python
def classification_report(expected: list[set[str]], predicted: list[set[str]], labels: list[str]) -> dict: ...
def exact_match_rate(expected: list[Any], predicted: list[Any]) -> float: ...
def set_precision_recall(expected: set[str], predicted: set[str]) -> tuple[float, float]: ...
def required_tool_recall(cases: list[GoldenCase], predictions: list[CasePrediction]) -> float: ...
def forbidden_tool_violation_rate(...) -> float: ...
def weighted_cohens_kappa(left: list[int], right: list[int], *, minimum: int = 1, maximum: int = 5) -> float: ...
def percentile(values: list[float], quantile: float) -> float: ...
def build_accuracy_summary(cases: list[GoldenCase], predictions: list[CasePrediction]) -> dict: ...
```

- [ ] **Step 1: Viết unit tests bằng hand-calculated fixtures**

Bao phủ zero division, perfect agreement, chance agreement, disagreement, per-label TP/FP/FN/TN, exact match và percentile p50/p95/p99. Dùng expected numeric literals tính tay, không dùng chính implementation để sinh expected.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_metrics.py
```

- [ ] **Step 3: Implement pure metrics**

Summary phải có:

- per-event precision/recall/F1 và confusion counts;
- `INFEASIBLE` precision/recall/F1;
- outcome/action/lifecycle exact match;
- tool selection precision/recall, required recall, forbidden violation;
- constraint/epoch/candidate/blacklist/stale/security violation counts;
- kết quả tách `MENTOR_REMEDIATION` và `HOLDOUT`.

Nếu safety violation >0 hoặc infeasible recall <100% trên safety subset, `safety_gate_passed=false` dù macro metrics cao.

- [ ] **Step 4: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_metrics.py
```

- [ ] **Step 5: Commit metrics**

```powershell
git add eval/metrics.py tests/test_eval/test_metrics.py
git commit -m "feat: calculate F3 F4 evaluation metrics"
```

---

### Task 5: Thêm LLM-as-judge hai lượt và blind human audit package

**Files:**
- Create: `eval/prompts/f3_f4_judge_v1.md`
- Create: `eval/judge.py`
- Create: `tests/test_eval/test_judge.py`

**Interfaces:**

```python
class JudgeScore(BaseModel):
    groundedness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    action_safety: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    rationale: str

async def judge_narratives(
    samples: list[JudgeSample], *, client: OpenAI, model: str,
    prompt_text: str, passes: int = 2,
) -> list[JudgeRecord]: ...

def summarize_judges(records: list[JudgeRecord]) -> dict: ...
def select_human_audit_sample(records: list[JudgeRecord], *, rate: float = 0.20, seed: int = 210) -> list[dict]: ...
```

- [ ] **Step 1: Viết tests với fake Responses client**

Assert structured parse schema, hai lượt độc lập, case ID không xuất hiện trong judge input, raw score/rationale được lưu, pass chỉ khi cả 5 dimension `>=4`, kappa tính từng dimension và aggregate. Audit sampling phải deterministic, stratified theo cohort/pass-fail và có `ceil(20%)` records.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_judge.py
```

- [ ] **Step 3: Implement prompt và judge adapter**

Prompt chỉ chứa typed observations, expected limitations và narrative; không gửi golden final score hoặc case ID. Dùng `client.responses.parse(..., text_format=JudgeScore)` theo pattern hiện có trong `src/packages/agent/replanning/supervisor.py`. Cấu hình timeout hữu hạn; retry tối đa một lần cho transport/schema error và ghi retry count.

- [ ] **Step 4: Implement human audit package**

Sinh `human_audit_sample.jsonl` với blind sample, rubric và empty reviewer fields. Validation của `human_audit_completed.jsonl` yêu cầu `reviewer`, `reviewed_at`, 5 dimension scores và notes; không cho report final nếu audit file thiếu hoặc chưa đủ 20%.

- [ ] **Step 5: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_judge.py tests/test_eval/test_metrics.py
```

- [ ] **Step 6: Commit judge**

```powershell
git add eval/prompts/f3_f4_judge_v1.md eval/judge.py tests/test_eval/test_judge.py
git commit -m "feat: add reproducible LLM judge evaluation"
```

---

### Task 6: Đo performance/CCU trên local HTTP server thật

**Files:**
- Create: `eval/load_runner.py`
- Create: `tests/test_eval/test_load_runner.py`
- Modify: `requirements.txt`

**Interfaces:**

```python
class WorkloadSpec(BaseModel):
    name: Literal["F3_TICK", "F4_DETERMINISTIC", "F4_LIVE_LLM"]
    concurrency: int
    samples: int
    warmup_samples: int
    timeout_seconds: float

async def run_workload(base_url: str, spec: WorkloadSpec, factory: RequestFactory) -> list[LatencySample]: ...
def summarize_workload(samples: list[LatencySample], baseline_p95_ms: float | None) -> dict: ...
async def run_performance_matrix(base_url: str, manifest: EvaluationManifest) -> tuple[list[LatencySample], dict]: ...
```

- [ ] **Step 1: Viết worker-pool tests thất bại**

Fake HTTP server ghi số in-flight requests. Assert concurrency không vượt spec, warm-up không lọt vào measured samples, mỗi sample có status/latency/error/tool latency, timeout thành error sample, percentile/throughput đúng.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_load_runner.py
```

- [ ] **Step 3: Implement bounded asyncio runner**

Dùng `asyncio.Queue` + đúng số worker bằng CCU, một shared `httpx.AsyncClient`, `time.perf_counter_ns`. Request factory tạo unique trip/event IDs và seed database trước workload; không tái dùng cùng idempotency key làm giảm giả latency.

- [ ] **Step 4: Implement exact workload matrix**

- F3 tick/event: CCU `1,5,10,20`, 200 measured samples/mức.
- F4 deterministic/fallback: CCU `1,5,10,20`, 40 measured samples/mức.
- F4 live LLM: CCU `1`, tối thiểu 10 golden cases.

Mỗi workload warm-up riêng. Live LLM sample ghi model, input/output tokens nếu response cung cấp, estimated cost theo một config snapshot có nguồn/version; nếu không có token/cost thì ghi `null` + limitation, không ước lượng bừa.

- [ ] **Step 5: Implement saturation rules và process sampling**

Thêm `psutil>=6.1.0,<7.0.0` vào dev/evaluation dependencies và cài vào `.venv` trước benchmark. Mức saturation đầu tiên thỏa một trong: error `>1%`, p95 `>2x` baseline CCU1, sustained CPU `>85%`, memory slope dương không ổn định. Sampler lấy CPU/RSS của API process và children theo chu kỳ cố định; nếu sampler không hoạt động trên Windows, runner fail preflight thay vì âm thầm bỏ metric.

- [ ] **Step 6: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_load_runner.py
```

- [ ] **Step 7: Commit load runner**

```powershell
git add eval/load_runner.py tests/test_eval/test_load_runner.py requirements.txt
git commit -m "feat: benchmark F3 F4 local concurrency"
```

---

### Task 7: Đo availability, downtime, MTTR và fault recovery trong soak 10 phút

**Files:**
- Create: `eval/availability_runner.py`
- Create: `tests/test_eval/test_availability_runner.py`

**Interfaces:**

```python
class LocalApiProcess:
    async def start(self) -> None: ...
    async def wait_ready(self, timeout_seconds: float) -> float: ...
    async def restart(self) -> None: ...
    async def stop(self) -> None: ...

async def run_availability_soak(
    process: LocalApiProcess, *, duration_seconds: int = 600,
    request_interval_seconds: float = 1.0,
) -> tuple[list[AvailabilitySample], AvailabilitySummary]: ...

def calculate_error_windows(samples: list[AvailabilitySample]) -> list[ErrorWindow]: ...
```

- [ ] **Step 1: Viết lifecycle/MTTR tests với fake process/clock**

Assert contiguous failures gộp thành một error window, downtime tính từ request failure đầu tới successful recovery đầu, longest downtime/total downtime/MTTR đúng, typed `INSUFFICIENT_EVIDENCE` vẫn functionally available, forced connection failure là unavailable.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_availability_runner.py
```

- [ ] **Step 3: Implement managed local Uvicorn process**

Start bằng chính interpreter `.venv`, port evaluation riêng, SQLite database file trong run directory và `eval.local_app:create_app --factory`. Evaluation app dùng test auth isolation, deterministic external providers, explicit supervisor mode và fault injection enabled. Resolve/validate tuyệt đối run directory trước cleanup. Process stdout/stderr ghi vào run artifact; không hiện secret/env values.

- [ ] **Step 4: Implement fault schedule**

Trong 600 giây ở 1 request/giây:

- baseline health/functional probe;
- LLM timeout window qua `local_app` supervisor override tại composition boundary, expected production timeout/fallback handling và typed safe response;
- `F1_PROVIDER_FAILURE`, expected `INSUFFICIENT_EVIDENCE` với valid HTTP contract;
- forced API restart, expected có connection downtime trên single instance rồi recovery.

Không thêm endpoint production chỉ để crash server. Forced restart do benchmark process manager thực hiện.

- [ ] **Step 5: Chạy GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_availability_runner.py
```

- [ ] **Step 6: Commit availability runner**

```powershell
git add eval/availability_runner.py tests/test_eval/test_availability_runner.py
git commit -m "feat: measure local F3 F4 availability"
```

---

### Task 8: Orchestrator, artifact writer và Markdown report renderer

**Files:**
- Create: `eval/report.py`
- Create: `eval/run_f3_f4_evaluation.py`
- Create: `tests/test_eval/test_report.py`
- Create: `docs/evaluation/.gitkeep`

**CLI:**

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation accuracy --dataset eval/datasets/f3_f4_golden_v1.jsonl
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation judge --run-id current --model-from-settings
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation performance --run-id current --managed-local-api
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation availability --run-id current --duration-seconds 600
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation report --run-id current
```

- [ ] **Step 1: Viết report snapshot tests thất bại**

Fixture result nhỏ phải render:

- manifest + `MEASURED`/`TARGET`;
- remediation và holdout accuracy riêng;
- confusion matrices/safety gates;
- judge mean/median/pass/kappa/human audit;
- performance p50/p95/p99/throughput/error/saturation;
- availability, error windows, downtime, MTTR;
- limitations local/single-instance và next HA step;
- links tới raw artifact cùng `run_id`.

Assert report fail nếu thiếu raw file, audit chưa hoàn tất, run IDs/version không khớp hoặc safety section bị bỏ.

- [ ] **Step 2: Chạy RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval/test_report.py
```

- [ ] **Step 3: Implement atomic artifact writes và CLI stages**

Ghi file tạm trong đúng run directory rồi `replace`; `eval/results/current.json` chỉ chứa active `run_id` và được dùng khi CLI nhận `--run-id current`. Resume được stage đã hoàn tất nếu checksum/version khớp. Manifest lưu SHA trước khi chạy; nếu worktree dirty, report phải hiển thị rõ và lưu diff hash. CLI không tự che lỗi network/model; stage nào fail ghi status và error class vào manifest rồi exit non-zero.

- [ ] **Step 4: Implement report renderer**

Render `docs/evaluation/f3_f4_local_benchmark_20260901.md` chỉ từ summary/raw files, không hard-code số trong template. Mọi số trên Markdown mang result ID hoặc link raw evidence.

- [ ] **Step 5: Chạy GREEN và full evaluation unit suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval
.\.venv\Scripts\python.exe -m ruff check eval tests/test_eval
```

- [ ] **Step 6: Commit orchestrator**

```powershell
git add eval/report.py eval/run_f3_f4_evaluation.py tests/test_eval/test_report.py docs/evaluation/.gitkeep
git commit -m "feat: orchestrate F3 F4 benchmark artifacts"
```

---

### Task 9: Chạy benchmark thực tế trên máy local hiện tại

**Files created by runner:**
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/manifest.json`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/accuracy_raw.jsonl`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/accuracy_summary.json`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/judge_raw.jsonl`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/judge_summary.json`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/human_audit_sample.jsonl`
- Create after human checkpoint: `eval/results/f3_f4_local_20260901_<short-sha>/human_audit_completed.jsonl`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/performance_samples.csv`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/performance_summary.json`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/availability_samples.csv`
- Create: `eval/results/f3_f4_local_20260901_<short-sha>/availability_summary.json`

- [ ] **Step 1: Preflight và baseline verification**

```powershell
git rev-parse HEAD
git status --short
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval tests/test_core/test_f3_monitoring.py tests/test_core/test_f4_replanning_service.py tests/test_api/test_f4.py
```

Ghi dirty state trung thực. Verify `.env` có credential cần thiết bằng boolean preflight, tuyệt đối không print value.

- [ ] **Step 2: Chạy golden system accuracy với live supervisor**

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation accuracy --dataset eval/datasets/f3_f4_golden_v1.jsonl --supervisor-mode live
```

Không sửa implementation/label sau khi nhìn holdout score trong cùng run. Nếu phát hiện runner bug, tạo run ID mới và ghi lý do invalidating run cũ.

- [ ] **Step 3: Chạy live LLM F4 và two-pass judge**

Đây là network/cost checkpoint. Chỉ chạy khi user đã cho phép dùng credential/model cấu hình. Ghi đúng model trả về từ API; tối thiểu 10 live F4 golden cases và hai judge passes. Không fallback sang fake client trong benchmark thực.

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation judge --run-id current --model-from-settings
```

- [ ] **Step 4: Hoàn tất blind human audit 20%**

Gửi `human_audit_sample.jsonl` cho người duyệt, nhận lại đủ scores/notes/reviewer/timestamp, validate bằng CLI. Đây là manual gate bắt buộc; nếu chưa có thì report ghi `PENDING_HUMAN_AUDIT` và không tuyên bố LLM judge hoàn tất.

- [ ] **Step 5: Chạy performance matrix**

Start local API evaluation process, xác minh `/health`, rồi chạy đủ CCU/sample matrix. Trong lúc đo không chạy frontend/build/test khác trên máy. Lưu CPU/RAM/DB/provider mode vào manifest.

- [ ] **Step 6: Chạy availability soak đủ 600 giây**

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation availability --run-id current --duration-seconds 600
```

Không rút ngắn duration rồi vẫn ghi 10 phút. Forced restart phải tạo downtime thực và recovery evidence.

- [ ] **Step 7: Render report và audit raw artifacts**

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation report --run-id current
rg -n "OPENAI_API_KEY|GOONG_API_KEY|Bearer |X-User-Id" eval/results docs/evaluation
```

Expected: secret scan không có match nhạy cảm; mọi summary truy ngược được raw samples.

- [ ] **Step 8: Commit measured artifacts**

```powershell
git add eval/results/f3_f4_local_20260901_<short-sha> docs/evaluation/f3_f4_local_benchmark_20260901.md
git commit -m "docs: record measured F3 F4 local benchmark"
```

---

### Task 10: Reflect measured Evaluation vào design, feature docs và presentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-01-f3-f4-mentor-review-remediation-design.md`
- Modify: `docs/FEATURE_3_IMPLEMENT.md`
- Modify: `docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md`
- Modify: `presentation/README.md`
- Modify: `eval/results/report.md`

- [ ] **Step 1: Thêm result reference vào design Section 13**

Không copy tay toàn bộ bảng. Thêm benchmark `run_id`, commit SHA, link report và completion status cho từng gate; giữ methodology/target riêng số measured.

- [ ] **Step 2: Thêm mục `Evaluation` vào hai feature docs**

F3 doc nêu golden boundary/event recall, tick latency/CCU và simulator limitations. F4 doc nêu outcome/tool/action/safety metrics, live LLM judge, deterministic/live latency, provider degradation và lifecycle/security violations. Cả hai link cùng benchmark report/run ID.

- [ ] **Step 3: Thay placeholder report cũ**

`eval/results/report.md` trở thành index ngắn trỏ tới report authoritative mới; bỏ các ô `—`, `[User 1]`, `[YYYY-MM-DD]` để mentor không nhầm template là kết quả.

- [ ] **Step 4: Tăng pitch deck từ 10 lên 11 slide**

Trong `presentation/README.md`, chèn `Evaluation Evidence` sau `Architecture/Tech Stack`, trước `Traction`. Slide chỉ hiển thị số `MEASURED`: dataset size, remediation/holdout accuracy, zero/non-zero safety violations, LLM judge pass/kappa, latency theo workload, max verified CCU, observed availability/downtime/MTTR và một next HA step. Ghi rõ `Local benchmark · single instance`.

- [ ] **Step 5: Consistency test thủ công bằng result ID**

```powershell
rg -n "f3_f4_local_20260901|MEASURED|TARGET|single instance|run_id" docs/superpowers/specs/2026-09-01-f3-f4-mentor-review-remediation-design.md docs/FEATURE_3_IMPLEMENT.md docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md docs/evaluation/f3_f4_local_benchmark_20260901.md presentation/README.md eval/results/report.md
```

Đối chiếu mọi số presentation với JSON summary; không có số chỉ xuất hiện riêng trên slide.

- [ ] **Step 6: Commit documentation**

```powershell
git add docs/superpowers/specs/2026-09-01-f3-f4-mentor-review-remediation-design.md docs/FEATURE_3_IMPLEMENT.md docs/FEATURE_4_IMPLEMENTATION_SPEC_v2.0.md presentation/README.md eval/results/report.md
git commit -m "docs: publish F3 F4 evaluation evidence"
```

---

### Task 11: Final verification and evidence integrity gate

**Files:**
- No new files expected; only fix files whose verification test fails.

- [ ] **Step 1: Run all evaluation and relevant F3/F4 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_eval tests/test_core/test_f3_monitoring.py tests/test_core/test_monitoring_service.py tests/test_agents/test_f4_supervisor.py tests/test_agents/test_f4_guards.py tests/test_core/test_f4_event_coordinator.py tests/test_core/test_f4_context_manager.py tests/test_core/test_f4_supervisor_loop.py tests/test_core/test_f4_runtime_store.py tests/test_core/test_f4_replanning_service.py tests/test_core/test_f4_plan_diff.py tests/test_core/test_f4_persistence.py tests/test_core/test_f4_periodic_risk.py tests/test_core/test_f4_simulation_faults.py tests/test_api/test_f4_candidate_planner.py tests/test_api/test_f4.py tests/test_api/test_f2.py
```

- [ ] **Step 2: Run lint and frontend verification**

```powershell
.\.venv\Scripts\python.exe -m ruff check eval src tests
Set-Location src/apps/web
npm.cmd test
npm.cmd run build
Set-Location ../../..
```

- [ ] **Step 3: Verify artifact consistency and no placeholders**

```powershell
.\.venv\Scripts\python.exe -m eval.run_f3_f4_evaluation report --run-id current --verify-only
rg -n "Actual.*—|PENDING_HUMAN_AUDIT|\[User [0-9]+\]|\[YYYY-MM-DD\]" docs/evaluation presentation/README.md eval/results/report.md
```

Expected: zero placeholder matches; `--verify-only` checks checksums, versions, sample counts and cross-file run ID.

- [ ] **Step 4: Secret and privacy scan**

```powershell
rg -n "sk-[A-Za-z0-9_-]+|OPENAI_API_KEY=.+|GOONG_API_KEY=.+|Authorization: Bearer|X-User-Id" eval/results docs/evaluation presentation
```

Expected: zero secret/identity payload matches.

- [ ] **Step 5: Final diff audit**

```powershell
git diff --check
git status --short
git log -1 --oneline
```

Review raw result size; commit compact evidence JSONL/CSV, không commit SQLite DB, process logs chứa payload, cache hoặc `.env`.

- [ ] **Step 6: Completion rule**

Chỉ tuyên bố evaluation hoàn tất khi:

- dataset `>=60` và đủ 4 cohort;
- deterministic report có confusion matrices và safety gate;
- live judge có 2 passes, agreement và human audit đủ 20%;
- performance đủ toàn bộ CCU/sample matrix;
- soak thực sự đủ 600 giây và có forced-restart recovery;
- docs/design/presentation dùng cùng run ID/SHA và mọi số truy được raw evidence.

Nếu một gate chưa hoàn tất, báo đúng gate và artifact đã có; không chuyển target thành actual hoặc tự ghi `PASS`.
