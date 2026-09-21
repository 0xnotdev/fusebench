"""Read-tool, action-tool, failure, and observation contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Strict immutable base for benchmark contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadTool(StrEnum):
    GET_TRACKING = "get_tracking"
    GET_PAYMENT = "get_payment"
    GET_INVENTORY = "get_inventory"
    GET_DAMAGE_EVIDENCE = "get_damage_evidence"
    GET_CUSTOMER_RISK = "get_customer_risk"


class ActionTool(StrEnum):
    REFUND_ORDER = "refund_order"
    RESHIP_ORDER = "reship_order"
    REQUEST_INFORMATION = "request_information"
    WAIT_FOR_CARRIER = "wait_for_carrier"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class ToolErrorKind(StrEnum):
    TEMPORARY_ERROR = "temporary_error"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"


class FailurePlan(ContractModel):
    fail_first_n: int = Field(default=0, ge=0)
    persistent: bool = False
    error_kind: ToolErrorKind


class GetTrackingInput(ContractModel):
    order_id: str = Field(min_length=1)


class GetPaymentInput(ContractModel):
    order_id: str = Field(min_length=1)


class GetInventoryInput(ContractModel):
    sku: str = Field(min_length=1)


class GetDamageEvidenceInput(ContractModel):
    order_id: str = Field(min_length=1)


class GetCustomerRiskInput(ContractModel):
    customer_id: str = Field(min_length=1)


class RefundInput(ContractModel):
    order_id: str = Field(min_length=1)


class ReshipInput(ContractModel):
    order_id: str = Field(min_length=1)


class RequestInformationInput(ContractModel):
    order_id: str = Field(min_length=1)
    field: str = Field(min_length=1)


class WaitForCarrierInput(ContractModel):
    order_id: str = Field(min_length=1)


class EscalateInput(ContractModel):
    order_id: str = Field(min_length=1)
    reason_code: str = Field(min_length=1, pattern=r".*\S.*")


class TrackingObservation(ContractModel):
    order_id: str
    carrier_status: Literal["in_transit", "delivered", "exception", "unknown"] | None
    days_without_movement: int | None = Field(default=None, ge=0)


class ChargeObservation(ContractModel):
    charge_id: str
    amount_inr: int = Field(ge=0)
    status: Literal["pending", "settled", "failed", "refunded"]


class PaymentObservation(ContractModel):
    order_id: str
    charges: tuple[ChargeObservation, ...]


class InventoryObservation(ContractModel):
    sku: str
    available_units: int = Field(ge=0)


class DamageEvidenceObservation(ContractModel):
    required: bool
    present: bool | None
    valid: bool | None


class CustomerRiskObservation(ContractModel):
    customer_id: str = Field(min_length=1)
    prior_exception_refunds_90d: int = Field(ge=0)
    trusted_records_conflict: bool


class ToolError(ContractModel):
    kind: ToolErrorKind
    message: str = Field(min_length=1)
    persistent: bool = False
