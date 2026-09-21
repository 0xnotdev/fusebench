import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from fusebench.agents.terra_jev import TerraJevAgent
from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.tools import FailurePlan, ReadTool, ToolErrorKind
from fusebench.jev.parsing import InformationNeeds, JevDecision, JevResponseError
from fusebench.providers.typesafe_jev import ModelVersionChanged
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime


def probabilities(action: Action) -> dict[Action, float]:
    return {candidate: 0.96 if candidate is action else 0.01 for candidate in Action}


def information_needs(**overrides: float) -> InformationNeeds:
    values = {
        "need_tracking": 0.0,
        "need_payment": 0.0,
        "need_inventory": 0.0,
        "need_damage_evidence": 0.0,
        "need_customer_risk": 0.0,
    }
    values.update(overrides)
    return InformationNeeds(
        issue_type="shipping",
        issue_probabilities={"shipping": 0.9, "other": 0.1},
        issue_confidence=0.8,
        reported_model="jev-1.13.0",
        input_tokens=100,
        output_tokens=10,
        latency_ms=12.0,
        **values,
    )


def terminal_decision(
    action: Action,
    *,
    information_sufficient: float = 1.0,
    requires_human: float = 0.0,
) -> JevDecision:
    return JevDecision(
        action=action,
        action_probabilities=probabilities(action),
        action_confidence=0.87,
        information_sufficient=information_sufficient,
        requires_human=requires_human,
        risk_score=2.0,
        risk_confidence=0.75,
        risk_legend={1: "low", 2: "moderate", 3: "high", 4: "critical"},
        risk_probabilities={1: 0.1, 2: 0.7, 3: 0.15, 4: 0.05},
        reported_model="jev-1.13.0",
        input_tokens=200,
        output_tokens=20,
        latency_ms=18.0,
    )


class ScriptedJevProvider:
    model = "jev-latest"
    reported_model = "jev-1.13.0"

    def __init__(
        self,
        needs: InformationNeeds,
        decisions: list[JevDecision],
        *,
        information_error: Exception | None = None,
        terminal_error: Exception | None = None,
    ) -> None:
        self.needs = needs
        self.decisions = decisions
        self.information_error = information_error
        self.terminal_error = terminal_error
        self.information_calls = 0
        self.terminal_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def infer_information_needs(
        self,
        policy: str,
        case: BenchmarkCase,
    ) -> InformationNeeds:
        self.information_calls += 1
        if self.information_error is not None:
            raise self.information_error
        return self.needs

    async def infer_terminal_action(
        self,
        policy: str,
        case: BenchmarkCase,
        observations: Mapping[str, Any],
        observation_errors: Mapping[str, Any],
    ) -> JevDecision:
        self.terminal_calls.append((dict(observations), dict(observation_errors)))
        if self.terminal_error is not None:
            raise self.terminal_error
        return self.decisions[len(self.terminal_calls) - 1]


class ConcurrentRuntime(ToolRuntime):
    def __init__(self, case: BenchmarkCase) -> None:
        super().__init__(SimulatorEnvironment.from_case(case, seed=23), "terra_jev")
        self.active_reads = 0
        self.maximum_active_reads = 0

    async def call_read(self, tool, arguments):
        self.active_reads += 1
        self.maximum_active_reads = max(self.maximum_active_reads, self.active_reads)
        try:
            await asyncio.sleep(0)
            return await super().call_read(tool, arguments)
        finally:
            self.active_reads -= 1


def make_runtime(case: BenchmarkCase) -> ToolRuntime:
    return ToolRuntime(SimulatorEnvironment.from_case(case, seed=23), "terra_jev")


@pytest.mark.asyncio
async def test_threshold_selects_reads_concurrently_and_captures_complete_decision(
    shipping_case: BenchmarkCase,
) -> None:
    provider = ScriptedJevProvider(
        information_needs(
            need_tracking=0.50,
            need_payment=0.49,
            need_inventory=0.9,
            need_customer_risk=0.5,
        ),
        [terminal_decision(Action.RESHIP)],
    )
    runtime = ConcurrentRuntime(shipping_case)

    outcome = await TerraJevAgent(
        provider=provider,
        policy_text="Apply policy.",
        information_threshold=0.50,
    ).run(shipping_case, runtime, run_id="threshold", repetition=0)

    assert runtime.maximum_active_reads == 3
    assert outcome.read_tools_requested == (
        "get_tracking",
        "get_inventory",
        "get_customer_risk",
    )
    observations, errors = provider.terminal_calls[0]
    assert set(observations) == {"tracking", "inventory", "customer_risk"}
    assert errors == {}
    assert outcome.decision.raw_action is Action.RESHIP
    assert outcome.decision.executed_action is Action.RESHIP
    assert outcome.decision.action_probabilities == probabilities(Action.RESHIP)
    assert outcome.model_calls == {"jev": 2}
    assert outcome.jev_input_tokens == 300
    assert outcome.jev_output_tokens == 30


@pytest.mark.asyncio
async def test_zero_read_path_proceeds_to_second_jev_call(
    shipping_case: BenchmarkCase,
) -> None:
    provider = ScriptedJevProvider(
        information_needs(),
        [terminal_decision(Action.WAIT)],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        shipping_case,
        make_runtime(shipping_case),
        run_id="zero-read",
        repetition=0,
    )

    assert provider.information_calls == 1
    assert provider.terminal_calls == [({}, {})]
    assert outcome.read_tools_requested == ()
    assert outcome.decision.executed_action is Action.WAIT
    assert outcome.model_calls == {"jev": 2}


@pytest.mark.asyncio
async def test_persistent_read_failure_is_explicit_terminal_state(
    shipping_case: BenchmarkCase,
) -> None:
    failed = shipping_case.model_copy(
        update={
            "hidden": shipping_case.hidden.model_copy(
                update={
                    "tool_failures": {
                        ReadTool.GET_TRACKING.value: FailurePlan(
                            persistent=True,
                            error_kind=ToolErrorKind.UNAVAILABLE,
                        )
                    }
                }
            )
        }
    )
    provider = ScriptedJevProvider(
        information_needs(need_tracking=1.0),
        [terminal_decision(Action.ESCALATE)],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        failed,
        make_runtime(failed),
        run_id="failure",
        repetition=0,
    )

    observations, errors = provider.terminal_calls[0]
    assert observations == {}
    assert errors["tracking"] == {
        "kind": "unavailable",
        "message": "get_tracking returned unavailable",
        "persistent": True,
    }
    assert outcome.decision.executed_action is Action.ESCALATE


@pytest.mark.asyncio
async def test_auxiliary_judgments_never_override_action_choice(
    shipping_case: BenchmarkCase,
) -> None:
    provider = ScriptedJevProvider(
        information_needs(),
        [
            terminal_decision(
                Action.WAIT,
                information_sufficient=0.0,
                requires_human=1.0,
            )
        ],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        shipping_case,
        make_runtime(shipping_case),
        run_id="auxiliary",
        repetition=0,
    )

    assert outcome.decision.executed_action is Action.WAIT
    assert outcome.jev_auxiliary["requires_human"] == 1.0
    assert outcome.jev_auxiliary["information_sufficient"] == 0.0


@pytest.mark.asyncio
async def test_missing_risk_read_triggers_permitted_third_decision_call(
    shipping_case: BenchmarkCase,
) -> None:
    provider = ScriptedJevProvider(
        information_needs(need_customer_risk=0.49),
        [terminal_decision(Action.RESHIP), terminal_decision(Action.RESHIP)],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        shipping_case,
        make_runtime(shipping_case),
        run_id="third-call",
        repetition=0,
    )

    assert len(provider.terminal_calls) == 2
    assert "customer_risk" in provider.terminal_calls[1][0]
    assert outcome.precheck_action is Action.RESHIP
    assert outcome.read_tools_requested == ("get_customer_risk",)
    assert outcome.model_calls == {"jev": 3}
    assert outcome.decision.executed_action is Action.RESHIP


@pytest.mark.asyncio
async def test_persistent_late_risk_failure_forces_final_escalation(
    shipping_case: BenchmarkCase,
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
    provider = ScriptedJevProvider(
        information_needs(),
        [terminal_decision(Action.RESHIP), terminal_decision(Action.REFUND)],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        failed,
        make_runtime(failed),
        run_id="late-risk-failure",
        repetition=0,
    )

    assert provider.terminal_calls[1][1]["customer_risk"]["persistent"] is True
    assert outcome.precheck_action is Action.RESHIP
    assert outcome.decision.raw_action is Action.REFUND
    assert outcome.decision.executed_action is Action.ESCALATE
    assert "customer_risk_unavailable" in outcome.decision.errors
    assert outcome.model_calls == {"jev": 3}


@pytest.mark.asyncio
async def test_unsafe_risk_observation_overrides_autonomous_choice(
    shipping_case: BenchmarkCase,
) -> None:
    risky = shipping_case.model_copy(
        update={
            "hidden": shipping_case.hidden.model_copy(
                update={"trusted_records_conflict": True}
            )
        }
    )
    provider = ScriptedJevProvider(
        information_needs(need_customer_risk=1.0),
        [terminal_decision(Action.REFUND)],
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        risky,
        make_runtime(risky),
        run_id="risk-override",
        repetition=0,
    )

    assert outcome.decision.raw_action is Action.REFUND
    assert outcome.decision.executed_action is Action.ESCALATE
    assert "customer_risk_override" in outcome.decision.errors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ModelVersionChanged("changed"), "model_version_changed"),
        (JevResponseError("invalid"), "invalid_terminal_output"),
    ],
)
async def test_provider_failures_fail_closed(
    error: Exception,
    expected: str,
    shipping_case: BenchmarkCase,
) -> None:
    provider = ScriptedJevProvider(
        information_needs(),
        [terminal_decision(Action.WAIT)],
        information_error=error,
    )

    outcome = await TerraJevAgent(provider=provider, policy_text="Policy.").run(
        shipping_case,
        make_runtime(shipping_case),
        run_id="provider-error",
        repetition=0,
    )

    assert outcome.decision.raw_action is None
    assert outcome.decision.executed_action is Action.ESCALATE
    assert expected in outcome.decision.errors
    assert outcome.model_calls == {"jev": 1}


def test_information_threshold_must_be_probability() -> None:
    with pytest.raises(ValueError, match="threshold"):
        TerraJevAgent(
            provider=ScriptedJevProvider(
                information_needs(),
                [terminal_decision(Action.WAIT)],
            ),
            policy_text="Policy.",
            information_threshold=1.01,
        )
