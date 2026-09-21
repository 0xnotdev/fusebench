from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.simulator.environment import SimulatorEnvironment


def test_environment_uses_system_independent_replacement_identifier(
    shipping_case: BenchmarkCase,
) -> None:
    first = SimulatorEnvironment.from_case(shipping_case, seed=42)
    second = SimulatorEnvironment.from_case(shipping_case, seed=42)

    first.record_reship()
    second.record_reship()

    assert first.state.replacement_order_id == second.state.replacement_order_id
    assert first.state.terminal_action is Action.RESHIP


def test_fresh_environments_do_not_share_mutable_state(shipping_case: BenchmarkCase) -> None:
    first = SimulatorEnvironment.from_case(shipping_case, seed=42)
    second = SimulatorEnvironment.from_case(shipping_case, seed=42)

    first.record_refund()

    assert first.state.refund_executed is True
    assert second.state.refund_executed is False
    assert second.state.terminal_action is None
