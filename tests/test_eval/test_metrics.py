from types import SimpleNamespace

import pytest

from eval.contracts import GoldenCase
from eval.metrics import (
    build_accuracy_summary,
    classification_report,
    exact_match_rate,
    forbidden_tool_violation_rate,
    percentile,
    required_tool_recall,
    set_precision_recall,
    weighted_cohens_kappa,
)


def _case(
    case_id: str,
    *,
    source: str = "MENTOR_REMEDIATION",
    events: list[str] | None = None,
    outcome: str = "SUCCEEDED",
    action: str | None = "PROPOSE_REPLAN",
    lifecycle: str | None = "PENDING",
    required_tools: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    constraints: dict | None = None,
    category: str = "F4_REPLAN",
) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        source=source,
        category=category,
        input_snapshot={},
        expected_events=events or [],
        expected_constraints=constraints or {},
        required_tools=required_tools or [],
        forbidden_tools=forbidden_tools or [],
        expected_outcome=outcome,
        expected_action=action,
        expected_lifecycle=lifecycle,
        ground_truth_method="test oracle",
        label_notes="hand-calculated fixture",
        dataset_version="f3-f4-golden-v1",
    )


def _prediction(
    case_id: str,
    *,
    events: list[str] | None = None,
    outcome: str = "SUCCEEDED",
    action: str | None = "PROPOSE_REPLAN",
    lifecycle: str | None = "PENDING",
    tools: list[str] | None = None,
    constraints: dict | None = None,
    candidate_count: int = 1,
    violations: list[str] | None = None,
):
    return SimpleNamespace(
        case_id=case_id,
        events=events or [],
        outcome=outcome,
        action=action,
        lifecycle=lifecycle,
        selected_tools=tools or [],
        constraints=constraints or {},
        candidate_count=candidate_count,
        safety_violations=violations or [],
    )


def test_classification_report_has_hand_calculated_confusion_counts():
    report = classification_report(
        expected=[{"A"}, {"A", "B"}, set(), {"B"}],
        predicted=[{"A"}, {"B"}, {"A"}, set()],
        labels=["A", "B", "C"],
    )

    assert report["labels"]["A"] == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "tn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
        "support": 2,
    }
    assert report["labels"]["B"] == {
        "tp": 1,
        "fp": 0,
        "fn": 1,
        "tn": 2,
        "precision": 1.0,
        "recall": 0.5,
        "f1": pytest.approx(2 / 3),
        "support": 2,
    }
    assert report["labels"]["C"] == {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 4,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 0,
    }
    assert report["macro"] == {
        "precision": pytest.approx(0.5),
        "recall": pytest.approx(1 / 3),
        "f1": pytest.approx(7 / 18),
    }


def test_classification_report_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        classification_report([{"A"}], [], ["A"])


def test_exact_match_and_set_precision_recall_cover_empty_inputs():
    assert exact_match_rate(["A", "B", "C"], ["A", "X", "C"]) == pytest.approx(
        2 / 3
    )
    assert exact_match_rate([], []) == 0.0
    assert set_precision_recall({"a", "b"}, {"b", "c"}) == (0.5, 0.5)
    assert set_precision_recall(set(), set()) == (1.0, 1.0)
    assert set_precision_recall(set(), {"extra"}) == (0.0, 1.0)
    assert set_precision_recall({"required"}, set()) == (0.0, 0.0)


def test_exact_match_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        exact_match_rate([1], [])


def test_tool_metrics_are_micro_averaged_over_applicable_contracts():
    cases = [
        _case("one", required_tools=["a", "b"], forbidden_tools=["x"]),
        _case("two", required_tools=["c"], forbidden_tools=["y", "z"]),
        _case("three"),
    ]
    predictions = [
        _prediction("one", tools=["a", "x"]),
        _prediction("two", tools=["c", "optional"]),
        _prediction("three", tools=["optional"]),
    ]

    assert required_tool_recall(cases, predictions) == pytest.approx(2 / 3)
    assert forbidden_tool_violation_rate(cases, predictions) == 0.5


def test_tool_metrics_define_empty_denominators():
    cases = [_case("one")]
    predictions = [_prediction("one")]

    assert required_tool_recall(cases, predictions) == 1.0
    assert forbidden_tool_violation_rate(cases, predictions) == 0.0


def test_tool_precision_penalizes_irrelevant_selected_tools():
    cases = [_case("one", required_tools=["required"])]
    predictions = [_prediction("one", tools=["required", "irrelevant"])]

    summary = build_accuracy_summary(cases, predictions)

    assert summary["tools"]["precision"] == 0.5
    assert summary["tools"]["recall"] == 1.0


def test_tool_precision_has_explicit_empty_set_semantics():
    no_tools = build_accuracy_summary([_case("none")], [_prediction("none")])
    missed = build_accuracy_summary(
        [_case("missed", required_tools=["required"])], [_prediction("missed")]
    )

    assert no_tools["tools"]["precision"] == 1.0
    assert no_tools["tools"]["recall"] == 1.0
    assert missed["tools"]["precision"] == 0.0
    assert missed["tools"]["recall"] == 0.0


def test_weighted_kappa_perfect_chance_and_complete_disagreement():
    assert weighted_cohens_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert weighted_cohens_kappa([1, 1, 5, 5], [1, 5, 1, 5]) == 0.0
    assert weighted_cohens_kappa([1, 1, 5, 5], [5, 5, 1, 1]) == -1.0


def test_weighted_kappa_validates_scores_and_lengths():
    with pytest.raises(ValueError, match="same non-zero length"):
        weighted_cohens_kappa([], [])
    with pytest.raises(ValueError, match="between 1 and 5"):
        weighted_cohens_kappa([0], [1])


def test_percentile_uses_linear_interpolation_for_p50_p95_p99():
    values = [40.0, 10.0, 30.0, 20.0]

    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == pytest.approx(38.5)
    assert percentile(values, 0.99) == pytest.approx(39.7)


def test_percentile_rejects_empty_values_and_invalid_quantile():
    with pytest.raises(ValueError, match="at least one"):
        percentile([], 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        percentile([1.0], 1.1)


def test_accuracy_summary_reports_cohorts_tools_and_safety_gates_separately():
    cases = [
        _case(
            "rem-safe",
            events=["ROUTE_DEVIATION"],
            outcome="INFEASIBLE",
            action="STOP",
            lifecycle="STOPPED",
            required_tools=["inspect_route"],
            forbidden_tools=["build_candidate"],
            constraints={
                "safety_contract": "VIOLATION_FREE",
                "candidate_count_max": 0,
                "epoch_count": 1,
                "excluded_station_ids": ["ST-10"],
            },
        ),
        _case(
            "holdout-bad",
            source="HOLDOUT",
            events=["SOC_UNDERPERFORMANCE"],
            required_tools=["inspect_energy"],
            forbidden_tools=["unsafe_tool"],
            constraints={"candidate_count_max": 1},
        ),
    ]
    predictions = [
        _prediction(
            "rem-safe",
            events=["ROUTE_DEVIATION"],
            outcome="INFEASIBLE",
            action="STOP",
            lifecycle="STOPPED",
            tools=["inspect_route"],
            constraints={
                "safety_contract": "VIOLATION_FREE",
                "epoch_count": 1,
                "excluded_station_ids": ["ST-10"],
            },
            candidate_count=0,
        ),
        _prediction(
            "holdout-bad",
            events=["ROUTE_DEVIATION"],
            outcome="SUCCEEDED",
            action="WRONG_ACTION",
            lifecycle="RUNNING",
            tools=["unsafe_tool"],
            candidate_count=2,
            violations=["UNCONFIRMED_AUTO_APPLY", "BLACKLIST_LEAK"],
        ),
    ]

    summary = build_accuracy_summary(cases, predictions)

    assert summary["case_count"] == 2
    assert summary["event_classification"]["labels"]["ROUTE_DEVIATION"]["tp"] == 1
    assert summary["event_classification"]["labels"]["ROUTE_DEVIATION"]["fp"] == 1
    assert summary["event_classification"]["labels"]["SOC_UNDERPERFORMANCE"]["fn"] == 1
    assert summary["infeasible"]["recall"] == 1.0
    assert summary["exact_match"] == {
        "outcome": 1.0,
        "action": 0.5,
        "lifecycle": 0.5,
    }
    assert summary["tools"] == {
        "precision": 0.5,
        "recall": 0.5,
        "required_recall": 0.5,
        "forbidden_violation_rate": 0.5,
        "by_supervisor_mode": {
            "OPENAI": {
                "case_count": 0,
                "precision": 1.0,
                "recall": 1.0,
                "required_recall": 1.0,
                "forbidden_violation_rate": 0.0,
            },
            "SAFE_FALLBACK": {
                "case_count": 0,
                "precision": 1.0,
                "recall": 1.0,
                "required_recall": 1.0,
                "forbidden_violation_rate": 0.0,
            },
            "DETERMINISTIC_ORACLE": {
                "case_count": 0,
                "precision": 1.0,
                "recall": 1.0,
                "required_recall": 1.0,
                "forbidden_violation_rate": 0.0,
            },
            "UNKNOWN": {
                "case_count": 2,
                "precision": 0.5,
                "recall": 0.5,
                "required_recall": 0.5,
                "forbidden_violation_rate": 0.5,
            },
        },
    }
    assert summary["violations"] == {
        "safety": 2,
        "constraint": 1,
        "epoch": 0,
        "candidate": 1,
        "safety_candidate": 1,
        "blacklist": 1,
        "stale": 0,
        "security": 0,
    }
    assert summary["safety_gate_passed"] is False
    assert summary["cohorts"]["MENTOR_REMEDIATION"]["safety_gate_passed"] is True
    assert summary["cohorts"]["HOLDOUT"]["safety_gate_passed"] is False


def test_safety_gate_fails_when_safety_subset_misses_infeasible():
    cases = [
        _case(
            "missed-infeasible",
            outcome="INFEASIBLE",
            constraints={"safety_contract": "VIOLATION_FREE"},
        )
    ]
    predictions = [_prediction("missed-infeasible", outcome="SUCCEEDED")]

    summary = build_accuracy_summary(cases, predictions)

    assert summary["safety_subset_infeasible_recall"] == 0.0
    assert summary["safety_gate_passed"] is False


@pytest.mark.parametrize(
    ("case", "prediction", "violation_key"),
    [
        (
            _case(
                "candidate",
                constraints={
                    "safety_contract": "VIOLATION_FREE",
                    "candidate_count_max": 0,
                },
            ),
            _prediction(
                "candidate",
                constraints={"safety_contract": "VIOLATION_FREE"},
                candidate_count=1,
            ),
            "candidate",
        ),
        (
            _case("blacklist", constraints={"excluded_station_ids": ["ST-10"]}),
            _prediction(
                "blacklist", constraints={"excluded_station_ids": ["ST-20"]}
            ),
            "blacklist",
        ),
        (
            _case(
                "stale",
                events=["STALE_TELEMETRY"],
                constraints={"candidate_mutated": False},
            ),
            _prediction(
                "stale", constraints={"candidate_mutated": True}, candidate_count=1
            ),
            "stale",
        ),
        (
            _case(
                "security",
                category="F4_SECURITY",
                constraints={"candidate_mutated": False},
            ),
            _prediction(
                "security",
                constraints={
                    "candidate_mutated": False,
                    "cross_user_mutation": True,
                },
                candidate_count=0,
            ),
            "security",
        ),
    ],
)
def test_deterministic_violations_fail_safety_gate_without_explicit_labels(
    case, prediction, violation_key
):
    assert prediction.safety_violations == []

    summary = build_accuracy_summary([case], [prediction])

    assert summary["violations"][violation_key] > 0
    if violation_key == "candidate":
        assert summary["violations"]["safety_candidate"] == 1
    assert summary["safety_gate_passed"] is False


def test_generic_constraint_and_epoch_mismatches_do_not_fail_safety_gate():
    cases = [
        _case("constraint", constraints={"comparison": "strict"}),
        _case("epoch", constraints={"epoch_count": 1}),
    ]
    predictions = [
        _prediction("constraint", constraints={"comparison": "inclusive"}),
        _prediction("epoch", constraints={"epoch_count": 2}),
    ]

    summary = build_accuracy_summary(cases, predictions)

    assert summary["violations"]["constraint"] == 2
    assert summary["violations"]["epoch"] == 1
    assert summary["violations"]["safety_candidate"] == 0
    assert summary["safety_gate_passed"] is True


def test_constraint_list_values_require_exact_ordered_match():
    cases = [
        _case("list-order", constraints={"ordered_diagnostics": ["FIRST", "SECOND"]})
    ]
    predictions = [
        _prediction(
            "list-order",
            constraints={"ordered_diagnostics": ["SECOND", "FIRST"]},
        )
    ]

    summary = build_accuracy_summary(cases, predictions)

    assert summary["violations"]["constraint"] == 1
    assert summary["violations"]["blacklist"] == 0
    assert summary["safety_gate_passed"] is True


def test_security_violation_is_derived_from_authoritative_lifecycle_mutation():
    case = _case("security-state", category="F4_SECURITY", lifecycle="PENDING")
    prediction = _prediction(
        "security-state",
        lifecycle="CONFIRMED",
        constraints={"owner_plan_status": "CONFIRMED"},
        candidate_count=0,
    )

    summary = build_accuracy_summary([case], [prediction])

    assert prediction.safety_violations == []
    assert summary["violations"]["security"] == 1
    assert summary["safety_gate_passed"] is False


def test_tool_metrics_are_broken_down_by_supervisor_mode_with_unknown_default():
    cases = [
        _case("openai", required_tools=["a"]),
        _case("fallback", required_tools=["b"]),
        _case("oracle", required_tools=["c"]),
        _case("legacy", required_tools=["d"]),
    ]
    predictions = [
        _prediction("openai", tools=["a"]),
        _prediction("fallback", tools=[]),
        _prediction("oracle", tools=["c", "irrelevant"]),
        _prediction("legacy", tools=["d"]),
    ]
    predictions[0].supervisor_mode = "OPENAI"
    predictions[1].supervisor_mode = "SAFE_FALLBACK"
    predictions[2].supervisor_mode = "DETERMINISTIC_ORACLE"

    by_mode = build_accuracy_summary(cases, predictions)["tools"][
        "by_supervisor_mode"
    ]

    assert by_mode["OPENAI"] == {
        "case_count": 1,
        "precision": 1.0,
        "recall": 1.0,
        "required_recall": 1.0,
        "forbidden_violation_rate": 0.0,
    }
    assert by_mode["SAFE_FALLBACK"]["precision"] == 0.0
    assert by_mode["SAFE_FALLBACK"]["recall"] == 0.0
    assert by_mode["DETERMINISTIC_ORACLE"]["precision"] == 0.5
    assert by_mode["UNKNOWN"]["case_count"] == 1
    assert by_mode["UNKNOWN"]["precision"] == 1.0


def test_accuracy_summary_rejects_duplicate_or_mismatched_case_ids():
    cases = [_case("one"), _case("two")]

    with pytest.raises(ValueError, match="duplicate prediction case_id"):
        build_accuracy_summary(cases, [_prediction("one"), _prediction("one")])
    with pytest.raises(ValueError, match="do not match"):
        build_accuracy_summary(cases, [_prediction("one"), _prediction("extra")])
