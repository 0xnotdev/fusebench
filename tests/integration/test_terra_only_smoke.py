import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fusebench.agents.terra_only import TerraOnlyAgent
from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import ReadTool
from fusebench.dataset.validation import load_cases_jsonl
from fusebench.providers.codex_app_server import (
    TerraFinalDecision,
    TerraSession,
    TerraTurnResult,
    TerraUsage,
)
from fusebench.providers.isolation import CaseSandboxManager
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime


class ShippingTerra:
    model = "gpt-5.6-terra"
    codex_user_agent = "codex-smoke/1"

    async def start_case(self, case_sandbox: Path, developer_instructions: str) -> TerraSession:
        return TerraSession(
            thread_id="thread-smoke",
            session_id="thread-smoke",
            case_sandbox=case_sandbox,
            effective_sandbox={"type": "readOnly", "networkAccess": False},
            runtime_workspace_roots=(case_sandbox,),
        )

    async def turn(self, session, message, *, tool_handler=None) -> TerraTurnResult:
        assert tool_handler is not None
        observations: list[Mapping[str, Any]] = []
        observations.append(
            await tool_handler(ReadTool.GET_TRACKING, {"order_id": "ORD-1"})
        )
        observations.append(
            await tool_handler(ReadTool.GET_INVENTORY, {"sku": "SKU-1"})
        )
        observations.append(
            await tool_handler(ReadTool.GET_CUSTOMER_RISK, {"customer_id": "CUS-1"})
        )
        assert observations[0]["days_without_movement"] == 7
        assert observations[1]["available_units"] == 3
        assert observations[2]["prior_exception_refunds_90d"] == 1
        output = TerraFinalDecision(
            kind="final",
            action_probabilities={
                Action.REFUND: 0.01,
                Action.RESHIP: 0.94,
                Action.REQUEST_INFO: 0.01,
                Action.WAIT: 0.02,
                Action.ESCALATE: 0.02,
            },
            reason_code="SHIPPING_STALLED_STOCK_AVAILABLE",
        )
        return TerraTurnResult(
            thread_id=session.thread_id,
            turn_id="turn-smoke",
            output=output,
            raw_text=output.model_dump_json(),
            usage=TerraUsage(
                input_tokens=500,
                cached_input_tokens=0,
                output_tokens=50,
                reasoning_output_tokens=10,
            ),
            raw_token_events=(),
            dynamic_tool_requests=(),
        )

    async def close(self) -> None:
        return None


class DevScenarioTerra:
    model = "gpt-5.6-terra"
    codex_user_agent = "codex-smoke/1"

    def __init__(self, action: Action, tools: tuple[ReadTool, ...]) -> None:
        self.action = action
        self.tools = tools
        self.observations: list[Mapping[str, Any]] = []

    async def start_case(self, case_sandbox: Path, developer_instructions: str) -> TerraSession:
        return TerraSession(
            thread_id="thread-dev-smoke",
            session_id="thread-dev-smoke",
            case_sandbox=case_sandbox,
            effective_sandbox={"type": "readOnly", "networkAccess": False},
            runtime_workspace_roots=(case_sandbox,),
        )

    async def turn(self, session, message, *, tool_handler=None) -> TerraTurnResult:
        assert tool_handler is not None
        visible = json.loads(message)["visible_case"]
        for tool in self.tools:
            field = "customer_id" if tool is ReadTool.GET_CUSTOMER_RISK else "order_id"
            if tool is ReadTool.GET_INVENTORY:
                field = "sku"
            self.observations.append(await tool_handler(tool, {field: visible[field]}))
        output = TerraFinalDecision(
            kind="final",
            action_probabilities={
                candidate: 0.96 if candidate is self.action else 0.01
                for candidate in Action
            },
            reason_code=f"SMOKE_{self.action.value}",
        )
        return TerraTurnResult(
            thread_id=session.thread_id,
            turn_id="turn-dev-smoke",
            output=output,
            raw_text=output.model_dump_json(),
            usage=TerraUsage(
                input_tokens=100,
                cached_input_tokens=0,
                output_tokens=20,
                reasoning_output_tokens=5,
            ),
            raw_token_events=(),
            dynamic_tool_requests=(),
        )


@pytest.mark.asyncio
async def test_terra_only_shipping_case_completes_end_to_end(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    runtime = ToolRuntime(
        SimulatorEnvironment.from_case(shipping_case, seed=20260921),
        "terra_only",
    )
    agent = TerraOnlyAgent(
        provider=ShippingTerra(),
        policy_text="Apply global safety, then the shipping rules.",
        sandbox_manager=CaseSandboxManager(tmp_path / "artifacts" / "case_sandboxes"),
    )

    outcome = await agent.run(
        shipping_case,
        runtime,
        run_id="smoke",
        repetition=0,
    )

    assert outcome.decision.raw_action is Action.RESHIP
    assert outcome.decision.executed_action is Action.RESHIP
    assert runtime.environment.state.reship_executed is True
    assert outcome.read_tools_requested == (
        "get_tracking",
        "get_inventory",
        "get_customer_risk",
    )
    assert outcome.model_calls == {"terra": 1}
    assert outcome.terra_input_tokens == 500


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "action", "tools"),
    [
        (
            "DEV_0057",
            Action.REFUND,
            (ReadTool.GET_PAYMENT, ReadTool.GET_CUSTOMER_RISK),
        ),
        ("DEV_0005", Action.REQUEST_INFO, (ReadTool.GET_DAMAGE_EVIDENCE,)),
        ("DEV_0019", Action.WAIT, (ReadTool.GET_TRACKING,)),
        ("DEV_0056", Action.ESCALATE, ()),
        ("DEV_0027", Action.ESCALATE, (ReadTool.GET_TRACKING,)),
        (
            "DEV_0001",
            Action.RESHIP,
            (
                ReadTool.GET_DAMAGE_EVIDENCE,
                ReadTool.GET_INVENTORY,
                ReadTool.GET_CUSTOMER_RISK,
            ),
        ),
    ],
    ids=[
        "duplicate-refund",
        "request-info",
        "wait",
        "escalate",
        "persistent-tool-failure",
        "adversarial-message",
    ],
)
async def test_terra_only_required_dev_scenarios_complete_end_to_end(
    case_id: str,
    action: Action,
    tools: tuple[ReadTool, ...],
    tmp_path: Path,
) -> None:
    cases = {case.visible.case_id: case for case in load_cases_jsonl(Path("data/dev/cases.jsonl"))}
    case = cases[case_id]
    provider = DevScenarioTerra(action, tools)
    runtime = ToolRuntime(SimulatorEnvironment.from_case(case, seed=20260921), "terra_only")
    agent = TerraOnlyAgent(
        provider=provider,
        policy_text="Apply the frozen order-exception policy.",
        sandbox_manager=CaseSandboxManager(tmp_path / "artifacts" / "case_sandboxes"),
    )

    outcome = await agent.run(case, runtime, run_id="dev-smoke", repetition=0)

    assert outcome.decision.executed_action is action
    assert runtime.environment.state.terminal_action is action
    assert outcome.read_tools_requested == tuple(tool.value for tool in tools)
    if case_id == "DEV_0027":
        assert provider.observations[0]["error"]["persistent"] is True
