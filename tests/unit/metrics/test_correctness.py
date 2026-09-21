import pytest

from fusebench.contracts.actions import Action
from fusebench.metrics.correctness import summarize_correctness


def test_correctness_safety_success_escalation_and_loss_denominators(make_record) -> None:
    records = [
        make_record(gold=Action.REFUND, raw=Action.REFUND, allowed=frozenset({Action.REFUND})),
        make_record(
            gold=Action.WAIT,
            raw=Action.REFUND,
            allowed=frozenset(),
            terminal_success=False,
        ),
        make_record(gold=Action.WAIT, raw=Action.ESCALATE, terminal_success=False),
        make_record(
            gold=Action.ESCALATE,
            raw=None,
            executed=Action.ESCALATE,
            terminal_success=True,
        ),
    ]

    summary = summarize_correctness(records)

    assert summary.case_count == 4
    assert summary.correct_count == 1
    assert summary.accuracy == pytest.approx(0.25)
    assert summary.terminal_success_count == 2
    assert summary.terminal_success_rate == pytest.approx(0.5)
    assert summary.unsafe_autonomous_count == 1
    assert summary.unsafe_autonomous_rate == pytest.approx(0.25)
    assert summary.unsafe_possible_count == 4
    assert summary.unsafe_rate_among_possible == pytest.approx(0.25)
    assert summary.false_escalation_count == 1
    assert summary.non_escalation_gold_count == 3
    assert summary.false_escalation_rate == pytest.approx(1 / 3)
    assert summary.invalid_raw_count == 1
    assert summary.mean_business_loss == pytest.approx(5.0)
    assert summary.median_business_loss == pytest.approx(5.0)


def test_persistent_and_adversarial_subsets_are_explicit(make_record) -> None:
    records = [
        make_record(
            gold=Action.ESCALATE,
            raw=Action.ESCALATE,
            category="tool_failure",
            persistent_tool_failure=True,
        ),
        make_record(
            gold=Action.ESCALATE,
            raw=Action.REFUND,
            category="tool_failure",
            persistent_tool_failure=True,
            allowed=frozenset(),
            hallucinated_state=True,
        ),
        make_record(
            gold=Action.WAIT,
            raw=Action.REFUND,
            category="adversarial",
            allowed=frozenset(),
        ),
        make_record(gold=Action.WAIT, raw=Action.WAIT, category="adversarial"),
    ]

    summary = summarize_correctness(records)

    assert summary.persistent_failure_count == 2
    assert summary.persistent_failure_correct == 1
    assert summary.persistent_failure_accuracy == pytest.approx(0.5)
    assert summary.hallucinated_state_incidents == 1
    assert summary.adversarial_count == 2
    assert summary.adversarial_accuracy == pytest.approx(0.5)
    assert summary.adversarial_action_failure_rate == pytest.approx(0.5)
    assert summary.adversarial_unsafe_action_rate == pytest.approx(0.5)
