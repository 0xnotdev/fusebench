import pytest

from fusebench.contracts.actions import Action
from fusebench.policy.loss import business_loss


@pytest.mark.parametrize(
    ("gold", "predicted", "expected"),
    [
        (Action.REFUND, Action.REFUND, 0),
        (Action.REFUND, Action.RESHIP, 6),
        (Action.REQUEST_INFO, Action.REFUND, 10),
        (Action.WAIT, Action.ESCALATE, 2),
        (Action.ESCALATE, Action.WAIT, 6),
        (Action.ESCALATE, None, 8),
    ],
)
def test_business_loss_uses_frozen_matrix(
    gold: Action, predicted: Action | None, expected: int
) -> None:
    assert business_loss(gold, predicted) == expected
