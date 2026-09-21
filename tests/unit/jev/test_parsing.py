import pytest

from fusebench.contracts.actions import Action
from fusebench.jev.parsing import (
    JevResponseError,
    parse_information_needs,
    parse_terminal_decision,
)


def information_response() -> dict:
    return {
        "model": "jev-2026-09-01",
        "usage": {"input_tokens": 100, "output_tokens": 10},
        "answers": {
            "issue_type": {
                "type": "choice",
                "choice": "shipping",
                "confidence": 0.9,
                "probabilities": {
                    "shipping": 0.9,
                    "duplicate_payment": 0.04,
                    "damage": 0.03,
                    "other": 0.03,
                },
            },
            "need_tracking": {"type": "noul", "noul": 0.98},
            "need_payment": {"type": "noul", "noul": 0.02},
            "need_inventory": {"type": "noul", "noul": 0.95},
            "need_damage_evidence": {"type": "noul", "noul": 0.01},
            "need_customer_risk": {"type": "noul", "noul": 0.99},
        },
    }


def terminal_response() -> dict:
    return {
        "model": "jev-2026-09-01",
        "usage": {"input_tokens": 140, "output_tokens": 15},
        "answers": {
            "information_sufficient": {"type": "noul", "noul": 0.96},
            "requires_human": {"type": "noul", "noul": 0.02},
            "risk_level": {
                "type": "score",
                "score": 3.0,
                "confidence": 0.8,
                "legend": {
                    1: "Low: routine and reversible",
                    2: "Moderate: customer-impacting but bounded",
                    3: "High: monetary/fulfillment action with meaningful downside",
                    4: "Critical: policy requires escalation",
                },
                "probabilities": {1: 0.01, 2: 0.08, 3: 0.9, 4: 0.01},
            },
            "action": {
                "type": "choice",
                "choice": "RESHIP",
                "confidence": 0.91,
                "probabilities": {
                    "REFUND": 0.02,
                    "RESHIP": 0.94,
                    "REQUEST_INFO": 0.01,
                    "WAIT": 0.02,
                    "ESCALATE": 0.01,
                },
            },
        },
    }


def test_information_needs_parser_preserves_all_noul_values_and_usage() -> None:
    parsed = parse_information_needs(information_response(), latency_ms=12.5)

    assert parsed.issue_type == "shipping"
    assert parsed.need_customer_risk == pytest.approx(0.99)
    assert parsed.reported_model == "jev-2026-09-01"
    assert parsed.input_tokens == 100
    assert parsed.latency_ms == pytest.approx(12.5)


def test_terminal_parser_uses_action_distribution_as_authority() -> None:
    parsed = parse_terminal_decision(terminal_response(), latency_ms=18.0)

    assert parsed.action is Action.RESHIP
    assert parsed.action_probabilities[Action.RESHIP] == pytest.approx(0.94)
    assert parsed.action_confidence == pytest.approx(0.91)
    assert parsed.information_sufficient == pytest.approx(0.96)
    assert parsed.risk_score == pytest.approx(3.0)


def test_missing_answer_is_a_semantic_parse_error() -> None:
    response = information_response()
    del response["answers"]["need_customer_risk"]

    with pytest.raises(JevResponseError, match="need_customer_risk"):
        parse_information_needs(response, latency_ms=1)


def test_malformed_action_probability_distribution_is_rejected() -> None:
    response = terminal_response()
    del response["answers"]["action"]["probabilities"]["ESCALATE"]

    with pytest.raises(JevResponseError, match="probability"):
        parse_terminal_decision(response, latency_ms=1)


def test_missing_usage_is_rejected_when_trustworthy_accounting_is_required() -> None:
    response = information_response()
    response["usage"]["input_tokens"] = None

    with pytest.raises(JevResponseError, match="input token usage"):
        parse_information_needs(response, latency_ms=1)
