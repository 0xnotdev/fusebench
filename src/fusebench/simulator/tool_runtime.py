"""Validated read and action execution over a single simulator environment."""

from collections.abc import Mapping
from time import perf_counter_ns
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from fusebench.contracts.actions import Action
from fusebench.contracts.events import ToolEvent
from fusebench.contracts.tools import (
    ActionTool,
    ChargeObservation,
    CustomerRiskObservation,
    DamageEvidenceObservation,
    EscalateInput,
    GetCustomerRiskInput,
    GetDamageEvidenceInput,
    GetInventoryInput,
    GetPaymentInput,
    GetTrackingInput,
    InventoryObservation,
    PaymentObservation,
    ReadTool,
    RefundInput,
    RequestInformationInput,
    ReshipInput,
    ToolError,
    ToolErrorKind,
    TrackingObservation,
    WaitForCarrierInput,
)
from fusebench.simulator.environment import SimulatorEnvironment


class ToolValidationError(ValueError):
    """A model-requested tool call failed schema or visible-identity validation."""


class TerminalActionAlreadyExecuted(RuntimeError):
    """A second terminal action was attempted in one case environment."""


class ReadCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ReadTool
    result: dict[str, Any] | None
    error: ToolError | None
    events: tuple[ToolEvent, ...]
    infrastructure_retries: int


class ActionExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    result: dict[str, Any]


_READ_INPUTS: dict[ReadTool, type[BaseModel]] = {
    ReadTool.GET_TRACKING: GetTrackingInput,
    ReadTool.GET_PAYMENT: GetPaymentInput,
    ReadTool.GET_INVENTORY: GetInventoryInput,
    ReadTool.GET_DAMAGE_EVIDENCE: GetDamageEvidenceInput,
    ReadTool.GET_CUSTOMER_RISK: GetCustomerRiskInput,
}

_ACTION_INPUTS: dict[ActionTool, type[BaseModel]] = {
    ActionTool.REFUND_ORDER: RefundInput,
    ActionTool.RESHIP_ORDER: ReshipInput,
    ActionTool.REQUEST_INFORMATION: RequestInformationInput,
    ActionTool.WAIT_FOR_CARRIER: WaitForCarrierInput,
    ActionTool.ESCALATE_TO_HUMAN: EscalateInput,
}

_ACTION_BY_TOOL: dict[ActionTool, Action] = {
    ActionTool.REFUND_ORDER: Action.REFUND,
    ActionTool.RESHIP_ORDER: Action.RESHIP,
    ActionTool.REQUEST_INFORMATION: Action.REQUEST_INFO,
    ActionTool.WAIT_FOR_CARRIER: Action.WAIT,
    ActionTool.ESCALATE_TO_HUMAN: Action.ESCALATE,
}


class ToolRuntime:
    """Expose trusted simulator state only through validated tool calls."""

    def __init__(
        self,
        environment: SimulatorEnvironment,
        system: Literal["terra_only", "terra_jev"],
    ) -> None:
        self.environment = environment
        self.system = system
        self.model_read_calls = 0
        self.read_tools_requested: list[str] = []
        self.tool_events: list[ToolEvent] = []

    async def call_read(
        self,
        tool: ReadTool | str,
        arguments: Mapping[str, Any],
    ) -> ReadCallResult:
        self.model_read_calls += 1
        try:
            read_tool = ReadTool(tool)
        except ValueError as error:
            raise ToolValidationError(f"unknown read tool: {tool}") from error
        self.read_tools_requested.append(read_tool.value)
        request = self._validate_input(_READ_INPUTS[read_tool], arguments)
        self._validate_identity(request)

        events: list[ToolEvent] = []
        retry_count = 0
        for attempt in (1, 2):
            started = perf_counter_ns()
            error_kind = self.environment.failures.next_error(read_tool.value)
            if error_kind is None:
                result = self._read_result(read_tool)
                ended = perf_counter_ns()
                event = self._event(
                    read_tool,
                    arguments,
                    started,
                    ended,
                    attempt,
                    attempt > 1,
                    "success",
                    result,
                )
                events.append(event)
                self.tool_events.extend(events)
                return ReadCallResult(
                    tool=read_tool,
                    result=result,
                    error=None,
                    events=tuple(events),
                    infrastructure_retries=retry_count,
                )

            ended = perf_counter_ns()
            persistent = error_kind is not ToolErrorKind.TEMPORARY_ERROR or attempt == 2
            error = ToolError(
                kind=error_kind,
                message=f"{read_tool.value} returned {error_kind.value}",
                persistent=persistent,
            )
            event = self._event(
                read_tool,
                arguments,
                started,
                ended,
                attempt,
                attempt > 1,
                error_kind.value,
                {"error": error.model_dump(mode="json")},
            )
            events.append(event)
            if error_kind is ToolErrorKind.TEMPORARY_ERROR and attempt == 1:
                retry_count = 1
                continue
            self.tool_events.extend(events)
            return ReadCallResult(
                tool=read_tool,
                result=None,
                error=error,
                events=tuple(events),
                infrastructure_retries=retry_count,
            )
        raise AssertionError("read retry loop exhausted unexpectedly")

    async def execute_action(
        self,
        tool: ActionTool | str,
        arguments: Mapping[str, Any],
    ) -> ActionExecutionResult:
        if self.environment.state.terminal_action is not None:
            raise TerminalActionAlreadyExecuted("a terminal action has already executed")
        try:
            action_tool = ActionTool(tool)
        except ValueError as error:
            raise ToolValidationError(f"unknown action tool: {tool}") from error
        request = self._validate_input(_ACTION_INPUTS[action_tool], arguments)
        self._validate_identity(request)

        if action_tool is ActionTool.REFUND_ORDER:
            result = self.environment.record_refund()
        elif action_tool is ActionTool.RESHIP_ORDER:
            result = self.environment.record_reship()
        elif action_tool is ActionTool.REQUEST_INFORMATION:
            result = self.environment.record_request_information(request.field)  # type: ignore[attr-defined]
        elif action_tool is ActionTool.WAIT_FOR_CARRIER:
            result = self.environment.record_wait()
        else:
            result = self.environment.record_escalation(request.reason_code)  # type: ignore[attr-defined]
        return ActionExecutionResult(action=_ACTION_BY_TOOL[action_tool], result=result)

    def _validate_input(
        self,
        model: type[BaseModel],
        arguments: Mapping[str, Any],
    ) -> BaseModel:
        try:
            return model.model_validate(dict(arguments))
        except ValidationError as error:
            raise ToolValidationError(str(error)) from error

    def _validate_identity(self, request: BaseModel) -> None:
        visible = self.environment.case.visible
        if hasattr(request, "order_id") and request.order_id != visible.order_id:  # type: ignore[attr-defined]
            raise ToolValidationError("order_id does not match the visible case")
        if hasattr(request, "sku") and request.sku != visible.sku:  # type: ignore[attr-defined]
            raise ToolValidationError("sku does not match the visible case")
        if hasattr(request, "customer_id") and request.customer_id != visible.customer_id:  # type: ignore[attr-defined]
            raise ToolValidationError("customer_id does not match the visible case")

    def _read_result(self, tool: ReadTool) -> dict[str, Any]:
        case = self.environment.case
        hidden = case.hidden
        visible = case.visible
        if tool is ReadTool.GET_TRACKING:
            return TrackingObservation(
                order_id=visible.order_id,
                carrier_status=hidden.carrier_status,
                days_without_movement=hidden.days_without_carrier_movement,
            ).model_dump(mode="json")
        if tool is ReadTool.GET_PAYMENT:
            return PaymentObservation(
                order_id=visible.order_id,
                charges=tuple(
                    ChargeObservation.model_validate(record.model_dump())
                    for record in hidden.payment_records
                ),
            ).model_dump(mode="json")
        if tool is ReadTool.GET_INVENTORY:
            if hidden.inventory_available is None:
                raise ToolValidationError("inventory fixture is missing without a failure plan")
            return InventoryObservation(
                sku=visible.sku,
                available_units=hidden.inventory_available,
            ).model_dump(mode="json")
        if tool is ReadTool.GET_DAMAGE_EVIDENCE:
            return DamageEvidenceObservation(
                required=hidden.damage_evidence_required,
                present=hidden.damage_evidence_present,
                valid=hidden.damage_evidence_valid,
            ).model_dump(mode="json")
        return CustomerRiskObservation(
            customer_id=visible.customer_id,
            prior_exception_refunds_90d=hidden.prior_exception_refunds_90d,
            trusted_records_conflict=hidden.trusted_records_conflict,
        ).model_dump(mode="json")

    def _event(
        self,
        tool: ReadTool,
        arguments: Mapping[str, Any],
        started: int,
        ended: int,
        attempt: int,
        infrastructure_retry: bool,
        result_kind: str,
        result: dict[str, Any],
    ) -> ToolEvent:
        return ToolEvent(
            case_id=self.environment.case.visible.case_id,
            system=self.system,
            tool=tool.value,
            arguments=dict(arguments),
            started_at_ns=started,
            ended_at_ns=ended,
            duration_ms=(ended - started) / 1_000_000,
            attempt=attempt,
            infrastructure_retry=infrastructure_retry,
            result_kind=result_kind,
            result=result,
        )
