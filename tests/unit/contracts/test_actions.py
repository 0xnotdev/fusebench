from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action, IssueType


def test_action_enum_has_exactly_the_five_scored_actions() -> None:
    assert [action.value for action in Action] == [
        "REFUND",
        "RESHIP",
        "REQUEST_INFO",
        "WAIT",
        "ESCALATE",
    ]


def test_only_refund_and_reship_are_autonomous_side_effect_actions() -> None:
    assert frozenset({Action.REFUND, Action.RESHIP}) == AUTONOMOUS_ACTIONS


def test_issue_type_enum_matches_dataset_contract() -> None:
    assert {issue.value for issue in IssueType} == {
        "SHIPPING",
        "DUPLICATE_PAYMENT",
        "DAMAGE",
        "OTHER",
    }
