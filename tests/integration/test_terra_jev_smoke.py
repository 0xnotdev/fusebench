from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fusebench.agents.terra_jev import TerraJevAgent
from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import ReadTool
from fusebench.dataset.validation import load_cases_jsonl
from fusebench.jev.parsing import InformationNeeds, JevDecision
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime

_NEED_BY_TOOL = {
    ReadTool.GET_TRACKING: "need_tracking",
    ReadTool.GET_PAYMENT: "need_payment",
    ReadTool.GET_INVENTORY: "need_inventory",
    ReadTool.GET_DAMAGE_EVIDENCE: "need_damage_evidence",
    ReadTool.GET_CUSTOMER_RISK: "need_customer_risk",
}


class SmokeJevProvider:
    model = "jev-latest"
    reported_model = "jev-1.13.0"

    def __init__(self, action: Action, tools: tuple[ReadTool, ...]) -> None:
        self.action = action
        self.tools = tools
        self.terminal_states: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def infer_information_needs(
        self,
        policy: str,
        case: BenchmarkCase,
    ) -> InformationNeeds:
        needs = {name: 0.0 for name in _NEED_BY_TOOL.values()}
        needs.update({_NEED_BY_TOOL[tool]: 1.0 for tool in self.tools})
        return InformationNeeds(
            issue_type="other",
            issue_probabilities={"other": 1.0},
            issue_confidence=1.0,
            reported_model=self.reported_model,
            input_tokens=100,
            output_tokens=10,
            latency_ms=1.0,
            **needs,
        )

    async def infer_terminal_action(
        self,
        policy: str,
        case: BenchmarkCase,
        observations: Mapping[str, Any],
        observation_errors: Mapping[str, Any],
    ) -> JevDecision:
        self.terminal_states.append((dict(observations), dict(observation_errors)))
        probabilities = {
            candidate: 0.96 if candidate is self.action else 0.01
            for candidate in Action
        }
        return JevDecision(
            action=self.action,
            action_probabilities=probabilities,
            action_confidence=0.9,
            information_sufficient=1.0,
            requires_human=1.0 if self.action is Action.ESCALATE else 0.0,
            risk_score=2.0,
            risk_confidence=0.8,
            risk_legend={1: "low", 2: "moderate", 3: "high", 4: "critical"},
            risk_probabilities={1: 0.1, 2: 0.7, 3: 0.1, 4: 0.1},
            reported_model=self.reported_model,
            input_tokens=200,
            output_tokens=20,
            latency_ms=1.0,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "action", "tools"),
    [
        (
            "DEV_0020",
            Action.RESHIP,
            (
                ReadTool.GET_TRACKING,
                ReadTool.GET_INVENTORY,
                ReadTool.GET_CUSTOMER_RISK,
            ),
        ),
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
                ReadTool.GET_INVENTORY,
                ReadTool.GET_DAMAGE_EVIDENCE,
                ReadTool.GET_CUSTOMER_RISK,
            ),
        ),
    ],
    ids=[
        "shipping-reship",
        "duplicate-refund",
        "request-info",
        "wait",
        "escalate",
        "persistent-tool-failure",
        "adversarial-message",
    ],
)
async def test_hybrid_required_dev_scenarios_complete_end_to_end(
    case_id: str,
    action: Action,
    tools: tuple[ReadTool, ...],
) -> None:
    cases = {case.visible.case_id: case for case in load_cases_jsonl(Path("data/dev/cases.jsonl"))}
    case = cases[case_id]
    provider = SmokeJevProvider(action, tools)
    runtime = ToolRuntime(SimulatorEnvironment.from_case(case, seed=20260921), "terra_jev")

    outcome = await TerraJevAgent(provider=provider, policy_text="Apply policy.").run(
        case,
        runtime,
        run_id="hybrid-smoke",
        repetition=0,
    )

    assert outcome.decision.executed_action is action
    assert runtime.environment.state.terminal_action is action
    assert outcome.read_tools_requested == tuple(tool.value for tool in tools)
    assert outcome.model_calls == {"jev": 2}
    if case_id == "DEV_0027":
        assert provider.terminal_states[0][1]["tracking"]["persistent"] is True
