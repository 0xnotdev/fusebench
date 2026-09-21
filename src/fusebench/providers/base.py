"""Provider-agnostic interfaces consumed by benchmark agents."""

from collections.abc import Mapping
from typing import Any, Protocol

from fusebench.contracts.case import BenchmarkCase
from fusebench.jev.parsing import InformationNeeds, JevDecision


class JevDecisionProvider(Protocol):
    async def infer_information_needs(
        self,
        policy: str,
        case: BenchmarkCase,
    ) -> InformationNeeds: ...

    async def infer_terminal_action(
        self,
        policy: str,
        case: BenchmarkCase,
        observations: Mapping[str, Any],
        observation_errors: Mapping[str, Any],
    ) -> JevDecision: ...


class TerraDecisionProvider(Protocol):
    async def start_case(self, context: Mapping[str, Any]) -> Any: ...

    async def turn(self, session: Any, message: Mapping[str, Any]) -> Mapping[str, Any]: ...
