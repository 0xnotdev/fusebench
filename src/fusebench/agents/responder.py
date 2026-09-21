"""Shared post-action Terra customer-response stage."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter_ns
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from fusebench.agents.base import AgentRunOutcome
from fusebench.dataset.validation import assert_no_forbidden_keys, canonical_json
from fusebench.providers.codex_app_server import (
    CodexUsageLimitExceeded,
    TerraModelMismatch,
    TerraProviderError,
    TerraResponseResult,
    TerraSession,
    TerraStructuredOutputError,
)
from fusebench.providers.codex_protocol import CodexRequestTimeout
from fusebench.providers.isolation import CaseSandboxManager


class TerraResponseProvider(Protocol):
    model: str

    async def start_response_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession: ...

    async def response_turn(
        self,
        session: TerraSession,
        message: str,
    ) -> TerraResponseResult: ...


class ResponseStageResult(BaseModel):
    """Unscored response telemetry with deliberately no action field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_response: str | None = None
    response_stage_latency_ms: float = Field(ge=0)
    full_response_latency_ms: float = Field(ge=0)
    response_error: str | None = None
    response_model_calls: int = Field(default=0, ge=0)
    response_input_tokens: int = Field(default=0, ge=0)
    response_cached_input_tokens: int = Field(default=0, ge=0)
    response_output_tokens: int = Field(default=0, ge=0)
    response_reasoning_output_tokens: int = Field(default=0, ge=0)
    thread_id: str | None = None
    turn_id: str | None = None
    provider_events: tuple[dict[str, Any], ...] = ()
    provider_versions: dict[str, str] = Field(default_factory=dict)


class SharedTerraResponder:
    """Generate identical post-action Terra responses for both benchmark systems."""

    def __init__(
        self,
        *,
        provider: TerraResponseProvider,
        sandbox_manager: CaseSandboxManager,
        prompt_path: Path = Path("prompts/terra_response.md"),
    ) -> None:
        self.provider = provider
        self.sandbox_manager = sandbox_manager
        self.prompt_path = prompt_path

    async def respond_for_outcome(
        self,
        outcome: AgentRunOutcome,
        *,
        customer_message: str,
        case_id: str,
        run_id: str,
        repetition: int,
    ) -> ResponseStageResult:
        """Use only the locked action/result while leaving the decision object untouched."""

        payload = {
            "customer_message": customer_message,
            "executed_action": outcome.decision.executed_action.value,
            "action_result": dict(outcome.action_result),
        }
        assert_no_forbidden_keys(payload)
        message = canonical_json(payload)
        boundary = self.sandbox_manager.create_fresh(
            run_id,
            f"{case_id}-r{repetition}-response",
        )
        instructions = self.prompt_path.read_text(encoding="utf-8").strip()
        started = perf_counter_ns()
        session: TerraSession | None = None
        result: TerraResponseResult | None = None
        error: str | None = None
        model_calls = 0
        structured_failure: TerraStructuredOutputError | None = None
        try:
            session = await self.provider.start_response_case(
                boundary.case_sandbox,
                instructions,
            )
            model_calls = 1
            result = await self.provider.response_turn(session, message)
        except CodexRequestTimeout:
            error = "provider_timeout"
        except (CodexUsageLimitExceeded, TerraModelMismatch):
            raise
        except TerraStructuredOutputError as exc:
            structured_failure = exc
            error = "invalid_response_output"
        except TerraProviderError:
            error = "provider_error"
        ended = perf_counter_ns()
        response_latency = (ended - started) / 1_000_000
        usage = result.usage if result is not None else (
            structured_failure.usage if structured_failure is not None else None
        )
        return ResponseStageResult(
            customer_response=result.text if result is not None else None,
            response_stage_latency_ms=response_latency,
            full_response_latency_ms=outcome.decision_path_latency_ms + response_latency,
            response_error=error,
            response_model_calls=model_calls,
            response_input_tokens=usage.input_tokens if usage is not None else 0,
            response_cached_input_tokens=(
                usage.cached_input_tokens if usage is not None else 0
            ),
            response_output_tokens=usage.output_tokens if usage is not None else 0,
            response_reasoning_output_tokens=(
                usage.reasoning_output_tokens if usage is not None else 0
            ),
            thread_id=session.thread_id if session is not None else None,
            turn_id=(
                result.turn_id
                if result is not None
                else structured_failure.turn_id
                if structured_failure is not None
                else None
            ),
            provider_events=(
                result.raw_events
                if result is not None
                else structured_failure.raw_events
                if structured_failure is not None
                else ()
            ),
            provider_versions={
                "terra": getattr(self.provider, "model", "unknown"),
                "codex": getattr(self.provider, "codex_user_agent", "unknown"),
            },
        )
