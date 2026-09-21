"""Bounded Terra-only decision agent."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Protocol

from fusebench.agents.base import AgentRunOutcome, build_action_call
from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.decisions import DecisionResult, normalize_action_probabilities
from fusebench.contracts.tools import ReadTool
from fusebench.dataset.validation import canonical_json, serialize_visible_case
from fusebench.providers.codex_app_server import (
    CodexUsageLimitExceeded,
    TerraFinalDecision,
    TerraModelMismatch,
    TerraProviderError,
    TerraSession,
    TerraStructuredOutputError,
    TerraTurnResult,
)
from fusebench.providers.codex_protocol import CodexRequestTimeout
from fusebench.providers.isolation import CaseSandboxManager
from fusebench.simulator.tool_runtime import ToolRuntime, ToolValidationError

MAX_DECISION_TURNS = 6
MAX_READ_TOOL_CALLS = 8
MAX_REPEATED_READ_TOOL_CALLS = 2

_ToolHandler = Callable[[ReadTool, Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


class TerraDecisionProvider(Protocol):
    """Provider surface required by the Terra-only agent."""

    model: str

    async def start_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession: ...

    async def turn(
        self,
        session: TerraSession,
        message: str,
        *,
        tool_handler: _ToolHandler | None = None,
    ) -> TerraTurnResult: ...


class TerraOnlyAgent:
    """Execute one isolated, bounded Terra decision and one terminal action."""

    def __init__(
        self,
        *,
        provider: TerraDecisionProvider,
        policy_text: str,
        sandbox_manager: CaseSandboxManager,
        prompt_path: Path = Path("prompts/terra_agent.md"),
    ) -> None:
        self.provider = provider
        self.policy_text = policy_text
        self.sandbox_manager = sandbox_manager
        self.prompt_path = prompt_path

    async def run(
        self,
        case: BenchmarkCase,
        runtime: ToolRuntime,
        *,
        run_id: str,
        repetition: int,
    ) -> AgentRunOutcome:
        started = perf_counter_ns()
        boundary = self.sandbox_manager.create(
            run_id,
            f"{case.visible.case_id}-r{repetition}",
        )
        developer_instructions = self._developer_instructions()
        payload = canonical_json({"visible_case": serialize_visible_case(case)})

        read_tools_requested: list[str] = []
        request_counts: Counter[str] = Counter()
        infrastructure_retries = 0
        invalid_tool_requests = 0
        loop_limit_exceeded = False
        risk_result: dict[str, Any] | None = None
        risk_unavailable = False

        async def handle_tool(
            tool: ReadTool,
            arguments: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            nonlocal infrastructure_retries
            nonlocal invalid_tool_requests
            nonlocal loop_limit_exceeded
            nonlocal risk_result
            nonlocal risk_unavailable

            read_tools_requested.append(tool.value)
            request_counts[tool.value] += 1
            if (
                len(read_tools_requested) > MAX_READ_TOOL_CALLS
                or request_counts[tool.value] > MAX_REPEATED_READ_TOOL_CALLS
            ):
                loop_limit_exceeded = True
                return {
                    "error": {
                        "kind": "loop_limit",
                        "message": "read tool limit exceeded",
                    }
                }
            try:
                call = await runtime.call_read(tool, arguments)
            except ToolValidationError:
                invalid_tool_requests += 1
                return {"error": {"kind": "invalid", "message": "invalid tool request"}}
            infrastructure_retries += call.infrastructure_retries
            if call.error is not None:
                if tool is ReadTool.GET_CUSTOMER_RISK:
                    risk_unavailable = True
                return {"error": call.error.model_dump(mode="json")}
            assert call.result is not None
            if tool is ReadTool.GET_CUSTOMER_RISK:
                risk_result = call.result
                risk_unavailable = False
            return call.result

        session: TerraSession | None = None
        result: TerraTurnResult | None = None
        errors: list[str] = []
        model_calls = 0
        try:
            session = await self.provider.start_case(
                boundary.case_sandbox,
                developer_instructions,
            )
            model_calls = 1
            result = await self.provider.turn(session, payload, tool_handler=handle_tool)
        except TerraStructuredOutputError:
            errors.append("invalid_terminal_output")
        except CodexRequestTimeout:
            errors.append("provider_timeout")
        except CodexUsageLimitExceeded:
            errors.append("provider_usage_limit")
        except TerraModelMismatch:
            errors.append("model_version_changed")
        except TerraProviderError:
            errors.append("provider_error")

        decision = self._finalize_decision(
            result,
            errors=errors,
            loop_limit_exceeded=loop_limit_exceeded,
            risk_result=risk_result,
            risk_unavailable=risk_unavailable,
            risk_requested=ReadTool.GET_CUSTOMER_RISK.value in read_tools_requested,
        )
        action_execution = await runtime.execute_action(
            *build_action_call(case, decision.executed_action, decision.reason_code)
        )
        ended = perf_counter_ns()

        usage = result.usage if result is not None else None
        return AgentRunOutcome(
            decision=decision,
            thread_id=session.thread_id if session is not None else None,
            turn_id=result.turn_id if result is not None else None,
            read_tools_requested=tuple(read_tools_requested),
            infrastructure_retries=infrastructure_retries,
            model_calls={"terra": model_calls},
            decision_path_latency_ms=(ended - started) / 1_000_000,
            terra_input_tokens=usage.input_tokens if usage is not None else 0,
            terra_cached_input_tokens=usage.cached_input_tokens if usage is not None else 0,
            terra_output_tokens=usage.output_tokens if usage is not None else 0,
            terra_reasoning_output_tokens=(
                usage.reasoning_output_tokens if usage is not None else 0
            ),
            tool_events=tuple(runtime.tool_events),
            provider_events=result.raw_token_events if result is not None else (),
            dynamic_tool_requests=(
                result.dynamic_tool_requests if result is not None else ()
            ),
            loop_limit_exceeded=loop_limit_exceeded,
            invalid_tool_requests=invalid_tool_requests,
            action_result=action_execution.result,
            provider_versions={
                "terra": getattr(self.provider, "model", "unknown"),
                "codex": getattr(self.provider, "codex_user_agent", "unknown"),
            },
        )

    def _developer_instructions(self) -> str:
        prompt = self.prompt_path.read_text(encoding="utf-8").strip()
        return f"{prompt}\n\n# Company policy\n\n{self.policy_text.strip()}"

    @staticmethod
    def _finalize_decision(
        result: TerraTurnResult | None,
        *,
        errors: list[str],
        loop_limit_exceeded: bool,
        risk_result: Mapping[str, Any] | None,
        risk_unavailable: bool,
        risk_requested: bool,
    ) -> DecisionResult:
        if loop_limit_exceeded:
            return _fallback_decision("loop_limit")
        if result is None or not isinstance(result.output, TerraFinalDecision):
            return _fallback_decision(*(errors or ["invalid_terminal_output"]))

        normalized = normalize_action_probabilities(result.output.action_probabilities)
        if normalized.selected_action is None:
            return _fallback_decision(*(errors + list(normalized.errors)))

        raw_action = normalized.selected_action
        executed_action = raw_action
        decision_errors = errors + list(normalized.errors)
        if raw_action in AUTONOMOUS_ACTIONS:
            if not risk_requested:
                executed_action = Action.ESCALATE
                decision_errors.append("missing_customer_risk")
            elif risk_unavailable or risk_result is None:
                executed_action = Action.ESCALATE
                decision_errors.append("customer_risk_unavailable")
            elif (
                int(risk_result["prior_exception_refunds_90d"]) >= 2
                or bool(risk_result["trusted_records_conflict"])
            ):
                executed_action = Action.ESCALATE
                decision_errors.append("customer_risk_override")

        return DecisionResult(
            raw_action=raw_action,
            executed_action=executed_action,
            action_probabilities=normalized.probabilities,
            top_probability=normalized.top_probability,
            reason_code=result.output.reason_code,
            invalid_probability_distribution=not normalized.valid,
            original_probability_sum=normalized.original_sum,
            errors=tuple(dict.fromkeys(decision_errors)),
        )


def _fallback_decision(*errors: str) -> DecisionResult:
    return DecisionResult(
        raw_action=None,
        executed_action=Action.ESCALATE,
        reason_code="HARNESS_FAIL_CLOSED",
        errors=tuple(dict.fromkeys(errors)),
    )
