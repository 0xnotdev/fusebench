"""Provider-agnostic interfaces consumed by benchmark agents."""

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import ReadTool
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
    async def start_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> Any: ...

    async def turn(
        self,
        session: Any,
        message: str,
        *,
        tool_handler: Callable[
            [ReadTool, dict[str, Any]], Awaitable[Mapping[str, Any]]
        ]
        | None = None,
    ) -> Any: ...

    async def close(self) -> None: ...
