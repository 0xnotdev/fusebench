import pytest

from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import FailurePlan, ReadTool, ToolErrorKind
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import (
    TerminalActionAlreadyExecuted,
    ToolRuntime,
    ToolValidationError,
)


@pytest.mark.asyncio
async def test_tracking_read_maps_only_tracking_hidden_state(
    shipping_case: BenchmarkCase,
) -> None:
    runtime = ToolRuntime(SimulatorEnvironment.from_case(shipping_case, seed=1), "terra_only")

    call = await runtime.call_read(ReadTool.GET_TRACKING, {"order_id": "ORD-1"})

    assert call.result == {
        "order_id": "ORD-1",
        "carrier_status": "in_transit",
        "days_without_movement": 7,
    }
    assert "prior_exception_refunds_90d" not in call.result
    assert "trusted_records_conflict" not in call.result


@pytest.mark.asyncio
async def test_customer_risk_is_the_only_risk_read_surface(
    shipping_case: BenchmarkCase,
) -> None:
    runtime = ToolRuntime(SimulatorEnvironment.from_case(shipping_case, seed=1), "terra_jev")

    call = await runtime.call_read(
        ReadTool.GET_CUSTOMER_RISK,
        {"customer_id": "CUS-1"},
    )

    assert call.result == {
        "customer_id": "CUS-1",
        "prior_exception_refunds_90d": 1,
        "trusted_records_conflict": False,
    }


@pytest.mark.asyncio
async def test_read_rejects_identity_not_present_in_visible_case(
    shipping_case: BenchmarkCase,
) -> None:
    runtime = ToolRuntime(SimulatorEnvironment.from_case(shipping_case, seed=1), "terra_only")

    with pytest.raises(ToolValidationError, match="order_id"):
        await runtime.call_read(ReadTool.GET_TRACKING, {"order_id": "ORD-OTHER"})


@pytest.mark.asyncio
async def test_temporary_error_gets_exactly_one_infrastructure_retry(
    shipping_case: BenchmarkCase,
) -> None:
    hidden = shipping_case.hidden.model_copy(
        update={
            "tool_failures": {
                "get_tracking": FailurePlan(
                    fail_first_n=1,
                    error_kind=ToolErrorKind.TEMPORARY_ERROR,
                )
            }
        }
    )
    case = shipping_case.model_copy(update={"hidden": hidden})
    runtime = ToolRuntime(SimulatorEnvironment.from_case(case, seed=1), "terra_only")

    call = await runtime.call_read(ReadTool.GET_TRACKING, {"order_id": "ORD-1"})

    assert call.error is None
    assert call.infrastructure_retries == 1
    assert [event.result_kind for event in call.events] == ["temporary_error", "success"]
    assert [event.infrastructure_retry for event in call.events] == [False, True]
    assert runtime.model_read_calls == 1


@pytest.mark.asyncio
async def test_persistent_error_is_returned_as_explicit_observation(
    shipping_case: BenchmarkCase,
) -> None:
    hidden = shipping_case.hidden.model_copy(
        update={
            "tool_failures": {
                "get_customer_risk": FailurePlan(
                    persistent=True,
                    error_kind=ToolErrorKind.UNAVAILABLE,
                )
            }
        }
    )
    case = shipping_case.model_copy(update={"hidden": hidden})
    runtime = ToolRuntime(SimulatorEnvironment.from_case(case, seed=1), "terra_jev")

    call = await runtime.call_read(
        ReadTool.GET_CUSTOMER_RISK,
        {"customer_id": "CUS-1"},
    )

    assert call.result is None
    assert call.error is not None
    assert call.error.kind is ToolErrorKind.UNAVAILABLE
    assert call.error.persistent is True
    assert call.infrastructure_retries == 0


@pytest.mark.asyncio
async def test_successful_reads_are_semantically_idempotent(
    shipping_case: BenchmarkCase,
) -> None:
    runtime = ToolRuntime(SimulatorEnvironment.from_case(shipping_case, seed=1), "terra_only")

    first = await runtime.call_read(ReadTool.GET_INVENTORY, {"sku": "SKU-1"})
    second = await runtime.call_read(ReadTool.GET_INVENTORY, {"sku": "SKU-1"})

    assert first.result == second.result == {"sku": "SKU-1", "available_units": 3}


@pytest.mark.asyncio
async def test_wrong_business_action_still_executes_without_oracle_enforcement(
    shipping_case: BenchmarkCase,
) -> None:
    environment = SimulatorEnvironment.from_case(shipping_case, seed=1)
    runtime = ToolRuntime(environment, "terra_only")

    result = await runtime.execute_action("refund_order", {"order_id": "ORD-1"})

    assert result.action is Action.REFUND
    assert environment.state.refund_executed is True
    assert environment.state.terminal_action is Action.REFUND


@pytest.mark.asyncio
async def test_second_terminal_action_is_rejected(shipping_case: BenchmarkCase) -> None:
    runtime = ToolRuntime(SimulatorEnvironment.from_case(shipping_case, seed=1), "terra_only")
    await runtime.execute_action("wait_for_carrier", {"order_id": "ORD-1"})

    with pytest.raises(TerminalActionAlreadyExecuted):
        await runtime.execute_action(
            "escalate_to_human",
            {"order_id": "ORD-1", "reason_code": "MANUAL_REVIEW"},
        )
