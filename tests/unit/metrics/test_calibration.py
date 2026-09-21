import math

import pytest

from fusebench.contracts.actions import Action
from fusebench.metrics.calibration import summarize_calibration


def test_brier_nll_ece_bins_and_high_confidence_errors(make_record) -> None:
    first = {
        Action.REFUND: 0.8,
        Action.RESHIP: 0.05,
        Action.REQUEST_INFO: 0.05,
        Action.WAIT: 0.05,
        Action.ESCALATE: 0.05,
    }
    second = {
        Action.REFUND: 0.6,
        Action.RESHIP: 0.1,
        Action.REQUEST_INFO: 0.1,
        Action.WAIT: 0.1,
        Action.ESCALATE: 0.1,
    }
    records = [
        make_record(gold=Action.REFUND, raw=Action.REFUND, probabilities=first),
        make_record(gold=Action.WAIT, raw=Action.REFUND, probabilities=second),
    ]

    summary = summarize_calibration(records, high_confidence_thresholds=(0.5, 0.9))

    assert summary.scored_count == 2
    assert summary.multiclass_brier == pytest.approx(0.625)
    assert summary.negative_log_likelihood == pytest.approx((-math.log(0.8) - math.log(0.1)) / 2)
    assert summary.ece == pytest.approx(0.4)
    assert len(summary.bins) == 10
    assert summary.bins[6].count == 1
    assert summary.bins[6].mean_confidence == pytest.approx(0.6)
    assert summary.bins[6].empirical_accuracy == 0.0
    assert summary.bins[8].count == 1
    assert summary.bins[8].empirical_accuracy == 1.0
    assert summary.high_confidence[0.5].count == 2
    assert summary.high_confidence[0.5].error_rate == pytest.approx(0.5)
    assert summary.high_confidence[0.9].count == 0
    assert summary.high_confidence[0.9].error_rate is None


def test_nll_clips_zero_gold_probability(make_record) -> None:
    probabilities = {
        Action.REFUND: 1.0,
        Action.RESHIP: 0.0,
        Action.REQUEST_INFO: 0.0,
        Action.WAIT: 0.0,
        Action.ESCALATE: 0.0,
    }
    record = make_record(gold=Action.WAIT, raw=Action.REFUND, probabilities=probabilities)

    summary = summarize_calibration([record])

    assert summary.negative_log_likelihood == pytest.approx(-math.log(1e-12))
