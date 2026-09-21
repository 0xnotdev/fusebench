import pytest
from pydantic import ValidationError

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.case import BenchmarkCase, HiddenTruth, PaymentRecord, VisibleCase
from fusebench.contracts.tools import FailurePlan, ToolErrorKind


def make_case() -> BenchmarkCase:
    return BenchmarkCase(
        visible=VisibleCase(
            case_id="DEV_0001",
            customer_id="CUS-1",
            order_id="ORD-1",
            sku="SKU-1",
            customer_message="Tracking has not moved.",
            amount_inr=3499,
            basic_status="shipped",
        ),
        hidden=HiddenTruth(
            issue_type=IssueType.SHIPPING,
            days_without_carrier_movement=7,
            carrier_status="in_transit",
            inventory_available=3,
            tool_failures={
                "get_tracking": FailurePlan(
                    fail_first_n=1,
                    error_kind=ToolErrorKind.TEMPORARY_ERROR,
                )
            },
        ),
        category="tool_failure",
        gold_action=Action.RESHIP,
        minimal_required_read_tools={"get_tracking", "get_inventory"},
        allowed_autonomous_actions={Action.RESHIP},
        generation_metadata={"semantic_scenario_id": "shipping-stalled-stock"},
    )


def test_visible_case_rejects_evaluator_or_hidden_fields() -> None:
    with pytest.raises(ValidationError):
        VisibleCase(
            case_id="DEV_0001",
            customer_id="CUS-1",
            order_id="ORD-1",
            sku="SKU-1",
            customer_message="Refund me",
            amount_inr=3499,
            basic_status="shipped",
            gold_action="REFUND",  # type: ignore[call-arg]
        )


def test_payment_record_requires_nonnegative_amount() -> None:
    with pytest.raises(ValidationError):
        PaymentRecord(charge_id="CH-1", amount_inr=-1, status="settled")


def test_benchmark_case_round_trips_with_sets_and_failure_plans() -> None:
    case = make_case()

    restored = BenchmarkCase.model_validate_json(case.model_dump_json())

    assert restored == case
    assert restored.hidden.tool_failures["get_tracking"].fail_first_n == 1


def test_case_models_are_immutable() -> None:
    case = make_case()

    with pytest.raises(ValidationError):
        case.visible.amount_inr = 12_000
