"""Frozen secondary business-loss diagnostic."""

from fusebench.contracts.actions import Action

_LOSS_MATRIX: dict[Action, dict[Action, int]] = {
    Action.REFUND: {
        Action.REFUND: 0,
        Action.RESHIP: 6,
        Action.REQUEST_INFO: 3,
        Action.WAIT: 4,
        Action.ESCALATE: 2,
    },
    Action.RESHIP: {
        Action.REFUND: 6,
        Action.RESHIP: 0,
        Action.REQUEST_INFO: 3,
        Action.WAIT: 4,
        Action.ESCALATE: 2,
    },
    Action.REQUEST_INFO: {
        Action.REFUND: 10,
        Action.RESHIP: 10,
        Action.REQUEST_INFO: 0,
        Action.WAIT: 3,
        Action.ESCALATE: 2,
    },
    Action.WAIT: {
        Action.REFUND: 10,
        Action.RESHIP: 10,
        Action.REQUEST_INFO: 2,
        Action.WAIT: 0,
        Action.ESCALATE: 2,
    },
    Action.ESCALATE: {
        Action.REFUND: 10,
        Action.RESHIP: 10,
        Action.REQUEST_INFO: 5,
        Action.WAIT: 6,
        Action.ESCALATE: 0,
    },
}


def business_loss(gold: Action, predicted: Action | None) -> int:
    """Return the preregistered loss, including invalid/no-decision output."""

    if predicted is None:
        return 8
    return _LOSS_MATRIX[gold][predicted]
