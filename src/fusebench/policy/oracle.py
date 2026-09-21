"""Deterministic source of benchmark labels and required-tool metadata."""

from pydantic import BaseModel, ConfigDict

from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action, IssueType
from fusebench.contracts.case import BenchmarkCase


class OracleDecision(BaseModel):
    """A deterministic evaluator decision that is never provider-visible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    minimal_required_read_tools: frozenset[str]
    allowed_autonomous_actions: frozenset[Action]
    reason_code: str


def _decision(action: Action, tools: set[str], reason_code: str) -> OracleDecision:
    allowed = frozenset({action}) if action in {Action.REFUND, Action.RESHIP} else frozenset()
    return OracleDecision(
        action=action,
        minimal_required_read_tools=frozenset(tools),
        allowed_autonomous_actions=allowed,
        reason_code=reason_code,
    )


def _persistently_unavailable(case: BenchmarkCase, tool: str) -> bool:
    plan = case.hidden.tool_failures.get(tool)
    return bool(plan and plan.persistent)


def decide(case: BenchmarkCase) -> OracleDecision:
    """Apply the frozen policy in precedence order without any model call."""

    if case.visible.amount_inr > 10_000:
        return _decision(Action.ESCALATE, set(), "AMOUNT_LIMIT")

    if case.hidden.issue_type is IssueType.SHIPPING:
        candidate = _decide_shipping(case)
    elif case.hidden.issue_type is IssueType.DUPLICATE_PAYMENT:
        candidate = _decide_duplicate_payment(case)
    elif case.hidden.issue_type is IssueType.DAMAGE:
        candidate = _decide_damage(case)
    else:
        candidate = _decision(Action.ESCALATE, set(), "UNSUPPORTED_ISSUE")

    risk_changes_outcome = candidate.action is not Action.ESCALATE and (
        case.hidden.prior_exception_refunds_90d >= 2
        or case.hidden.trusted_records_conflict
    )
    risk_required = candidate.action in AUTONOMOUS_ACTIONS or risk_changes_outcome
    if not risk_required:
        return candidate

    tools = set(candidate.minimal_required_read_tools) | {"get_customer_risk"}
    if _persistently_unavailable(case, "get_customer_risk"):
        return _decision(Action.ESCALATE, tools, "CUSTOMER_RISK_UNAVAILABLE")
    if case.hidden.prior_exception_refunds_90d >= 2:
        return _decision(Action.ESCALATE, tools, "PRIOR_REFUND_LIMIT")
    if case.hidden.trusted_records_conflict:
        return _decision(Action.ESCALATE, tools, "TRUSTED_RECORDS_CONFLICT")
    return _decision(candidate.action, tools, candidate.reason_code)


def _decide_shipping(case: BenchmarkCase) -> OracleDecision:
    tracking = {"get_tracking"}
    if _persistently_unavailable(case, "get_tracking"):
        return _decision(Action.ESCALATE, tracking, "TRACKING_UNAVAILABLE")
    if case.hidden.carrier_status == "delivered":
        return _decision(Action.ESCALATE, tracking, "DELIVERED_NONDELIVERY_CONFLICT")
    if case.hidden.carrier_status in {"exception", "unknown"}:
        return _decision(Action.ESCALATE, tracking, "CARRIER_STATE_UNCLEAR")
    if case.hidden.days_without_carrier_movement is None:
        return _decision(Action.REQUEST_INFO, tracking, "TRACKING_DETAIL_REQUIRED")
    if case.hidden.days_without_carrier_movement < 5:
        return _decision(Action.WAIT, tracking, "SHIPPING_WITHIN_WAIT_WINDOW")

    tools = {"get_tracking", "get_inventory"}
    if _persistently_unavailable(case, "get_inventory"):
        return _decision(Action.ESCALATE, tools, "INVENTORY_UNAVAILABLE")
    if case.hidden.inventory_available is None:
        return _decision(Action.ESCALATE, tools, "INVENTORY_UNKNOWN")
    if case.hidden.inventory_available > 0:
        return _decision(Action.RESHIP, tools, "SHIPPING_STALLED_STOCK_AVAILABLE")
    return _decision(Action.REFUND, tools, "SHIPPING_STALLED_OUT_OF_STOCK")


def _decide_duplicate_payment(case: BenchmarkCase) -> OracleDecision:
    tools = {"get_payment"}
    if _persistently_unavailable(case, "get_payment"):
        return _decision(Action.ESCALATE, tools, "PAYMENT_UNAVAILABLE")

    matching = [
        record
        for record in case.hidden.payment_records
        if record.amount_inr == case.visible.amount_inr
    ]
    settled_ids = {record.charge_id for record in matching if record.status == "settled"}
    if len(settled_ids) >= 2:
        return _decision(Action.REFUND, tools, "DUPLICATE_SETTLED_CHARGES")
    if settled_ids and any(record.status == "pending" for record in matching):
        return _decision(Action.WAIT, tools, "SECOND_CHARGE_PENDING")
    return _decision(Action.REQUEST_INFO, tools, "SECOND_CHARGE_EVIDENCE_REQUIRED")


def _decide_damage(case: BenchmarkCase) -> OracleDecision:
    evidence_tools = {"get_damage_evidence"}
    if _persistently_unavailable(case, "get_damage_evidence"):
        return _decision(Action.ESCALATE, evidence_tools, "DAMAGE_EVIDENCE_UNAVAILABLE")
    if not case.hidden.damage_evidence_present or not case.hidden.damage_evidence_valid:
        return _decision(Action.REQUEST_INFO, evidence_tools, "VALID_DAMAGE_EVIDENCE_REQUIRED")

    tools = {"get_damage_evidence", "get_inventory"}
    if _persistently_unavailable(case, "get_inventory"):
        return _decision(Action.ESCALATE, tools, "INVENTORY_UNAVAILABLE")
    if case.hidden.inventory_available is None:
        return _decision(Action.ESCALATE, tools, "INVENTORY_UNKNOWN")
    if case.hidden.inventory_available > 0:
        return _decision(Action.RESHIP, tools, "DAMAGE_VALID_STOCK_AVAILABLE")
    return _decision(Action.REFUND, tools, "DAMAGE_VALID_OUT_OF_STOCK")
