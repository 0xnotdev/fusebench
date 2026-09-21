from pathlib import Path

import pytest

from fusebench.agents.base import AgentRunOutcome, build_action_call
from fusebench.benchmark.preflight import PreflightCheck, PreflightReport
from fusebench.benchmark.recorder import RunRecorder
from fusebench.benchmark.runner import BenchmarkRunner
from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import DecisionResult
from fusebench.dataset.validation import load_cases_jsonl


class OracleFreeFixtureAgent:
    async def run(self, case, runtime, *, run_id, repetition):
        action = case.gold_action
        probabilities = {
            candidate: 0.96 if candidate is action else 0.01 for candidate in Action
        }
        execution = await runtime.execute_action(*build_action_call(case, action, "MOCK"))
        return AgentRunOutcome(
            decision=DecisionResult(
                raw_action=action,
                executed_action=action,
                action_probabilities=probabilities,
                top_probability=0.96,
                reason_code="MOCK",
            ),
            model_calls={"mock": 1},
            decision_path_latency_ms=1.0,
            action_result=execution.result,
        )


@pytest.mark.asyncio
async def test_all_60_dev_cases_produce_120_auditable_records(tmp_path) -> None:
    cases = load_cases_jsonl(Path("data/dev/cases.jsonl"))
    recorder = RunRecorder(tmp_path, "mock-dev")
    runner = BenchmarkRunner(
        cases=cases,
        agents={"terra_only": OracleFreeFixtureAgent(), "terra_jev": OracleFreeFixtureAgent()},
        recorder=recorder,
        preflight=PreflightReport(
            passed=True,
            checks={"mock": PreflightCheck(passed=True, detail="mock")},
        ),
        run_seed=20260921,
    )

    summary = await runner.run()

    assert summary.completed == 120
    assert len(recorder.load_records()) == 120
    assert recorder.verify_checksums() is True
