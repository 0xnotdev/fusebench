"""Shared execution outcome for benchmark decision agents."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.decisions import DecisionResult
from fusebench.contracts.events import ToolEvent
from fusebench.contracts.tools import ActionTool


class AgentRunOutcome(BaseModel):
    """Auditable result of one isolated decision-path execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: DecisionResult
    thread_id: str | None = None
    turn_id: str | None = None
    read_tools_requested: tuple[str, ...] = ()
    infrastructure_retries: int = Field(default=0, ge=0)
    model_calls: dict[str, int] = Field(default_factory=dict)
    decision_path_latency_ms: float = Field(ge=0)
    terra_input_tokens: int = Field(default=0, ge=0)
    terra_cached_input_tokens: int = Field(default=0, ge=0)
    terra_output_tokens: int = Field(default=0, ge=0)
    terra_reasoning_output_tokens: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)
    jev_latencies_ms: tuple[float, ...] = ()
    jev_information_needs: dict[str, Any] = Field(default_factory=dict)
    jev_auxiliary: dict[str, Any] = Field(default_factory=dict)
    jev_request_states: tuple[dict[str, Any], ...] = ()
    jev_responses: tuple[dict[str, Any], ...] = ()
    precheck_action: Action | None = None
    tool_events: tuple[ToolEvent, ...] = ()
    provider_events: tuple[dict[str, Any], ...] = ()
    dynamic_tool_requests: tuple[dict[str, Any], ...] = ()
    loop_limit_exceeded: bool = False
    invalid_tool_requests: int = Field(default=0, ge=0)
    action_result: dict[str, Any]
    provider_versions: dict[str, str] = Field(default_factory=dict)


def build_action_call(
    case: BenchmarkCase,
    action: Action,
    reason_code: str | None,
) -> tuple[ActionTool, dict[str, Any]]:
    """Map one scored action to the corresponding simulator action call."""

    order_id = case.visible.order_id
    if action is Action.REFUND:
        return ActionTool.REFUND_ORDER, {"order_id": order_id}
    if action is Action.RESHIP:
        return ActionTool.RESHIP_ORDER, {"order_id": order_id}
    if action is Action.REQUEST_INFO:
        return ActionTool.REQUEST_INFORMATION, {
            "order_id": order_id,
            "field": _requested_field(reason_code),
        }
    if action is Action.WAIT:
        return ActionTool.WAIT_FOR_CARRIER, {"order_id": order_id}
    return ActionTool.ESCALATE_TO_HUMAN, {
        "order_id": order_id,
        "reason_code": reason_code or "HARNESS_FAIL_CLOSED",
    }


def _requested_field(reason_code: str | None) -> str:
    normalized = (reason_code or "").upper()
    if "DAMAGE" in normalized:
        return "damage_evidence"
    if "PAYMENT" in normalized or "CHARGE" in normalized or "DUPLICATE" in normalized:
        return "payment_evidence"
    return "additional_information"
