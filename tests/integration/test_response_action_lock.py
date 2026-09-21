from pathlib import Path
from types import SimpleNamespace

import pytest

from fusebench.agents.base import AgentRunOutcome
from fusebench.agents.responder import SharedTerraResponder
from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import DecisionResult
from fusebench.providers.codex_app_server import TerraSession, TerraUsage
from fusebench.providers.isolation import CaseSandboxManager


class ActionChangingTextProvider:
    model = "gpt-5.6-terra"
    codex_user_agent = "codex-lock-test/1"

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.starts = 0

    async def start_response_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession:
        self.starts += 1
        return TerraSession(
            thread_id=f"thread-{self.starts}",
            session_id=f"thread-{self.starts}",
            case_sandbox=case_sandbox,
            effective_sandbox={"type": "readOnly", "networkAccess": False},
            runtime_workspace_roots=(case_sandbox,),
        )

    async def response_turn(self, session, message):
        self.messages.append(message)
        return SimpleNamespace(
            thread_id=session.thread_id,
            turn_id=f"turn-{len(self.messages)}",
            text="I changed the action to REFUND.",
            usage=TerraUsage(
                input_tokens=10,
                cached_input_tokens=0,
                output_tokens=8,
                reasoning_output_tokens=0,
            ),
            raw_token_events=(),
        )


def decision_outcome(action: Action, system: str) -> AgentRunOutcome:
    probabilities = {
        candidate: 0.96 if candidate is action else 0.01 for candidate in Action
    }
    return AgentRunOutcome(
        decision=DecisionResult(
            raw_action=action,
            executed_action=action,
            action_probabilities=probabilities,
            top_probability=0.96,
            reason_code="LOCKED",
        ),
        model_calls={system: 1},
        decision_path_latency_ms=50.0,
        action_result={"order_id": "ORD-1", "recorded": True},
    )


@pytest.mark.asyncio
async def test_both_architectures_share_responder_and_action_remains_locked(
    tmp_path: Path,
) -> None:
    provider = ActionChangingTextProvider()
    responder = SharedTerraResponder(
        provider=provider,
        sandbox_manager=CaseSandboxManager(tmp_path / "response_sandboxes"),
    )
    terra_only = decision_outcome(Action.WAIT, "terra")
    hybrid = decision_outcome(Action.RESHIP, "jev")
    terra_before = terra_only.model_dump(mode="json")
    hybrid_before = hybrid.model_dump(mode="json")

    terra_response = await responder.respond_for_outcome(
        terra_only,
        customer_message="First message",
        case_id="DEV_TERRA",
        run_id="shared",
        repetition=0,
    )
    hybrid_response = await responder.respond_for_outcome(
        hybrid,
        customer_message="Second message",
        case_id="DEV_HYBRID",
        run_id="shared",
        repetition=0,
    )

    assert provider.starts == 2
    assert terra_response.customer_response == hybrid_response.customer_response
    assert terra_only.model_dump(mode="json") == terra_before
    assert hybrid.model_dump(mode="json") == hybrid_before
    assert terra_only.decision.executed_action is Action.WAIT
    assert hybrid.decision.executed_action is Action.RESHIP
