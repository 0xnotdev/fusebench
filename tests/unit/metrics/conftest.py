from collections.abc import Callable

import pytest

from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.results import RunRecord
from fusebench.policy.loss import business_loss


@pytest.fixture
def make_record() -> Callable[..., RunRecord]:
    counter = 0

    def factory(
        *,
        system: str = "terra_only",
        case_id: str | None = None,
        repetition: int = 0,
        gold: Action = Action.WAIT,
        raw: Action | None = Action.WAIT,
        executed: Action | None = None,
        probabilities: dict[Action, float] | None = None,
        allowed: frozenset[Action] | None = None,
        required: frozenset[str] = frozenset(),
        requested: tuple[str, ...] = (),
        category: str = "clean",
        issue_type: IssueType = IssueType.SHIPPING,
        terminal_success: bool | None = None,
        latency: float = 10.0,
        invalid_tool_requests: int = 0,
        persistent_tool_failure: bool = False,
        hallucinated_state: bool = False,
        terra_input_tokens: int = 0,
        terra_output_tokens: int = 0,
        jev_input_tokens: int = 0,
        jev_output_tokens: int = 0,
    ) -> RunRecord:
        nonlocal counter
        counter += 1
        record_case_id = case_id or f"CASE_{counter:04d}"
        actual_executed = executed or raw or Action.ESCALATE
        if probabilities is None and raw is not None:
            probabilities = {action: 0.8 if action is raw else 0.05 for action in Action}
        top = max(probabilities.values()) if probabilities is not None else None
        allowed_actions = (
            allowed
            if allowed is not None
            else frozenset(
                {actual_executed} if actual_executed in {Action.REFUND, Action.RESHIP} else set()
            )
        )
        unsafe = (
            actual_executed in {Action.REFUND, Action.RESHIP}
            and actual_executed not in allowed_actions
        )
        correct = raw is gold
        return RunRecord(
            run_id="golden",
            case_id=record_case_id,
            system=system,
            repetition=repetition,
            category=category,
            issue_type=issue_type,
            gold_action=gold,
            raw_action=raw,
            executed_action=actual_executed,
            action_probabilities=probabilities,
            top_probability=top,
            minimal_required_read_tools=required,
            allowed_autonomous_actions=allowed_actions,
            read_tools_requested=requested,
            invalid_tool_requests=invalid_tool_requests,
            persistent_tool_failure=persistent_tool_failure,
            hallucinated_state=hallucinated_state,
            terminal_success=(correct if terminal_success is None else terminal_success),
            decision_path_latency_ms=latency,
            terra_input_tokens=terra_input_tokens,
            terra_output_tokens=terra_output_tokens,
            jev_input_tokens=jev_input_tokens,
            jev_output_tokens=jev_output_tokens,
            unsafe_autonomous=unsafe,
            correct=correct,
            business_loss=business_loss(gold, raw),
        )

    return factory
