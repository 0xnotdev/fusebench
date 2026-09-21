"""Fixture cloning helpers for paired benchmark execution."""

from fusebench.contracts.case import BenchmarkCase
from fusebench.simulator.environment import SimulatorEnvironment


def fresh_environment(case: BenchmarkCase, seed: int) -> SimulatorEnvironment:
    """Construct a fresh environment from the immutable shared fixture."""

    return SimulatorEnvironment.from_case(case, seed=seed)
