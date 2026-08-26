# Huong dan codebase P-210 cho nguoi moi

Tai lieu nay la ban do de nguoi lan dau vao du an biet nen bat dau tu dau, request di qua nhung lop nao, moi thu muc chiu trach nhiem gi va nen chay test nao khi sua code.

## 1. Tong quan repository

P-210 la monorepo gom backend FastAPI, frontend React/Vite, LangGraph planning agent, cac deterministic tools cho xe dien va database.

```text
P-210/
|-- src/
|   |-- apps/
|   |   |-- api/        # Backend FastAPI
|   |   `-- web/        # Frontend React/Vite
|   `-- packages/
|       |-- contracts/  # Pydantic request/response schemas
|       |-- agent/      # LangGraph planning workflow
|       `-- core/       # Business logic va infrastructure
|-- tests/              # Unit, agent va API tests
|-- migrations/         # Alembic migrations
|-- docs/               # PRD, architecture, huong dan
`-- scripts/            # Script ho tro, log va migration
```

Tai lieu kien truc tong quan: [`ARCHITECTURE.md`](../ARCHITECTURE.md).

## 2. Entry point cua ung dung

### Backend

Backend bat dau tai [`src/apps/api/main.py`](../src/apps/api/main.py).

File nay:

- tao FastAPI app;
- cau hinh logging va CORS;
- dang ky cac router;
- gan `X-Trace-Id` cho request;
- xu ly `AppError` va validation error;
- cung cap `/health`.

Router chinh:

```text
src/apps/api/routes/auth.py
src/apps/api/routes/places.py
src/apps/api/routes/trips.py
src/apps/api/routes/chat.py
```

Cau hinh moi truong va provider nam tai [`src/apps/api/bootstrap/config.py`](../src/apps/api/bootstrap/config.py).

### Frontend

Frontend bat dau tai [`src/apps/web/src/main.tsx`](../src/apps/web/src/main.tsx), component goc la [`App.tsx`](../src/apps/web/src/App.tsx).

Frontend xu ly dang nhap, chon xe, nhap diem dau/cuoi, tao trip, hien thi ban do, SOC, tram sac, canh bao va confirm/reject plan.

Component quan trong:

```text
AuthPage.tsx
VehicleSetup.tsx
GoongPlaceInput.tsx
TripPlanMap.tsx
SocChart.tsx
ChargingStopList.tsx
DashboardPanels.tsx
Feature2Panels.tsx
InfeasibleWarningBanner.tsx
RecoveryPanel.tsx
```

Frontend API va type:

```text
src/apps/web/src/lib/api.ts
src/apps/web/src/lib/types.ts
```

## 3. Ba khu vuc backend can nam ro

### `contracts`

[`src/packages/contracts/`](../src/packages/contracts/) dinh nghia hinh dang request/response bang Pydantic.

File chinh:

```text
trips.py
auth.py
places.py
chat.py
errors.py
```

Schema quan trong trong `trips.py`:

- `TripCreateRequest`;
- `TripCreatedResponse`;
- `TripDetailResponse`;
- `PlanProposal`;
- `RouteGeometry`;
- `ChargingStopProposal`;
- `AssumptionSnapshot`;
- `VehicleProfileSnapshot`;
- `NoFeasiblePlan`.

Khi can biet API nhan hoac tra du lieu gi, doc `contracts` truoc.

### `core`

[`src/packages/core/`](../src/packages/core/) chua nghiep vu chinh:

```text
core/
|-- auth/
|-- policies/
|-- trips/
|-- monitoring/
|-- simulator/
`-- support/
```

Moi module thuong chia thanh:

```text
module/
|-- api/             # FastAPI dependencies/adapters
|-- application/     # Use cases va services
|-- domain/          # Entities va business rules
`-- infrastructure/  # DB, provider, HTTP client, fixtures
```

### `agent`

[`src/packages/agent/`](../src/packages/agent/) chua LangGraph workflow.

Agent tinh toan va tra structured result. Agent khong tu ghi business state vao database; `TripService` quan ly ownership, version va persistence.

## 4. Luong tao trip

```text
Frontend
  -> POST /api/v1/trips
  -> routes/trips.py:create_trip()
  -> TripService.create_trip()
  -> resolve origin/destination
  -> load VehicleProfile
  -> create AssumptionSnapshot
  -> save TripRecord
  -> return trip_id
```

Route nam tai [`src/apps/api/routes/trips.py`](../src/apps/api/routes/trips.py).

Service nam tai [`src/packages/core/trips/application/service.py`](../src/packages/core/trips/application/service.py).

Trip luu origin, destination, initial SOC, SOC source, vehicle profile, preference, assumptions va timestamps.

## 5. Luong lap ke hoach F1

```text
POST /api/v1/trips/{trip_id}/plans
  -> routes/trips.py:create_trip_plan()
  -> TripService.generate_trip_plan()
  -> planning_agent.invoke()
  -> LangGraph nodes
  -> PlanProposal hoac NoFeasiblePlan
```

Graph nam tai [`src/packages/agent/planning/graph.py`](../src/packages/agent/planning/graph.py).

```text
routing
   |
station_energy
   |
feasibility
   |
   |-- proposal
   |-- recovery
   `-- no_feasible_plan
```

### `routing`

- Goi `RoutingProvider`.
- Lay polyline, segments, distance, duration va provenance.
- Tra `RoutingResult`.

### `station_energy`

- Lay environment snapshot.
- Mo phong direct trip truoc.
- Tim candidate stations khi can sac.
- Tim station chains va route qua tung tram.
- Mo phong SOC tung chang.
- Tao cac alternative `BALANCED`, `FASTEST`, `SAFEST`.

Node nam tai [`planning_nodes.py`](../src/packages/agent/planning/nodes/planning_nodes.py). Adaptive graph search nam tai [`adaptive_station_planner.py`](../src/packages/agent/planning/tools/adaptive_station_planner.py).

### `feasibility`

Kiem tra reserve SOC, connector, kha nang toi destination/tram tiep theo, detour, risk va reason codes.

### `proposal`

Chuyen ket qua ky thuat thanh `PlanProposal`: route, charging stops, SOC points, summary, explanation va alternatives.

### `recovery`

Mo rong tim kiem khi official search chua tim duoc phuong an hoan chinh.

### `no_feasible_plan`

Tra ket qua tu choi an toan va reason code. Khong luu mot plan nguy hiem nhu plan co the confirm.

## 6. AgentState

[`src/packages/agent/planning/state.py`](../src/packages/agent/planning/state.py) dinh nghia du lieu dung chung giua cac node.

```text
trip_id, owner_id
origin/destination
initial_soc_percent
vehicle_profile
assumptions
route_result
candidate_stations
environment
energy_result
feasibility_verdict
route_energy_alternatives
plan_proposal
plan_alternatives
no_feasible_plan
recovery state
response / analysis
```

Co the hieu `AgentState` la tui du lieu di xuyen suot workflow.

## 7. Cac tool cua thuat toan

### Routing

[`routing.py`](../src/packages/core/trips/infrastructure/routing.py)

```text
GoongRoutingProvider       # Runtime that
InMemoryRoutingProvider    # Test/fixture
```

### Station

[`station_service.py`](../src/packages/core/trips/infrastructure/station_service.py)

```text
FixtureStationDataService
VinFastStationDataService
FallbackStationDataService
```

### Energy

[`energy_tool.py`](../src/packages/core/trips/infrastructure/energy_tool.py) tinh consumption Wh/km, SOC tung chang, energy, charging time, station chain, final SOC va minimum SOC.

### Feasibility

[`feasibility_tool.py`](../src/packages/core/trips/infrastructure/feasibility_tool.py) danh gia reserve, reachability, connector, detour, risk va reason codes.

### Environment

[`environment.py`](../src/packages/core/trips/infrastructure/environment.py)

```text
OpenMeteoEnvironmentProvider
StaticEnvironmentProvider
```

Nhiet do, mua, gio va dia hinh co the tac dong toi EnergyTool.

## 8. Dependency wiring

[`src/packages/core/trips/api/dependencies.py`](../src/packages/core/trips/api/dependencies.py) tao repository, provider va `TripService`.

Moi truong test dung:

```text
InMemoryRoutingProvider
FixtureStationDataService
StaticEnvironmentProvider
InMemoryGeocoder
```

Moi truong runtime co the dung:

```text
GoongRoutingProvider
VinFastStationDataService
OpenMeteoEnvironmentProvider
GoongGeocoder
```

Neu test vo tinh goi API that, kiem tra `APP_ENV` va file dependency nay dau tien.

## 9. Database

Database models nam tai [`src/packages/core/trips/infrastructure/models.py`](../src/packages/core/trips/infrastructure/models.py).

Repository chinh:

```text
src/packages/core/trips/infrastructure/sqlalchemy_repository.py
src/packages/core/auth/infrastructure/repository.py
src/packages/core/policies/infrastructure/sqlalchemy_repository.py
```

Bang chinh hien co:

```text
users
auth_sessions
user_vehicles
vehicle_profiles
trips
policy_configs
plan_versions
```

Migration nam tai [`migrations/versions/`](../migrations/versions/). Khi sua schema: sua model, tao migration, chay migration va bo sung test.

## 10. F2: explanation, version, confirm va reject

F2 nam chu yeu tai:

```text
src/packages/core/trips/application/service.py
src/packages/core/trips/infrastructure/sqlalchemy_repository.py
src/apps/api/routes/trips.py
src/packages/agent/integrations/explanations.py
src/packages/agent/integrations/llm.py
```

API chinh:

```text
POST /api/v1/plans/{plan_id}/confirm
POST /api/v1/plans/{plan_id}/reject
POST /api/v1/trips/{trip_id}/plans/{version}/confirm
POST /api/v1/trips/{trip_id}/plans/{version}/reject
GET  /api/v1/trips/{trip_id}/plans
```

LLM chi duoc xep hang hoac giai thich cac phuong an da an toan. LLM khong duoc quyet dinh route, SOC, feasibility, reserve hoac plan state.

## 11. Trang thai F3/F4

Code da co skeleton:

```text
src/packages/core/monitoring/
src/packages/core/simulator/
```

Tuy nhien `TelemetryService`, `MonitoringService`, `PlanningRun`, simulator va replan workflow chua hoan thien nhu tai lieu. Khong nen hieu viec co thu muc la feature da xong.

Tài liệu triển khai nguồn chuẩn:

- [`FEATURE_3_IMPLEMENT.md`](FEATURE_3_IMPLEMENT.md) cho telemetry, monitoring và simulator.
- [`FEATURE_4_IMPLEMENT.md`](FEATURE_4_IMPLEMENT.md) cho AI event decision và replanning.

## 12. Test structure

### Agent tests

```text
tests/test_agents/test_graph.py
```

Kiem tra graph, state va cac nhanh feasible/infeasible.

### Core tests

```text
tests/test_core/test_energy_planning.py
tests/test_core/test_feasibility.py
tests/test_core/test_adaptive_station_planner.py
tests/test_core/test_planning_detour.py
tests/test_core/test_policy_assumptions.py
tests/test_core/test_vehicle_profile_catalog.py
tests/test_core/test_recovery_supervisor.py
```

### API tests

```text
tests/test_api/test_trips.py
tests/test_api/test_planning.py
tests/test_api/test_f2.py
tests/test_api/test_auth.py
tests/test_api/test_routes.py
tests/test_api/test_places.py
```

Khi sua F1:

```powershell
pytest -q tests/test_core/test_energy_planning.py
pytest -q tests/test_core/test_feasibility.py
pytest -q tests/test_core/test_adaptive_station_planner.py
pytest -q tests/test_agents/test_graph.py
pytest -q tests/test_api/test_planning.py
```

Khi sua confirm/reject/version:

```powershell
pytest -q tests/test_api/test_f2.py
```

## 13. Thu tu doc code cho nguoi moi

1. [`ARCHITECTURE.md`](../ARCHITECTURE.md)
2. [`src/apps/api/main.py`](../src/apps/api/main.py)
3. [`src/apps/api/routes/trips.py`](../src/apps/api/routes/trips.py)
4. [`src/packages/contracts/trips.py`](../src/packages/contracts/trips.py)
5. [`src/packages/core/trips/application/service.py`](../src/packages/core/trips/application/service.py)
6. [`src/packages/agent/planning/graph.py`](../src/packages/agent/planning/graph.py)
7. [`src/packages/agent/planning/state.py`](../src/packages/agent/planning/state.py)
8. [`src/packages/agent/planning/nodes/planning_nodes.py`](../src/packages/agent/planning/nodes/planning_nodes.py)
9. [`src/packages/core/trips/infrastructure/energy_tool.py`](../src/packages/core/trips/infrastructure/energy_tool.py)
10. [`src/packages/core/trips/infrastructure/feasibility_tool.py`](../src/packages/core/trips/infrastructure/feasibility_tool.py)
11. [`src/packages/core/trips/infrastructure/routing.py`](../src/packages/core/trips/infrastructure/routing.py)
12. `tests/test_agents/` va `tests/test_api/`.

Chuoi can nho de hieu F1:

```text
routes/trips.py
  -> TripService
  -> planning_agent
  -> graph.py
  -> planning_nodes.py
  -> Routing / Station / Energy / Feasibility
  -> PlanProposal hoac NoFeasiblePlan
```

Chuoi can nho de hieu F2:

```text
plan_versions
  -> TripService.confirm_plan()
  -> TripService.reject_plan()
  -> repository.apply_plan_decision()
```

## 14. Quy tac khi sua code

- API schema dat trong `contracts`, khong tao schema trung trong route.
- Business rule dat trong `application` hoac `domain`, khong dat trong React.
- Provider ngoai dat trong `infrastructure`.
- Agent tra structured result; `TripService` luu business state.
- Khong de LLM quyet dinh logic an toan.
- Thay doi database phai co migration.
- Thay doi thuat toan phai co unit test va API test.
- Khi debug F1, xem file run tuong ung trong `log_F1`.
- Khong dung provider that trong unit test.

## 15. Tom tat mot cau cho moi thu muc

```text
apps/api            = API khoi dong o dau va endpoint nao
apps/web            = giao dien nguoi dung
contracts           = du lieu API co hinh dang gi
core/domain         = entities va business states
core/application    = use cases va services
core/infrastructure = database, providers va tools
agent/planning      = graph lap ke hoach
tests               = cach he thong duoc kiem chung
migrations          = lich su thay doi database
docs                = yeu cau va thiet ke can follow
```
