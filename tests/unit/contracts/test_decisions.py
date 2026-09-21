import math

import pytest
from pydantic import ValidationError

from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import DecisionResult, normalize_action_probabilities


def complete_distribution(**overrides: float) -> dict[str, float]:
    values = {
        "REFUND": 0.05,
        "RESHIP": 0.80,
        "REQUEST_INFO": 0.05,
        "WAIT": 0.05,
        "ESCALATE": 0.05,
    }
    values.update(overrides)
    return values


def test_valid_distribution_selects_argmax_without_marking_invalid() -> None:
    result = normalize_action_probabilities(complete_distribution())

    assert result.valid is True
    assert result.selected_action is Action.RESHIP
    assert result.top_probability == pytest.approx(0.80)
    assert result.original_sum == pytest.approx(1.0)
    assert result.errors == ()


def test_distribution_within_sum_tolerance_is_renormalized() -> None:
    result = normalize_action_probabilities(
        complete_distribution(RESHIP=0.79, ESCALATE=0.05)
    )

    assert result.valid is True
    assert result.renormalized is True
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.original_sum == pytest.approx(0.99)


def test_outside_tolerance_is_usable_but_invalid() -> None:
    result = normalize_action_probabilities(
        {
            "REFUND": 0.1,
            "RESHIP": 0.5,
            "REQUEST_INFO": 0.1,
            "WAIT": 0.1,
            "ESCALATE": 0.1,
        }
    )

    assert result.valid is False
    assert result.selected_action is Action.RESHIP
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert "sum_outside_tolerance" in result.errors


@pytest.mark.parametrize(
    "raw, error",
    [
        ({"REFUND": 1.0}, "keys_mismatch"),
        (complete_distribution(REFUND=math.nan), "non_finite"),
        (complete_distribution(REFUND=-0.1, RESHIP=0.95), "outside_unit_interval"),
        ({action.value: 0.0 for action in Action}, "non_positive_total"),
    ],
)
def test_malformed_distribution_is_invalid(raw: dict[str, float], error: str) -> None:
    result = normalize_action_probabilities(raw)

    assert result.valid is False
    assert error in result.errors


def test_decision_result_requires_probability_argmax_to_match_raw_action() -> None:
    normalized = normalize_action_probabilities(complete_distribution())

    with pytest.raises(ValidationError):
        DecisionResult(
            raw_action=Action.REFUND,
            executed_action=Action.REFUND,
            action_probabilities=normalized.probabilities,
            top_probability=normalized.top_probability,
        )
