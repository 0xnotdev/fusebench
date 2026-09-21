import pytest

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.case import BenchmarkCase, HiddenTruth, PaymentRecord, VisibleCase
from fusebench.policy.oracle import decide


@pytest.fixture
def shipping_case() -> BenchmarkCase:
    provisional = BenchmarkCase(
        visible=VisibleCase(
            case_id="DEV_0001",
            customer_id="CUS-1",
            order_id="ORD-1",
            sku="SKU-1",
            customer_message="Tracking has not moved for a week.",
            amount_inr=3499,
            basic_status="shipped",
        ),
        hidden=HiddenTruth(
            issue_type=IssueType.SHIPPING,
            days_without_carrier_movement=7,
            carrier_status="in_transit",
            inventory_available=3,
            payment_records=(
                PaymentRecord(charge_id="CH-1", amount_inr=3499, status="settled"),
            ),
            prior_exception_refunds_90d=1,
            trusted_records_conflict=False,
        ),
        category="clean",
        gold_action=Action.RESHIP,
        minimal_required_read_tools=frozenset(),
        allowed_autonomous_actions=frozenset(),
        generation_metadata={"semantic_scenario_id": "shipping-stalled"},
    )
    oracle = decide(provisional)
    return provisional.model_copy(
        update={
            "gold_action": oracle.action,
            "minimal_required_read_tools": oracle.minimal_required_read_tools,
            "allowed_autonomous_actions": oracle.allowed_autonomous_actions,
        }
    )
