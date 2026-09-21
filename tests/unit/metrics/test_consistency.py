import math

import pytest

from fusebench.contracts.actions import Action
from fusebench.metrics.consistency import summarize_consistency


def test_flip_pairwise_confidence_tool_and_outcome_variance(make_record) -> None:
    actions = (Action.WAIT, Action.WAIT, Action.WAIT, Action.REFUND, Action.WAIT)
    confidences = (0.9, 0.8, 0.7, 0.6, 0.5)
    tools = (
        ("get_tracking",),
        ("get_tracking",),
        ("get_tracking",),
        ("get_payment",),
        ("get_tracking",),
    )
    records = []
    for repetition, (action, confidence, requested) in enumerate(
        zip(actions, confidences, tools, strict=True)
    ):
        remainder = (1 - confidence) / 4
        probabilities = {
            candidate: confidence if candidate is action else remainder for candidate in Action
        }
        records.append(
            make_record(
                case_id="REPEAT_1",
                repetition=repetition,
                gold=Action.WAIT,
                raw=action,
                probabilities=probabilities,
                requested=requested,
            )
        )

    summary = summarize_consistency(records)

    assert summary.case_group_count == 1
    assert summary.mean_flip_rate == pytest.approx(0.2)
    assert summary.mean_pairwise_disagreement == pytest.approx(0.4)
    assert summary.mean_confidence_std == pytest.approx(math.sqrt(0.02))
    assert summary.mean_pairwise_tool_jaccard == pytest.approx(0.6)
    assert summary.outcome_variance_rate == 1.0
