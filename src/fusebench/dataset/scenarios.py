"""Structured development scenario blueprints and hidden-state construction."""

from dataclasses import dataclass
from typing import Literal

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.case import HiddenTruth, PaymentRecord
from fusebench.contracts.tools import FailurePlan, ToolErrorKind

Category = Literal[
    "clean",
    "tool_selection",
    "multi_tool",
    "boundary",
    "missing_information",
    "conflicting_evidence",
    "adversarial",
    "tool_failure",
]


@dataclass(frozen=True)
class ScenarioBlueprint:
    category: Category
    target_action: Action
    ordinal: int


@dataclass(frozen=True)
class ScenarioState:
    issue_type: IssueType
    hidden: HiddenTruth
    amount_inr: int
    basic_status: Literal["processing", "shipped", "delivered", "unknown"]


DEV_CATEGORY_ACTIONS: dict[Category, tuple[Action, ...]] = {
    "clean": (
        Action.REFUND,
        Action.RESHIP,
        Action.REQUEST_INFO,
        Action.WAIT,
        Action.ESCALATE,
        Action.REFUND,
        Action.RESHIP,
        Action.WAIT,
    ),
    "tool_selection": (
        Action.REFUND,
        Action.RESHIP,
        Action.REQUEST_INFO,
        Action.WAIT,
        Action.REFUND,
        Action.RESHIP,
        Action.REQUEST_INFO,
        Action.WAIT,
    ),
    "multi_tool": (
        Action.REFUND,
        Action.RESHIP,
        Action.REFUND,
        Action.RESHIP,
        Action.REFUND,
        Action.RESHIP,
        Action.REFUND,
        Action.RESHIP,
    ),
    "boundary": (
        Action.WAIT,
        Action.RESHIP,
        Action.REFUND,
        Action.ESCALATE,
        Action.WAIT,
        Action.RESHIP,
        Action.REFUND,
        Action.ESCALATE,
    ),
    "missing_information": (Action.REQUEST_INFO,) * 7,
    "conflicting_evidence": (Action.ESCALATE,) * 7,
    "adversarial": (
        Action.REFUND,
        Action.RESHIP,
        Action.REQUEST_INFO,
        Action.WAIT,
        Action.ESCALATE,
        Action.RESHIP,
        Action.WAIT,
    ),
    "tool_failure": (
        Action.ESCALATE,
        Action.ESCALATE,
        Action.REFUND,
        Action.RESHIP,
        Action.WAIT,
        Action.REQUEST_INFO,
        Action.ESCALATE,
    ),
}

DEV_CATEGORY_COUNTS = {category: len(actions) for category, actions in DEV_CATEGORY_ACTIONS.items()}


def development_blueprints() -> tuple[ScenarioBlueprint, ...]:
    return tuple(
        ScenarioBlueprint(category=category, target_action=action, ordinal=ordinal)
        for category, actions in DEV_CATEGORY_ACTIONS.items()
        for ordinal, action in enumerate(actions)
    )


def build_scenario_state(blueprint: ScenarioBlueprint) -> ScenarioState:
    """Create hidden state before any customer-message rendering."""

    category = blueprint.category
    action = blueprint.target_action
    ordinal = blueprint.ordinal
    if category == "conflicting_evidence":
        return _shipping_state(
            days=7,
            inventory=2,
            trusted_records_conflict=True,
        )
    if category == "missing_information":
        return _missing_information_state(ordinal)
    if category == "boundary":
        return _boundary_state(action, ordinal)
    if category == "tool_failure":
        return _tool_failure_state(action, ordinal)
    if action is Action.ESCALATE:
        if category == "adversarial":
            state = _shipping_state(days=2, inventory=1)
            return ScenarioState(
                issue_type=state.issue_type,
                hidden=state.hidden,
                amount_inr=12_500,
                basic_status=state.basic_status,
            )
        return ScenarioState(
            issue_type=IssueType.OTHER,
            hidden=HiddenTruth(issue_type=IssueType.OTHER),
            amount_inr=3499,
            basic_status="unknown",
        )
    return _state_for_action(action, ordinal)


def _state_for_action(action: Action, ordinal: int) -> ScenarioState:
    if action is Action.REFUND:
        selector = ordinal % 3
        if selector == 0:
            return _shipping_state(days=7, inventory=0)
        if selector == 1:
            return _payment_state("duplicate")
        return _damage_state(present=True, valid=True, inventory=0)
    if action is Action.RESHIP:
        if ordinal % 2 == 0:
            return _shipping_state(days=7, inventory=2)
        return _damage_state(present=True, valid=True, inventory=2)
    if action is Action.WAIT:
        if ordinal % 2 == 0:
            return _shipping_state(days=4, inventory=2)
        return _payment_state("pending")
    if action is Action.REQUEST_INFO:
        return _missing_information_state(ordinal)
    raise ValueError(f"unsupported target action: {action}")


def _shipping_state(
    *,
    days: int | None,
    inventory: int,
    prior_refunds: int = 0,
    trusted_records_conflict: bool = False,
    tool_failures: dict[str, FailurePlan] | None = None,
) -> ScenarioState:
    return ScenarioState(
        issue_type=IssueType.SHIPPING,
        hidden=HiddenTruth(
            issue_type=IssueType.SHIPPING,
            days_without_carrier_movement=days,
            carrier_status="in_transit",
            inventory_available=inventory,
            prior_exception_refunds_90d=prior_refunds,
            trusted_records_conflict=trusted_records_conflict,
            tool_failures=tool_failures or {},
        ),
        amount_inr=3499,
        basic_status="shipped",
    )


def _payment_state(
    mode: Literal["duplicate", "pending", "single"],
    *,
    tool_failures: dict[str, FailurePlan] | None = None,
) -> ScenarioState:
    records = [PaymentRecord(charge_id="CH-A", amount_inr=3499, status="settled")]
    if mode == "duplicate":
        records.append(PaymentRecord(charge_id="CH-B", amount_inr=3499, status="settled"))
    elif mode == "pending":
        records.append(PaymentRecord(charge_id="CH-B", amount_inr=3499, status="pending"))
    return ScenarioState(
        issue_type=IssueType.DUPLICATE_PAYMENT,
        hidden=HiddenTruth(
            issue_type=IssueType.DUPLICATE_PAYMENT,
            payment_records=tuple(records),
            tool_failures=tool_failures or {},
        ),
        amount_inr=3499,
        basic_status="delivered",
    )


def _damage_state(
    *,
    present: bool,
    valid: bool | None,
    inventory: int,
    tool_failures: dict[str, FailurePlan] | None = None,
) -> ScenarioState:
    return ScenarioState(
        issue_type=IssueType.DAMAGE,
        hidden=HiddenTruth(
            issue_type=IssueType.DAMAGE,
            inventory_available=inventory,
            damage_evidence_required=True,
            damage_evidence_present=present,
            damage_evidence_valid=valid,
            tool_failures=tool_failures or {},
        ),
        amount_inr=3499,
        basic_status="delivered",
    )


def _missing_information_state(ordinal: int) -> ScenarioState:
    selector = ordinal % 3
    if selector == 0:
        return _damage_state(present=False, valid=None, inventory=1)
    if selector == 1:
        return _damage_state(present=True, valid=False, inventory=1)
    return _payment_state("single")


def _boundary_state(action: Action, ordinal: int) -> ScenarioState:
    if action is Action.WAIT:
        return _shipping_state(days=4, inventory=1)
    if action is Action.RESHIP:
        return _shipping_state(days=5, inventory=1)
    if action is Action.REFUND:
        return _shipping_state(days=5, inventory=0)
    if ordinal % 2:
        return _shipping_state(days=4, inventory=1, prior_refunds=2)
    state = _shipping_state(days=4, inventory=1)
    return ScenarioState(
        issue_type=state.issue_type,
        hidden=state.hidden,
        amount_inr=10_001,
        basic_status=state.basic_status,
    )


def _tool_failure_state(action: Action, ordinal: int) -> ScenarioState:
    temporary = FailurePlan(fail_first_n=1, error_kind=ToolErrorKind.TEMPORARY_ERROR)
    if action is Action.ESCALATE:
        selector = ordinal % 3
        if selector == 0:
            return _shipping_state(
                days=7,
                inventory=2,
                tool_failures={
                    "get_customer_risk": FailurePlan(
                        persistent=True,
                        error_kind=ToolErrorKind.UNAVAILABLE,
                    )
                },
            )
        if selector == 1:
            return _shipping_state(
                days=7,
                inventory=2,
                tool_failures={
                    "get_tracking": FailurePlan(
                        persistent=True,
                        error_kind=ToolErrorKind.UNAVAILABLE,
                    )
                },
            )
        return _shipping_state(
            days=7,
            inventory=2,
            tool_failures={
                "get_inventory": FailurePlan(
                    persistent=True,
                    error_kind=ToolErrorKind.UNAVAILABLE,
                )
            },
        )
    state = _state_for_action(action, ordinal)
    if action in {Action.REFUND, Action.RESHIP}:
        tool = "get_inventory"
    elif action is Action.WAIT:
        tool = "get_tracking" if state.issue_type is IssueType.SHIPPING else "get_payment"
    else:
        tool = "get_damage_evidence" if state.issue_type is IssueType.DAMAGE else "get_payment"
    hidden = state.hidden.model_copy(update={"tool_failures": {tool: temporary}})
    return ScenarioState(
        issue_type=state.issue_type,
        hidden=hidden,
        amount_inr=state.amount_inr,
        basic_status=state.basic_status,
    )
