import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fusebench.agents.terra_only import TerraOnlyAgent
from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import FailurePlan, ReadTool, ToolErrorKind
from fusebench.providers.codex_app_server import (
    CodexUsageLimitExceeded,
    TerraFinalDecision,
    TerraModelMismatch,
    TerraSession,
    TerraStructuredOutputError,
    TerraTurnResult,
    TerraUsage,
)
from fusebench.providers.codex_protocol import CodexRequestTimeout
from fusebench.providers.isolation import CaseSandboxManager
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime


def probabilities(action: Action, *, top: float = 0.96, other: float = 0.01) -> dict:
    return {candidate: top if candidate is action else other for candidate in Action}


class ScriptedTerraProvider:
    model = "gpt-5.6-terra"
    effort = "medium"
    codex_user_agent = "codex-test/1"

    def __init__(
        self,
        action: Action,
        *,
        tool_calls: list[tuple[ReadTool, dict[str, Any]]] | None = None,
        raw_probabilities: dict[Action, float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.action = action
        self.tool_calls = tool_calls or []
        self.raw_probabilities = raw_probabilities or probabilities(action)
        self.error = error
        self.started: list[tuple[Path, str]] = []
        self.messages: list[str] = []
        self.observations: list[Mapping[str, Any]] = []

    async def start_case(self, case_sandbox: Path, developer_instructions: str) -> TerraSession:
        self.started.append((case_sandbox, developer_instructions))
        return TerraSession(
            thread_id="thread-1",
            session_id="thread-1",
            case_sandbox=case_sandbox,
            effective_sandbox={"type": "readOnly", "networkAccess": False},
            runtime_workspace_roots=(case_sandbox,),
        )

    async def turn(self, session, message, *, tool_handler=None) -> TerraTurnResult:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        assert tool_handler is not None
        dynamic_requests = []
        for tool, arguments in self.tool_calls:
            self.observations.append(await tool_handler(tool, arguments))
            dynamic_requests.append(
                {"call_id": f"call-{len(dynamic_requests) + 1}", "tool": tool.value}
            )
        output = TerraFinalDecision(
            kind="final",
            action_probabilities=self.raw_probabilities,
            reason_code=f"TEST_{self.action.value}",
        )
        return TerraTurnResult(
            thread_id=session.thread_id,
            turn_id="turn-1",
            output=output,
            raw_text=output.model_dump_json(),
            usage=TerraUsage(
                input_tokens=100,
                cached_input_tokens=10,
                output_tokens=20,
                reasoning_output_tokens=5,
            ),
            raw_token_events=({"method": "thread/tokenUsage/updated"},),
            dynamic_tool_requests=tuple(dynamic_requests),
        )

    async def close(self) -> None:
        return None


def make_agent(
    provider: ScriptedTerraProvider,
    tmp_path: Path,
) -> TerraOnlyAgent:
    return TerraOnlyAgent(
        provider=provider,
        policy_text="Apply the company policy exactly.",
        sandbox_manager=CaseSandboxManager(tmp_path / "artifacts" / "case_sandboxes"),
    )


def make_runtime(case: BenchmarkCase) -> ToolRuntime:
    return ToolRuntime(SimulatorEnvironment.from_case(case, seed=17), "terra_only")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(Action))
async def test_executes_each_terminal_action_and_preserves_visible_only_payload(
    action: Action,
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    calls = []
    if action in {Action.REFUND, Action.RESHIP}:
        calls.append(
            (
                ReadTool.GET_CUSTOMER_RISK,
                {"customer_id": shipping_case.visible.customer_id},
            )
        )
    provider = ScriptedTerraProvider(action, tool_calls=calls)
    runtime = make_runtime(shipping_case)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case,
        runtime,
        run_id="unit",
        repetition=0,
    )

    assert outcome.decision.raw_action is action
    assert outcome.decision.executed_action is action
    assert runtime.environment.state.terminal_action is action
    payload = json.loads(provider.messages[0])
    assert payload == {"visible_case": shipping_case.visible.model_dump(mode="json")}
    assert "gold" not in provider.messages[0].lower()
    assert "hidden" not in provider.messages[0].lower()


@pytest.mark.asyncio
async def test_missing_customer_risk_overrides_autonomous_action_to_escalate(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    provider = ScriptedTerraProvider(Action.RESHIP)
    runtime = make_runtime(shipping_case)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case, runtime, run_id="missing-risk", repetition=0
    )

    assert outcome.decision.raw_action is Action.RESHIP
    assert outcome.decision.executed_action is Action.ESCALATE
    assert "missing_customer_risk" in outcome.decision.errors


@pytest.mark.asyncio
async def test_unsafe_customer_risk_overrides_autonomous_action_to_escalate(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    risky = shipping_case.model_copy(
        update={
            "hidden": shipping_case.hidden.model_copy(
                update={"prior_exception_refunds_90d": 2}
            )
        }
    )
    provider = ScriptedTerraProvider(
        Action.RESHIP,
        tool_calls=[
            (ReadTool.GET_CUSTOMER_RISK, {"customer_id": risky.visible.customer_id})
        ],
    )

    outcome = await make_agent(provider, tmp_path).run(
        risky, make_runtime(risky), run_id="unsafe-risk", repetition=0
    )

    assert outcome.decision.raw_action is Action.RESHIP
    assert outcome.decision.executed_action is Action.ESCALATE
    assert "customer_risk_override" in outcome.decision.errors


@pytest.mark.asyncio
async def test_persistent_risk_failure_fails_closed(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    failed = shipping_case.model_copy(
        update={
            "hidden": shipping_case.hidden.model_copy(
                update={
                    "tool_failures": {
                        ReadTool.GET_CUSTOMER_RISK.value: FailurePlan(
                            persistent=True,
                            error_kind=ToolErrorKind.UNAVAILABLE,
                        )
                    }
                }
            )
        }
    )
    provider = ScriptedTerraProvider(
        Action.RESHIP,
        tool_calls=[
            (ReadTool.GET_CUSTOMER_RISK, {"customer_id": failed.visible.customer_id})
        ],
    )

    outcome = await make_agent(provider, tmp_path).run(
        failed, make_runtime(failed), run_id="risk-failure", repetition=0
    )

    assert outcome.decision.executed_action is Action.ESCALATE
    assert outcome.infrastructure_retries == 0
    assert "customer_risk_unavailable" in outcome.decision.errors


@pytest.mark.asyncio
async def test_invalid_tool_arguments_are_returned_to_model_without_hidden_data(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    provider = ScriptedTerraProvider(
        Action.WAIT,
        tool_calls=[(ReadTool.GET_TRACKING, {"order_id": "wrong-order"})],
    )

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case,
        make_runtime(shipping_case),
        run_id="invalid-tool",
        repetition=0,
    )

    assert outcome.invalid_tool_requests == 1
    assert provider.observations == [
        {"error": {"kind": "invalid", "message": "invalid tool request"}}
    ]
    assert outcome.decision.executed_action is Action.WAIT


@pytest.mark.asyncio
async def test_third_request_of_same_read_tool_triggers_loop_fallback(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    calls = [
        (ReadTool.GET_TRACKING, {"order_id": shipping_case.visible.order_id})
        for _ in range(3)
    ]
    provider = ScriptedTerraProvider(Action.WAIT, tool_calls=calls)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case, make_runtime(shipping_case), run_id="repeat-limit", repetition=0
    )

    assert outcome.loop_limit_exceeded is True
    assert outcome.decision.raw_action is None
    assert outcome.decision.executed_action is Action.ESCALATE
    assert outcome.read_tools_requested == (
        "get_tracking",
        "get_tracking",
        "get_tracking",
    )


@pytest.mark.asyncio
async def test_ninth_read_request_triggers_loop_fallback(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    order_id = shipping_case.visible.order_id
    calls = [
        (ReadTool.GET_TRACKING, {"order_id": order_id}),
        (ReadTool.GET_PAYMENT, {"order_id": order_id}),
        (ReadTool.GET_INVENTORY, {"sku": shipping_case.visible.sku}),
        (ReadTool.GET_DAMAGE_EVIDENCE, {"order_id": order_id}),
    ] * 2 + [
        (
            ReadTool.GET_CUSTOMER_RISK,
            {"customer_id": shipping_case.visible.customer_id},
        )
    ]
    provider = ScriptedTerraProvider(Action.WAIT, tool_calls=calls)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case, make_runtime(shipping_case), run_id="read-limit", repetition=0
    )

    assert outcome.loop_limit_exceeded is True
    assert outcome.decision.raw_action is None
    assert outcome.decision.executed_action is Action.ESCALATE
    assert len(outcome.read_tools_requested) == 9


@pytest.mark.asyncio
async def test_out_of_tolerance_distribution_is_normalized_but_still_executed(
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    raw = probabilities(Action.WAIT, top=0.46, other=0.01)
    provider = ScriptedTerraProvider(Action.WAIT, raw_probabilities=raw)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case, make_runtime(shipping_case), run_id="normalization", repetition=0
    )

    assert outcome.decision.raw_action is Action.WAIT
    assert outcome.decision.executed_action is Action.WAIT
    assert outcome.decision.invalid_probability_distribution is True
    assert outcome.decision.original_probability_sum == pytest.approx(0.5)
    assert sum(outcome.decision.action_probabilities.values()) == pytest.approx(1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (TerraStructuredOutputError("bad output"), "invalid_terminal_output"),
        (CodexRequestTimeout("timeout"), "provider_timeout"),
    ],
)
async def test_provider_failures_execute_escalation_without_raw_action(
    error: Exception,
    expected_error: str,
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    provider = ScriptedTerraProvider(Action.WAIT, error=error)

    outcome = await make_agent(provider, tmp_path).run(
        shipping_case, make_runtime(shipping_case), run_id="provider-failure", repetition=0
    )

    assert outcome.decision.raw_action is None
    assert outcome.decision.executed_action is Action.ESCALATE
    assert expected_error in outcome.decision.errors
    assert outcome.model_calls == {"terra": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [CodexUsageLimitExceeded("limit"), TerraModelMismatch("changed")],
)
async def test_run_abort_errors_propagate_without_executing_an_action(
    error: Exception,
    shipping_case: BenchmarkCase,
    tmp_path: Path,
) -> None:
    provider = ScriptedTerraProvider(Action.WAIT, error=error)
    runtime = make_runtime(shipping_case)

    with pytest.raises(type(error)):
        await make_agent(provider, tmp_path).run(
            shipping_case, runtime, run_id="abort", repetition=0
        )

    assert runtime.environment.state.terminal_action is None
