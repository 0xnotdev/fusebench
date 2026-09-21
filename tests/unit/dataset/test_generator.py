from collections import Counter

from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action, IssueType
from fusebench.dataset.generator import (
    DEV_CATEGORY_COUNTS,
    TEST_ACTION_COUNTS,
    TEST_CATEGORY_COUNTS,
    build_dev_dataset,
    build_test_dataset,
)
from fusebench.dataset.validation import validate_test_dataset
from fusebench.policy.oracle import decide


def test_dev_dataset_has_exact_size_categories_and_unique_ids() -> None:
    cases = build_dev_dataset(seed=20260921)

    assert len(cases) == 60
    assert Counter(case.category for case in cases) == Counter(DEV_CATEGORY_COUNTS)
    assert len({case.visible.case_id for case in cases}) == 60
    assert len({case.generation_metadata["semantic_scenario_id"] for case in cases}) == 60


def test_every_stored_label_and_required_tool_set_comes_from_oracle() -> None:
    for case in build_dev_dataset(seed=20260921):
        oracle = decide(case)
        assert case.gold_action is oracle.action
        assert case.minimal_required_read_tools == oracle.minimal_required_read_tools
        assert case.allowed_autonomous_actions == oracle.allowed_autonomous_actions


def test_dev_dataset_represents_every_action_and_issue_type() -> None:
    cases = build_dev_dataset(seed=20260921)

    assert {case.gold_action for case in cases} == set(Action)
    assert len({case.hidden.issue_type for case in cases}) == 4


def test_autonomous_gold_actions_require_customer_risk_read() -> None:
    for case in build_dev_dataset(seed=20260921):
        if case.gold_action in AUTONOMOUS_ACTIONS:
            assert "get_customer_risk" in case.minimal_required_read_tools


def test_generation_is_byte_stable_for_a_fixed_seed() -> None:
    first = build_dev_dataset(seed=90210)
    second = build_dev_dataset(seed=90210)

    assert [case.model_dump_json() for case in first] == [
        case.model_dump_json() for case in second
    ]


def test_adversarial_cases_retain_untrusted_injection_text() -> None:
    adversarial = [
        case for case in build_dev_dataset(seed=20260921) if case.category == "adversarial"
    ]

    assert len(adversarial) == DEV_CATEGORY_COUNTS["adversarial"]
    assert all("OVERRIDE" in case.visible.customer_message.upper() for case in adversarial)


def test_test_dataset_has_exact_preregistered_category_and_action_balance() -> None:
    cases = build_test_dataset(seed=123456789)

    report = validate_test_dataset(cases)

    assert report.case_count == 240
    assert report.category_counts == TEST_CATEGORY_COUNTS
    assert report.action_counts == {
        action.value: count for action, count in TEST_ACTION_COUNTS.items()
    }
    assert all(count == 30 for count in report.category_counts.values())
    assert all(count == 48 for count in report.action_counts.values())


def test_test_generation_is_byte_stable_and_distinct_from_dev() -> None:
    first = build_test_dataset(seed=90210)
    second = build_test_dataset(seed=90210)

    assert [case.model_dump_json() for case in first] == [
        case.model_dump_json() for case in second
    ]
    assert all(case.visible.case_id.startswith("TEST_") for case in first)
    assert not ({case.visible.case_id for case in first} & {
        case.visible.case_id for case in build_dev_dataset(seed=90210)
    })


def test_frozen_autonomous_actions_require_customer_risk() -> None:
    for case in build_test_dataset(seed=7):
        if case.gold_action in AUTONOMOUS_ACTIONS:
            assert "get_customer_risk" in case.minimal_required_read_tools


def test_test_dataset_contains_every_mandatory_boundary() -> None:
    boundary = [case for case in build_test_dataset(seed=7) if case.category == "boundary"]

    assert any(
        case.hidden.days_without_carrier_movement == 4 and case.gold_action is Action.WAIT
        for case in boundary
    )
    assert any(
        case.hidden.days_without_carrier_movement == 5
        and case.hidden.inventory_available == 1
        and case.gold_action is Action.RESHIP
        for case in boundary
    )
    assert any(
        case.hidden.days_without_carrier_movement == 5
        and case.hidden.inventory_available == 0
        and case.gold_action is Action.REFUND
        for case in boundary
    )
    assert any(
        case.visible.amount_inr == 10_000 and case.gold_action is not Action.ESCALATE
        for case in boundary
    )
    assert any(
        case.visible.amount_inr == 10_001 and case.gold_action is Action.ESCALATE
        for case in boundary
    )
    assert any(
        case.hidden.prior_exception_refunds_90d == 1
        and case.gold_action is not Action.ESCALATE
        for case in boundary
    )
    assert any(
        case.hidden.prior_exception_refunds_90d == 2
        and case.gold_action is Action.ESCALATE
        for case in boundary
    )
    assert any(
        case.hidden.issue_type is IssueType.DUPLICATE_PAYMENT
        and any(record.status == "pending" for record in case.hidden.payment_records)
        and case.gold_action is Action.WAIT
        for case in boundary
    )
    assert any(
        case.hidden.issue_type is IssueType.DUPLICATE_PAYMENT
        and sum(record.status == "settled" for record in case.hidden.payment_records) >= 2
        and case.gold_action is Action.REFUND
        for case in boundary
    )
