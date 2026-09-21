from collections.abc import Mapping
from typing import Any

import pytest

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.case import BenchmarkCase, HiddenTruth, PaymentRecord, VisibleCase
from fusebench.contracts.tools import FailurePlan, ToolErrorKind
from fusebench.policy.oracle import decide


def build_case(
    issue_type: IssueType,
    *,
    amount_inr: int = 3499,
    category: str = "clean",
    hidden_overrides: Mapping[str, Any] | None = None,
) -> BenchmarkCase:
    hidden_values: dict[str, Any] = {
        "issue_type": issue_type,
        "days_without_carrier_movement": 2 if issue_type is IssueType.SHIPPING else None,
        "carrier_status": "in_transit" if issue_type is IssueType.SHIPPING else None,
        "inventory_available": 2,
        "payment_records": (),
        "damage_evidence_required": issue_type is IssueType.DAMAGE,
        "damage_evidence_present": None,
        "damage_evidence_valid": None,
    }
    hidden_values.update(hidden_overrides or {})
    return BenchmarkCase(
        visible=VisibleCase(
            case_id="CASE-1",
            customer_id="CUS-1",
            order_id="ORD-1",
            sku="SKU-1",
            customer_message="A synthetic customer request",
            amount_inr=amount_inr,
            basic_status="shipped",
        ),
        hidden=HiddenTruth(**hidden_values),
        category=category,  # type: ignore[arg-type]
        gold_action=Action.ESCALATE,
        minimal_required_read_tools=frozenset(),
        allowed_autonomous_actions=frozenset(),
        generation_metadata={},
    )


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(10_000, Action.WAIT), (10_001, Action.ESCALATE)],
)
def test_amount_boundary(amount: int, expected: Action) -> None:
    decision = decide(build_case(IssueType.SHIPPING, amount_inr=amount))

    assert decision.action is expected
    if amount == 10_001:
        assert decision.minimal_required_read_tools == frozenset()


@pytest.mark.parametrize(
    ("prior_refunds", "expected"),
    [(1, Action.WAIT), (2, Action.ESCALATE)],
)
def test_prior_refund_boundary(prior_refunds: int, expected: Action) -> None:
    case = build_case(
        IssueType.SHIPPING,
        hidden_overrides={"prior_exception_refunds_90d": prior_refunds},
    )

    decision = decide(case)

    assert decision.action is expected
    if expected is Action.ESCALATE:
        assert "get_customer_risk" in decision.minimal_required_read_tools


def test_global_conflict_overrides_issue_specific_refund() -> None:
    case = build_case(
        IssueType.DUPLICATE_PAYMENT,
        hidden_overrides={
            "trusted_records_conflict": True,
            "payment_records": (
                PaymentRecord(charge_id="CH-1", amount_inr=3499, status="settled"),
                PaymentRecord(charge_id="CH-2", amount_inr=3499, status="settled"),
            ),
        },
    )

    decision = decide(case)

    assert decision.action is Action.ESCALATE
    assert decision.minimal_required_read_tools == frozenset(
        {"get_payment", "get_customer_risk"}
    )


@pytest.mark.parametrize(
    ("days", "inventory", "expected"),
    [
        (4, 1, Action.WAIT),
        (5, 1, Action.RESHIP),
        (5, 0, Action.REFUND),
        (9, 1, Action.RESHIP),
        (9, 0, Action.REFUND),
    ],
)
def test_shipping_boundaries(days: int, inventory: int, expected: Action) -> None:
    case = build_case(
        IssueType.SHIPPING,
        hidden_overrides={
            "days_without_carrier_movement": days,
            "inventory_available": inventory,
        },
    )

    assert decide(case).action is expected


def test_delivered_customer_conflict_escalates() -> None:
    case = build_case(
        IssueType.SHIPPING,
        hidden_overrides={"carrier_status": "delivered"},
    )

    assert decide(case).action is Action.ESCALATE
    assert decide(case).minimal_required_read_tools == frozenset({"get_tracking"})


def test_missing_shipping_movement_requests_customer_information() -> None:
    case = build_case(
        IssueType.SHIPPING,
        category="missing_information",
        hidden_overrides={"days_without_carrier_movement": None},
    )

    assert decide(case).action is Action.REQUEST_INFO


def test_persistent_tracking_failure_escalates() -> None:
    case = build_case(
        IssueType.SHIPPING,
        category="tool_failure",
        hidden_overrides={
            "tool_failures": {
                "get_tracking": FailurePlan(
                    persistent=True,
                    error_kind=ToolErrorKind.UNAVAILABLE,
                )
            }
        },
    )

    assert decide(case).action is Action.ESCALATE


def test_shipping_stall_requires_tracking_and_inventory() -> None:
    case = build_case(
        IssueType.SHIPPING,
        hidden_overrides={"days_without_carrier_movement": 7, "inventory_available": 1},
    )

    decision = decide(case)

    assert decision.action is Action.RESHIP
    assert decision.minimal_required_read_tools == frozenset(
        {"get_tracking", "get_inventory", "get_customer_risk"}
    )
    assert decision.allowed_autonomous_actions == frozenset({Action.RESHIP})


def test_persistent_customer_risk_failure_blocks_an_autonomous_action() -> None:
    case = build_case(
        IssueType.SHIPPING,
        category="tool_failure",
        hidden_overrides={
            "days_without_carrier_movement": 7,
            "inventory_available": 1,
            "tool_failures": {
                "get_customer_risk": FailurePlan(
                    persistent=True,
                    error_kind=ToolErrorKind.UNAVAILABLE,
                )
            },
        },
    )

    decision = decide(case)

    assert decision.action is Action.ESCALATE
    assert decision.minimal_required_read_tools == frozenset(
        {"get_tracking", "get_inventory", "get_customer_risk"}
    )


@pytest.mark.parametrize(
    ("records", "expected", "tools"),
    [
        (
            (
                PaymentRecord(charge_id="CH-1", amount_inr=3499, status="settled"),
                PaymentRecord(charge_id="CH-2", amount_inr=3499, status="settled"),
            ),
            Action.REFUND,
            {"get_payment", "get_customer_risk"},
        ),
        (
            (
                PaymentRecord(charge_id="CH-1", amount_inr=3499, status="settled"),
                PaymentRecord(charge_id="CH-2", amount_inr=3499, status="pending"),
            ),
            Action.WAIT,
            {"get_payment"},
        ),
        (
            (PaymentRecord(charge_id="CH-1", amount_inr=3499, status="settled"),),
            Action.REQUEST_INFO,
            {"get_payment"},
        ),
    ],
)
def test_duplicate_payment_rules(
    records: tuple[PaymentRecord, ...], expected: Action, tools: set[str]
) -> None:
    case = build_case(
        IssueType.DUPLICATE_PAYMENT,
        hidden_overrides={"payment_records": records},
    )

    decision = decide(case)

    assert decision.action is expected
    assert decision.minimal_required_read_tools == frozenset(tools)


@pytest.mark.parametrize(
    ("present", "valid", "inventory", "expected", "tools"),
    [
        (False, None, 1, Action.REQUEST_INFO, {"get_damage_evidence"}),
        (True, False, 1, Action.REQUEST_INFO, {"get_damage_evidence"}),
        (
            True,
            True,
            1,
            Action.RESHIP,
            {"get_damage_evidence", "get_inventory", "get_customer_risk"},
        ),
        (
            True,
            True,
            0,
            Action.REFUND,
            {"get_damage_evidence", "get_inventory", "get_customer_risk"},
        ),
    ],
)
def test_damage_rules(
    present: bool,
    valid: bool | None,
    inventory: int,
    expected: Action,
    tools: set[str],
) -> None:
    case = build_case(
        IssueType.DAMAGE,
        hidden_overrides={
            "damage_evidence_present": present,
            "damage_evidence_valid": valid,
            "inventory_available": inventory,
        },
    )

    decision = decide(case)

    assert decision.action is expected
    assert decision.minimal_required_read_tools == frozenset(tools)


def test_unsupported_issue_escalates_without_autonomous_permission() -> None:
    decision = decide(build_case(IssueType.OTHER))

    assert decision.action is Action.ESCALATE
    assert decision.allowed_autonomous_actions == frozenset()
