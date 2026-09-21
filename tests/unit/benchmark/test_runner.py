from pathlib import Path

import pytest

from fusebench.agents.base import AgentRunOutcome, build_action_call
from fusebench.benchmark.preflight import PreflightCheck, PreflightReport
from fusebench.benchmark.recorder import RunRecorder
from fusebench.benchmark.runner import BenchmarkRunner
from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import DecisionResult
from fusebench.providers.codex_app_server import CodexUsageLimitExceeded


class GoldAgent:
    def __init__(self) -> None:
        self.seeds: list[int] = []
        self.fresh_terminal_states: list[Action | None] = []

    async def run(self, case, runtime, *, run_id, repetition):
        self.seeds.append(runtime.environment.seed)
        self.fresh_terminal_states.append(runtime.environment.state.terminal_action)
        action = case.gold_action
        probabilities = {
            candidate: 0.96 if candidate is action else 0.01 for candidate in Action
        }
        execution = await runtime.execute_action(*build_action_call(case, action, "GOLD_FAKE"))
        return AgentRunOutcome(
            decision=DecisionResult(
                raw_action=action,
                executed_action=action,
                action_probabilities=probabilities,
                top_probability=0.96,
                reason_code="GOLD_FAKE",
            ),
            model_calls={"fake": 1},
            decision_path_latency_ms=1.0,
            action_result=execution.result,
            provider_versions={"fake": "1"},
        )


class UsageLimitAgent:
    async def run(self, case, runtime, *, run_id, repetition):
        raise CodexUsageLimitExceeded("limit")


class UsageLimitResponder:
    async def respond_for_outcome(self, *args, **kwargs):
        raise CodexUsageLimitExceeded("limit")


def preflight(passed: bool = True) -> PreflightReport:
    return PreflightReport(
        passed=passed,
        checks={"gate": PreflightCheck(passed=passed, detail="test")},
    )


@pytest.mark.asyncio
async def test_runner_pairs_fresh_equivalent_state_and_resumes(
    shipping_case,
    tmp_path: Path,
) -> None:
    second = shipping_case.model_copy(
        update={
            "visible": shipping_case.visible.model_copy(update={"case_id": "DEV_0002"})
        }
    )
    terra = GoldAgent()
    hybrid = GoldAgent()
    recorder = RunRecorder(tmp_path, "dev-run")
    runner = BenchmarkRunner(
        cases=[shipping_case, second],
        agents={"terra_only": terra, "terra_jev": hybrid},
        recorder=recorder,
        preflight=preflight(),
        run_seed=55,
    )

    first = await runner.run()
    resumed = await runner.run()

    assert first.completed == 4
    assert first.skipped == 0
    assert resumed.completed == 0
    assert resumed.skipped == 4
    assert terra.fresh_terminal_states == [None, None]
    assert hybrid.fresh_terminal_states == [None, None]
    assert terra.seeds == hybrid.seeds
    assert len(recorder.load_records()) == 4
    assert recorder.verify_checksums() is True


@pytest.mark.asyncio
async def test_runner_refuses_failed_preflight(shipping_case, tmp_path: Path) -> None:
    runner = BenchmarkRunner(
        cases=[shipping_case],
        agents={"terra_only": GoldAgent(), "terra_jev": GoldAgent()},
        recorder=RunRecorder(tmp_path, "blocked"),
        preflight=preflight(False),
        run_seed=1,
    )

    with pytest.raises(RuntimeError, match="preflight"):
        await runner.run()


@pytest.mark.asyncio
async def test_usage_limit_checkpoints_without_synthetic_record(
    shipping_case,
    tmp_path: Path,
) -> None:
    recorder = RunRecorder(tmp_path, "limited")
    runner = BenchmarkRunner(
        cases=[shipping_case],
        agents={"terra_only": UsageLimitAgent(), "terra_jev": UsageLimitAgent()},
        recorder=recorder,
        preflight=preflight(),
        run_seed=2,
    )

    summary = await runner.run()

    assert summary.stopped_for_usage_limit is True
    assert summary.completed == 0
    assert recorder.load_records() == []


@pytest.mark.asyncio
async def test_response_usage_limit_checkpoints_without_synthetic_record(
    shipping_case,
    tmp_path: Path,
) -> None:
    recorder = RunRecorder(tmp_path, "response-limited")
    runner = BenchmarkRunner(
        cases=[shipping_case],
        agents={"terra_only": GoldAgent(), "terra_jev": GoldAgent()},
        recorder=recorder,
        preflight=preflight(),
        run_seed=2,
        responder=UsageLimitResponder(),
    )

    summary = await runner.run()

    assert summary.stopped_for_usage_limit is True
    assert summary.completed == 0
    assert recorder.load_records() == []
