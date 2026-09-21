"""Bounded Terra + Jev hybrid decision agent."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from time import perf_counter_ns
from typing import Any, Protocol

from typesafe_sdk import TypeSafeAPITimeoutError, TypeSafeError

from fusebench.agents.base import AgentRunOutcome, build_action_call
from fusebench.benchmark.budget import JevBudgetExceeded
from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.decisions import DecisionResult
from fusebench.contracts.tools import ReadTool
from fusebench.jev.parsing import InformationNeeds, JevDecision, JevResponseError
from fusebench.providers.typesafe_jev import ModelVersionChanged
from fusebench.simulator.tool_runtime import ReadCallResult, ToolRuntime

DEFAULT_INFORMATION_THRESHOLD = 0.50

_READ_PLAN: tuple[tuple[str, ReadTool, str], ...] = (
    ("need_tracking", ReadTool.GET_TRACKING, "tracking"),
    ("need_payment", ReadTool.GET_PAYMENT, "payment"),
    ("need_inventory", ReadTool.GET_INVENTORY, "inventory"),
    ("need_damage_evidence", ReadTool.GET_DAMAGE_EVIDENCE, "damage_evidence"),
    ("need_customer_risk", ReadTool.GET_CUSTOMER_RISK, "customer_risk"),
)


class JevDecisionProvider(Protocol):
    """Provider surface required by the hybrid decision agent."""

    model: str
    reported_model: str | None

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


class TerraJevAgent:
    """Use one Jev fan-out and one authoritative Jev action decision per case."""

    def __init__(
        self,
        *,
        provider: JevDecisionProvider,
        policy_text: str,
        information_threshold: float = DEFAULT_INFORMATION_THRESHOLD,
    ) -> None:
        if not 0.0 <= information_threshold <= 1.0:
            raise ValueError("information threshold must be in [0, 1]")
        self.provider = provider
        self.policy_text = policy_text
        self.information_threshold = information_threshold

    async def run(
        self,
        case: BenchmarkCase,
        runtime: ToolRuntime,
        *,
        run_id: str,
        repetition: int,
    ) -> AgentRunOutcome:
        del run_id, repetition
        started = perf_counter_ns()
        observations: dict[str, Any] = {}
        observation_errors: dict[str, Any] = {}
        requested_tools: list[str] = []
        infrastructure_retries = 0
        model_calls = 0
        information: InformationNeeds | None = None
        decisions: list[JevDecision] = []
        precheck_action: Action | None = None
        harness_errors: list[str] = []
        late_risk_unavailable = False

        try:
            model_calls += 1
            information = await self.provider.infer_information_needs(self.policy_text, case)
            selected = [
                (tool, slot)
                for need, tool, slot in _READ_PLAN
                if getattr(information, need) >= self.information_threshold
            ]
            calls = await asyncio.gather(
                *(
                    runtime.call_read(tool, _read_arguments(case, tool))
                    for tool, _slot in selected
                )
            )
            for (tool, slot), call in zip(selected, calls, strict=True):
                requested_tools.append(tool.value)
                infrastructure_retries += call.infrastructure_retries
                _record_read(call, slot, observations, observation_errors)

            model_calls += 1
            decision = await self.provider.infer_terminal_action(
                self.policy_text,
                case,
                observations,
                observation_errors,
            )
            decisions.append(decision)

            risk_was_requested = ReadTool.GET_CUSTOMER_RISK.value in requested_tools
            if decision.action in AUTONOMOUS_ACTIONS and not risk_was_requested:
                precheck_action = decision.action
                risk_call = await runtime.call_read(
                    ReadTool.GET_CUSTOMER_RISK,
                    _read_arguments(case, ReadTool.GET_CUSTOMER_RISK),
                )
                requested_tools.append(ReadTool.GET_CUSTOMER_RISK.value)
                infrastructure_retries += risk_call.infrastructure_retries
                _record_read(
                    risk_call,
                    "customer_risk",
                    observations,
                    observation_errors,
                )
                late_risk_unavailable = risk_call.error is not None
                model_calls += 1
                decision = await self.provider.infer_terminal_action(
                    self.policy_text,
                    case,
                    observations,
                    observation_errors,
                )
                decisions.append(decision)
        except ModelVersionChanged:
            harness_errors.append("model_version_changed")
        except JevBudgetExceeded:
            harness_errors.append("provider_usage_limit")
        except TypeSafeAPITimeoutError:
            harness_errors.append("provider_timeout")
        except JevResponseError:
            harness_errors.append("invalid_terminal_output")
        except ValueError:
            harness_errors.append("invalid_terminal_output")
        except TypeSafeError:
            harness_errors.append("provider_http_error")

        final = decisions[-1] if decisions else None
        decision_result = _finalize_decision(
            final,
            observations=observations,
            observation_errors=observation_errors,
            late_risk_unavailable=late_risk_unavailable,
            harness_errors=harness_errors,
        )
        action_execution = await runtime.execute_action(
            *build_action_call(case, decision_result.executed_action, "JEV_ACTION_CHOICE")
        )
        ended = perf_counter_ns()

        input_tokens = (information.input_tokens if information is not None else 0) + sum(
            decision.input_tokens for decision in decisions
        )
        output_tokens = (information.output_tokens if information is not None else 0) + sum(
            decision.output_tokens for decision in decisions
        )
        latencies = (
            ((information.latency_ms,) if information is not None else ())
            + tuple(decision.latency_ms for decision in decisions)
        )
        return AgentRunOutcome(
            decision=decision_result,
            read_tools_requested=tuple(requested_tools),
            infrastructure_retries=infrastructure_retries,
            model_calls={"jev": model_calls},
            decision_path_latency_ms=(ended - started) / 1_000_000,
            jev_input_tokens=input_tokens,
            jev_output_tokens=output_tokens,
            jev_latencies_ms=latencies,
            jev_information_needs=(
                information.model_dump(mode="json") if information is not None else {}
            ),
            jev_auxiliary=_auxiliary(final),
            precheck_action=precheck_action,
            tool_events=tuple(runtime.tool_events),
            action_result=action_execution.result,
            provider_versions={
                "jev": (
                    final.reported_model
                    if final is not None
                    else information.reported_model
                    if information is not None
                    else getattr(self.provider, "reported_model", None)
                    or getattr(self.provider, "model", "unknown")
                )
            },
        )


def _record_read(
    call: ReadCallResult,
    slot: str,
    observations: dict[str, Any],
    observation_errors: dict[str, Any],
) -> None:
    if call.error is not None:
        observation_errors[slot] = call.error.model_dump(mode="json")
        observations.pop(slot, None)
        return
    assert call.result is not None
    observations[slot] = call.result
    observation_errors.pop(slot, None)


def _finalize_decision(
    decision: JevDecision | None,
    *,
    observations: Mapping[str, Any],
    observation_errors: Mapping[str, Any],
    late_risk_unavailable: bool,
    harness_errors: list[str],
) -> DecisionResult:
    if decision is None:
        return DecisionResult(
            raw_action=None,
            executed_action=Action.ESCALATE,
            reason_code="HARNESS_FAIL_CLOSED",
            errors=tuple(dict.fromkeys(harness_errors or ["invalid_terminal_output"])),
        )

    raw_action = decision.action
    executed_action = raw_action
    errors = list(harness_errors)
    risk = observations.get("customer_risk")
    risk_error = observation_errors.get("customer_risk")
    if late_risk_unavailable:
        executed_action = Action.ESCALATE
        errors.append("customer_risk_unavailable")
    elif raw_action in AUTONOMOUS_ACTIONS:
        if risk_error is not None or risk is None:
            executed_action = Action.ESCALATE
            errors.append("customer_risk_unavailable")
        elif (
            int(risk["prior_exception_refunds_90d"]) >= 2
            or bool(risk["trusted_records_conflict"])
        ):
            executed_action = Action.ESCALATE
            errors.append("customer_risk_override")

    top_probability = max(decision.action_probabilities.values())
    return DecisionResult(
        raw_action=raw_action,
        executed_action=executed_action,
        action_probabilities=decision.action_probabilities,
        top_probability=top_probability,
        reason_code="JEV_ACTION_CHOICE",
        errors=tuple(dict.fromkeys(errors)),
    )


def _read_arguments(case: BenchmarkCase, tool: ReadTool) -> dict[str, str]:
    if tool is ReadTool.GET_INVENTORY:
        return {"sku": case.visible.sku}
    if tool is ReadTool.GET_CUSTOMER_RISK:
        return {"customer_id": case.visible.customer_id}
    return {"order_id": case.visible.order_id}


def _auxiliary(decision: JevDecision | None) -> dict[str, Any]:
    if decision is None:
        return {}
    return {
        "action_confidence": decision.action_confidence,
        "information_sufficient": decision.information_sufficient,
        "requires_human": decision.requires_human,
        "risk_score": decision.risk_score,
        "risk_confidence": decision.risk_confidence,
        "risk_legend": decision.risk_legend,
        "risk_probabilities": decision.risk_probabilities,
    }
