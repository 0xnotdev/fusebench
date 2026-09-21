"""Visible, hidden, and evaluator-side case contracts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.tools import FailurePlan


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisibleCase(ContractModel):
    case_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    customer_message: str = Field(min_length=1)
    amount_inr: int = Field(ge=0)
    basic_status: Literal["processing", "shipped", "delivered", "unknown"]


class PaymentRecord(ContractModel):
    charge_id: str = Field(min_length=1)
    amount_inr: int = Field(ge=0)
    status: Literal["pending", "settled", "failed", "refunded"]


class HiddenTruth(ContractModel):
    issue_type: IssueType
    days_without_carrier_movement: int | None = Field(default=None, ge=0)
    carrier_status: Literal["in_transit", "delivered", "exception", "unknown"] | None = None
    inventory_available: int | None = Field(default=None, ge=0)
    payment_records: tuple[PaymentRecord, ...] = ()
    damage_evidence_required: bool = False
    damage_evidence_present: bool | None = None
    damage_evidence_valid: bool | None = None
    prior_exception_refunds_90d: int = Field(default=0, ge=0)
    trusted_records_conflict: bool = False
    tool_failures: dict[str, FailurePlan] = Field(default_factory=dict)


class BenchmarkCase(ContractModel):
    visible: VisibleCase
    hidden: HiddenTruth
    category: Literal[
        "clean",
        "tool_selection",
        "multi_tool",
        "boundary",
        "missing_information",
        "conflicting_evidence",
        "adversarial",
        "tool_failure",
    ]
    gold_action: Action
    minimal_required_read_tools: frozenset[str]
    allowed_autonomous_actions: frozenset[Action]
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
