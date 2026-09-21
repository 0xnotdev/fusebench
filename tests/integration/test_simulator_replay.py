import pytest

from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import ReadTool
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime


@pytest.mark.asyncio
async def test_paired_systems_receive_equivalent_fresh_simulators(
    shipping_case: BenchmarkCase,
) -> None:
    terra_runtime = ToolRuntime(
        SimulatorEnvironment.from_case(shipping_case, seed=20260921),
        "terra_only",
    )
    hybrid_runtime = ToolRuntime(
        SimulatorEnvironment.from_case(shipping_case, seed=20260921),
        "terra_jev",
    )

    terra_tracking = await terra_runtime.call_read(
        ReadTool.GET_TRACKING,
        {"order_id": "ORD-1"},
    )
    hybrid_tracking = await hybrid_runtime.call_read(
        ReadTool.GET_TRACKING,
        {"order_id": "ORD-1"},
    )
    terra_action = await terra_runtime.execute_action("reship_order", {"order_id": "ORD-1"})
    hybrid_action = await hybrid_runtime.execute_action("reship_order", {"order_id": "ORD-1"})

    assert terra_tracking.result == hybrid_tracking.result
    assert terra_action.result == hybrid_action.result
