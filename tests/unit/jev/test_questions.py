from typesafe_sdk import Choice, Noul, Score

from fusebench.dataset.validation import assert_no_forbidden_keys
from fusebench.jev.questions import information_need_questions, terminal_action_questions


def test_information_need_questions_are_one_batched_mapping_with_customer_risk() -> None:
    questions = information_need_questions()

    assert set(questions) == {
        "issue_type",
        "need_tracking",
        "need_payment",
        "need_inventory",
        "need_damage_evidence",
        "need_customer_risk",
    }
    assert isinstance(questions["issue_type"], Choice)
    assert all(isinstance(questions[name], Noul) for name in set(questions) - {"issue_type"})
    assert "REFUND" in str(questions["need_customer_risk"].instructions)
    assert "RESHIP" in str(questions["need_customer_risk"].instructions)


def test_terminal_questions_have_one_authoritative_action_and_diagnostics() -> None:
    questions = terminal_action_questions()

    assert set(questions) == {
        "information_sufficient",
        "requires_human",
        "risk_level",
        "action",
    }
    assert isinstance(questions["action"], Choice)
    assert isinstance(questions["risk_level"], Score)
    assert set(questions["action"].criteria) == {
        "REFUND",
        "RESHIP",
        "REQUEST_INFO",
        "WAIT",
        "ESCALATE",
    }
    assert_no_forbidden_keys({name: question.model_dump() for name, question in questions.items()})
