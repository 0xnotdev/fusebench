"""Scored action and issue enums."""

from enum import StrEnum


class Action(StrEnum):
    """The complete v1 terminal action space."""

    REFUND = "REFUND"
    RESHIP = "RESHIP"
    REQUEST_INFO = "REQUEST_INFO"
    WAIT = "WAIT"
    ESCALATE = "ESCALATE"


class IssueType(StrEnum):
    """Supported diagnostic issue families."""

    SHIPPING = "SHIPPING"
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    DAMAGE = "DAMAGE"
    OTHER = "OTHER"


AUTONOMOUS_ACTIONS = frozenset({Action.REFUND, Action.RESHIP})
