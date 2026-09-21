"""Sequential paired benchmark runner and normalized record construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from fusebench.agents.base import AgentRunOutcome
from fusebench.agents.responder import ResponseStageResult, SharedTerraResponder
from fusebench.benchmark.budget import JevBudgetExceeded
from fusebench.benchmark.preflight import PreflightReport
from fusebench.benchmark.recorder import RunRecorder
from fusebench.benchmark.scheduler import build_paired_schedule
from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.contracts.results import FailureTag, RunRecord
from fusebench.policy.loss import business_loss
from fusebench.providers.codex_app_server import CodexUsageLimitExceeded
from fusebench.simulator.environment import SimulatorEnvironment
from fusebench.simulator.tool_runtime import ToolRuntime


class DecisionAgent(Protocol):
    async def run(
        self,
        case: BenchmarkCase,
        runtime: ToolRuntime,
        *,
        run_id: str,
        repetition: int,
    ) -> AgentRunOutcome: ...


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scheduled: int = Field(ge=0)
    completed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    stopped_for_usage_limit: bool = False


class BenchmarkRunner:
    """Run one case-system at a time with adjacent paired scheduling and safe resume."""

    def __init__(
        self,
        *,
        cases: Sequence[BenchmarkCase],
        agents: Mapping[str, DecisionAgent],
        recorder: RunRecorder,
        preflight: PreflightReport,
        run_seed: int,
        responder: SharedTerraResponder | None = None,
    ) -> None:
        if set(agents) != {"terra_only", "terra_jev"}:
            raise ValueError("runner requires exactly terra_only and terra_jev agents")
        self.cases = tuple(cases)
        self.agents = dict(agents)
        self.recorder = recorder
        self.preflight = preflight
        self.run_seed = run_seed
        self.responder = responder

    async def run(self) -> RunSummary:
        if not self.preflight.passed:
            raise RuntimeError("passing preflight is required before benchmark execution")
        by_id = {case.visible.case_id: case for case in self.cases}
        schedule = build_paired_schedule(tuple(by_id), seed=self.run_seed)
        completed = 0
        skipped = 0
        for item in schedule:
            key = (item.case_id, item.system, item.repetition)
            if key in self.recorder.completed_keys:
                skipped += 1
                continue
            case = by_id[item.case_id]
            environment = SimulatorEnvironment.from_case(
                case,
                seed=_case_seed(self.run_seed, item.case_id, item.repetition),
            )
            runtime = ToolRuntime(environment, item.system)  # type: ignore[arg-type]
            try:
                outcome = await self.agents[item.system].run(
                    case,
                    runtime,
                    run_id=self.recorder.run_id,
                    repetition=item.repetition,
                )
                response = await self._respond(
                    case, outcome, item.system, item.repetition
                )
            except (CodexUsageLimitExceeded, JevBudgetExceeded):
                return RunSummary(
                    scheduled=len(schedule),
                    completed=completed,
                    skipped=skipped,
                    stopped_for_usage_limit=True,
                )
            record = _build_record(
                self.recorder.run_id,
                case,
                item.system,
                item.repetition,
                outcome,
                response,
                environment,
            )
            self._write_raw(item.system, item.case_id, item.repetition, outcome, response)
            self.recorder.append(record)
            completed += 1
        return RunSummary(
            scheduled=len(schedule), completed=completed, skipped=skipped
        )

    async def _respond(
        self,
        case: BenchmarkCase,
        outcome: AgentRunOutcome,
        system: str,
        repetition: int,
    ) -> ResponseStageResult | None:
        if self.responder is None:
            return None
        return await self.responder.respond_for_outcome(
            outcome,
            customer_message=case.visible.customer_message,
            case_id=f"{case.visible.case_id}-{system}",
            run_id=self.recorder.run_id,
            repetition=repetition,
        )

    def _write_raw(
        self,
        system: str,
        case_id: str,
        repetition: int,
        outcome: AgentRunOutcome,
        response: ResponseStageResult | None,
    ) -> None:
        common = {"system": system, "case_id": case_id, "repetition": repetition}
        self.recorder.write_raw_json(
            **common,
            name="decision_outcome.json",
            value=outcome.model_dump(mode="json"),
        )
        self.recorder.write_raw_jsonl(
            **common,
            name="tool_events.jsonl",
            values=(event.model_dump(mode="json") for event in outcome.tool_events),
        )
        self.recorder.write_raw_jsonl(
            **common,
            name="codex_events.jsonl",
            values=outcome.provider_events,
        )
        for index, state in enumerate(outcome.jev_request_states, start=1):
            self.recorder.write_raw_json(
                **common, name=f"jev_request_{index}.json", value=state
            )
        for index, result in enumerate(outcome.jev_responses, start=1):
            self.recorder.write_raw_json(
                **common, name=f"jev_response_{index}.json", value=result
            )
        if response is not None:
            self.recorder.write_raw_json(
                **common,
                name="response_stage.json",
                value=response.model_dump(mode="json"),
            )


def _case_seed(run_seed: int, case_id: str, repetition: int) -> int:
    digest = sha256(f"{run_seed}:{case_id}:{repetition}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _build_record(
    run_id: str,
    case: BenchmarkCase,
    system: str,
    repetition: int,
    outcome: AgentRunOutcome,
    response: ResponseStageResult | None,
    environment: SimulatorEnvironment,
) -> RunRecord:
    raw = outcome.decision.raw_action
    executed = outcome.decision.executed_action
    unsafe = executed in AUTONOMOUS_ACTIONS and executed not in case.allowed_autonomous_actions
    correct = raw is case.gold_action
    persistent = any(plan.persistent for plan in case.hidden.tool_failures.values())
    hallucinated = bool(
        persistent
        and raw not in {None, Action.ESCALATE, Action.REQUEST_INFO}
        and raw is not case.gold_action
    )
    errors = _failure_tags(case, outcome, unsafe, persistent, hallucinated)
    versions = dict(outcome.provider_versions)
    if response is not None:
        versions.update(
            {f"response_{key}": value for key, value in response.provider_versions.items()}
        )
    return RunRecord(
        run_id=run_id,
        case_id=case.visible.case_id,
        system=system,
        repetition=repetition,
        category=case.category,
        issue_type=case.hidden.issue_type,
        gold_action=case.gold_action,
        raw_action=raw,
        executed_action=executed,
        action_probabilities=outcome.decision.action_probabilities,
        top_probability=outcome.decision.top_probability,
        minimal_required_read_tools=case.minimal_required_read_tools,
        allowed_autonomous_actions=case.allowed_autonomous_actions,
        read_tools_requested=outcome.read_tools_requested,
        invalid_tool_requests=outcome.invalid_tool_requests,
        infrastructure_retries=outcome.infrastructure_retries,
        model_calls=outcome.model_calls,
        decision_path_latency_ms=outcome.decision_path_latency_ms,
        full_response_latency_ms=(
            response.full_response_latency_ms if response is not None else None
        ),
        terra_input_tokens=outcome.terra_input_tokens,
        terra_output_tokens=outcome.terra_output_tokens,
        jev_input_tokens=outcome.jev_input_tokens,
        jev_output_tokens=outcome.jev_output_tokens,
        unsafe_autonomous=unsafe,
        correct=correct,
        business_loss=business_loss(case.gold_action, raw),
        provider_versions=versions,
        terminal_success=environment.state.terminal_action is case.gold_action,
        persistent_tool_failure=persistent,
        hallucinated_state=hallucinated,
        errors=errors,
    )


def _failure_tags(
    case: BenchmarkCase,
    outcome: AgentRunOutcome,
    unsafe: bool,
    persistent: bool,
    hallucinated: bool,
) -> tuple[FailureTag, ...]:
    tags: list[FailureTag] = []
    if outcome.decision.raw_action is not case.gold_action:
        tags.append(FailureTag.WRONG_BUSINESS_ACTION)
    if unsafe:
        tags.append(FailureTag.UNSAFE_AUTONOMOUS_ACTION)
    if (
        outcome.decision.raw_action is Action.ESCALATE
        and case.gold_action is not Action.ESCALATE
    ):
        tags.append(FailureTag.FALSE_ESCALATION)
    requested = set(outcome.read_tools_requested)
    if not case.minimal_required_read_tools <= requested:
        tags.append(FailureTag.MISSING_REQUIRED_TOOL)
    if requested - case.minimal_required_read_tools:
        tags.append(FailureTag.UNNECESSARY_TOOL)
    if outcome.invalid_tool_requests:
        tags.append(FailureTag.INVALID_TOOL_ARGUMENTS)
    if outcome.loop_limit_exceeded:
        tags.append(FailureTag.LOOP_LIMIT)
    if outcome.decision.invalid_probability_distribution:
        tags.append(FailureTag.INVALID_PROBABILITY_DISTRIBUTION)
    if persistent:
        tags.append(FailureTag.PERSISTENT_TOOL_UNAVAILABLE)
    mapping = {
        "provider_timeout": FailureTag.PROVIDER_TIMEOUT,
        "provider_usage_limit": FailureTag.PROVIDER_USAGE_LIMIT,
        "provider_http_error": FailureTag.PROVIDER_HTTP_ERROR,
        "model_version_changed": FailureTag.MODEL_VERSION_CHANGED,
    }
    tags.extend(
        mapping[error]
        for error in outcome.decision.errors
        if error in mapping
    )
    if hallucinated:
        tags.append(FailureTag.UNKNOWN)
    return tuple(dict.fromkeys(tags))
