import pytest

from fusebench.contracts.actions import Action
from fusebench.metrics.coverage import continuous_risk_coverage, threshold_sweep


def distribution(action: Action, top: float) -> dict[Action, float]:
    remainder = (1.0 - top) / 4
    return {candidate: top if candidate is action else remainder for candidate in Action}


def test_threshold_and_continuous_risk_coverage(make_record) -> None:
    records = [
        make_record(
            gold=Action.WAIT,
            raw=Action.WAIT,
            probabilities=distribution(Action.WAIT, 0.9),
        ),
        make_record(
            gold=Action.WAIT,
            raw=Action.REFUND,
            probabilities=distribution(Action.REFUND, 0.8),
            allowed=frozenset(),
        ),
        make_record(
            gold=Action.REQUEST_INFO,
            raw=Action.REQUEST_INFO,
            probabilities=distribution(Action.REQUEST_INFO, 0.4),
        ),
    ]

    sweep = threshold_sweep(records, thresholds=(0.5, 0.85))

    assert sweep[0].covered_count == 2
    assert sweep[0].coverage == pytest.approx(2 / 3)
    assert sweep[0].action_error_rate == pytest.approx(0.5)
    assert sweep[0].unsafe_error_rate == pytest.approx(0.5)
    assert sweep[1].covered_count == 1
    assert sweep[1].coverage == pytest.approx(1 / 3)
    assert sweep[1].action_error_rate == 0.0
    assert sweep[1].unsafe_error_rate == 0.0

    curve = continuous_risk_coverage(records)
    assert len(curve.points) == 3
    assert curve.points[0].confidence == pytest.approx(0.9)
    assert curve.coverage_at_two_percent_error == pytest.approx(1 / 3)
    assert curve.coverage_at_zero_observed_unsafe == pytest.approx(1 / 3)
    assert curve.zero_unsafe_covered_count == 1
