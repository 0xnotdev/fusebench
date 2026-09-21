"""TypeSafe System One adapter with strict parsing and budget accounting."""

from collections.abc import Mapping
from time import perf_counter_ns
from typing import Any, Protocol

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Noul,
    Question,
    RetryPolicy,
    SystemOneResponse,
)

from fusebench.benchmark.budget import JevBudget
from fusebench.contracts.case import BenchmarkCase
from fusebench.dataset.validation import canonical_json
from fusebench.jev.parsing import (
    InformationNeeds,
    JevDecision,
    parse_information_needs,
    parse_terminal_decision,
)
from fusebench.jev.questions import information_need_questions, terminal_action_questions
from fusebench.jev.state import build_initial_state, build_terminal_state


class ModelVersionChanged(RuntimeError):
    """The concrete Jev model changed within one benchmark provider session."""


class AsyncSystemOneClient(Protocol):
    async def system_one(
        self,
        state: Any,
        questions: Mapping[str, Question],
        **kwargs: Any,
    ) -> Any: ...


class TypeSafeJevProvider:
    """Provider boundary for batched Jev information and action judgments."""

    def __init__(
        self,
        client: AsyncSystemOneClient,
        model: str,
        budget: JevBudget,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.client = client
        self.model = model
        self.budget = budget
        self.timeout_seconds = timeout_seconds
        self.retry_policy = RetryPolicy(max_retries=2, timeout=timeout_seconds)
        self.reported_model: str | None = None

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        model: str,
        budget: JevBudget,
        timeout_seconds: float = 30.0,
    ) -> "TypeSafeJevProvider":
        client = AsyncTypeSafeClient(
            api_key=api_key,
            model=model,
            retry=RetryPolicy(max_retries=2, timeout=timeout_seconds),
            timeout=timeout_seconds,
        )
        return cls(client=client, model=model, budget=budget, timeout_seconds=timeout_seconds)

    @staticmethod
    def noul_question(instructions: str) -> Noul:
        return Noul(instructions=instructions)

    async def infer_raw(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, Question],
    ) -> SystemOneResponse:
        projected_tokens = max(1, len(canonical_json(state).encode("utf-8")) // 3)
        self.budget.ensure_can_spend(projected_tokens)
        raw = await self.client.system_one(
            state,
            questions,
            model=self.model,
            retry=self.retry_policy,
            timeout=self.timeout_seconds,
        )
        response = SystemOneResponse.model_validate(raw)
        if response.usage.input_tokens is None:
            raise ValueError("TypeSafe response omitted input token usage")
        self.budget.record_usage(response.usage.input_tokens)
        self._record_model(response.model)
        return response

    async def infer_information_needs(
        self,
        policy: str,
        case: BenchmarkCase,
    ) -> InformationNeeds:
        state = build_initial_state(policy, case)
        started = perf_counter_ns()
        response = await self.infer_raw(state, information_need_questions())
        latency_ms = (perf_counter_ns() - started) / 1_000_000
        return parse_information_needs(response, latency_ms)

    async def infer_terminal_action(
        self,
        policy: str,
        case: BenchmarkCase,
        observations: Mapping[str, Any],
        observation_errors: Mapping[str, Any],
    ) -> JevDecision:
        state = build_terminal_state(policy, case, observations, observation_errors)
        started = perf_counter_ns()
        response = await self.infer_raw(state, terminal_action_questions())
        latency_ms = (perf_counter_ns() - started) / 1_000_000
        return parse_terminal_decision(response, latency_ms)

    def _record_model(self, model: str) -> None:
        if self.reported_model is None:
            self.reported_model = model
            return
        if model != self.reported_model:
            raise ModelVersionChanged(
                f"Jev model changed from {self.reported_model} to {model}"
            )
