import json
from pathlib import Path

import pytest

from fusebench.agents.base import AgentRunOutcome
from fusebench.agents.responder import SharedTerraResponder
from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import DecisionResult
from fusebench.providers.codex_app_server import (
    TerraResponseResult,
    TerraSession,
    TerraUsage,
)
from fusebench.providers.codex_protocol import CodexRequestTimeout
from fusebench.providers.isolation import CaseSandboxManager


def outcome(action: Action = Action.RESHIP) -> AgentRunOutcome:
    probabilities = {
        candidate: 0.96 if candidate is action else 0.01 for candidate in Action
    }
    return AgentRunOutcome(
        decision=DecisionResult(
            raw_action=action,
            executed_action=action,
            action_probabilities=probabilities,
            top_probability=0.96,
            reason_code="TEST",
        ),
        model_calls={"terra": 1},
        decision_path_latency_ms=125.0,
        action_result={"order_id": "ORD-1", "reship_executed": True},
    )


class FakeResponseProvider:
    model = "gpt-5.6-terra"
    codex_user_agent = "codex-test/1"

    def __init__(
        self,
        text: str = "A replacement is on the way.",
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error
        self.starts: list[tuple[Path, str]] = []
        self.messages: list[str] = []

    async def start_response_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession:
        self.starts.append((case_sandbox, developer_instructions))
        return TerraSession(
            thread_id=f"thread-{len(self.starts)}",
            session_id=f"thread-{len(self.starts)}",
            case_sandbox=case_sandbox,
            effective_sandbox={"type": "readOnly", "networkAccess": False},
            runtime_workspace_roots=(case_sandbox,),
        )

    async def response_turn(self, session, message):
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        event = {"method": "thread/tokenUsage/updated"}
        return TerraResponseResult(
            thread_id=session.thread_id,
            turn_id=f"turn-{len(self.messages)}",
            text=self.text,
            usage=TerraUsage(
                input_tokens=30,
                cached_input_tokens=5,
                output_tokens=12,
                reasoning_output_tokens=0,
            ),
            raw_token_events=(event,),
            raw_events=(event,),
        )


def make_responder(provider: FakeResponseProvider, tmp_path: Path) -> SharedTerraResponder:
    return SharedTerraResponder(
        provider=provider,
        sandbox_manager=CaseSandboxManager(tmp_path / "artifacts" / "response_sandboxes"),
    )


@pytest.mark.asyncio
async def test_provider_payload_is_exact_allowlist_and_output_has_no_action_field(
    tmp_path: Path,
) -> None:
    provider = FakeResponseProvider(text="I have arranged your replacement.")
    decision = outcome()

    response = await make_responder(provider, tmp_path).respond_for_outcome(
        decision,
        customer_message="My package never arrived.",
        case_id="DEV_0001",
        run_id="response",
        repetition=0,
    )

    assert json.loads(provider.messages[0]) == {
        "action_result": {"order_id": "ORD-1", "reship_executed": True},
        "customer_message": "My package never arrived.",
        "executed_action": "RESHIP",
    }
    assert "policy" not in provider.messages[0].lower()
    assert "gold" not in provider.messages[0].lower()
    assert "hidden" not in provider.messages[0].lower()
    assert "action" not in response.__class__.model_fields
    assert "executed_action" not in response.__class__.model_fields
    assert response.customer_response == "I have arranged your replacement."
    assert response.response_input_tokens == 30
    assert response.response_output_tokens == 12
    assert response.full_response_latency_ms >= decision.decision_path_latency_ms


@pytest.mark.asyncio
async def test_responder_failure_is_recorded_without_mutating_decision(
    tmp_path: Path,
) -> None:
    provider = FakeResponseProvider(error=CodexRequestTimeout("timeout"))
    decision = outcome(Action.WAIT)
    before = decision.model_dump(mode="json")

    response = await make_responder(provider, tmp_path).respond_for_outcome(
        decision,
        customer_message="Where is it?",
        case_id="DEV_0002",
        run_id="response-failure",
        repetition=0,
    )

    assert decision.model_dump(mode="json") == before
    assert decision.decision.executed_action is Action.WAIT
    assert response.customer_response is None
    assert response.response_error == "provider_timeout"
    assert response.response_model_calls == 1


@pytest.mark.asyncio
async def test_response_uses_fresh_empty_sandbox_and_shared_fixed_prompt(
    tmp_path: Path,
) -> None:
    provider = FakeResponseProvider()
    responder = make_responder(provider, tmp_path)

    await responder.respond_for_outcome(
        outcome(),
        customer_message="Help",
        case_id="DEV_0003",
        run_id="fresh",
        repetition=0,
    )

    sandbox, instructions = provider.starts[0]
    assert sandbox.is_dir()
    assert not any(sandbox.iterdir())
    assert "must not change" in instructions.lower()
    assert "company policy" not in instructions.lower()
