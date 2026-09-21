"""Multiclass calibration metrics for valid five-action distributions."""

import math
from collections.abc import Sequence
from statistics import mean

from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.actions import Action
from fusebench.contracts.results import RunRecord


class CalibrationBin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    lower: float
    upper: float
    count: int = Field(ge=0)
    mean_confidence: float | None = None
    empirical_accuracy: float | None = None


class HighConfidenceMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: float
    count: int = Field(ge=0)
    error_rate: float | None


class CalibrationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scored_count: int = Field(ge=0)
    multiclass_brier: float
    negative_log_likelihood: float
    ece: float
    bins: tuple[CalibrationBin, ...]
    high_confidence: dict[float, HighConfidenceMetric]


def _scored(records: Sequence[RunRecord]) -> list[RunRecord]:
    return [
        record
        for record in records
        if record.action_probabilities is not None and record.top_probability is not None
    ]


def summarize_calibration(
    records: Sequence[RunRecord],
    *,
    bin_count: int = 10,
    high_confidence_thresholds: tuple[float, ...] = (0.90, 0.95, 0.99),
) -> CalibrationSummary:
    """Compute unscaled Brier, clipped NLL, top-label ECE, and confidence errors."""

    if bin_count <= 0:
        raise ValueError("bin_count must be positive")
    scored = _scored(records)
    if not scored:
        raise ValueError("calibration metrics require at least one probability record")
    brier_values: list[float] = []
    nll_values: list[float] = []
    members: list[list[RunRecord]] = [[] for _ in range(bin_count)]
    for record in scored:
        assert record.action_probabilities is not None
        assert record.top_probability is not None
        brier_values.append(
            sum(
                (
                    record.action_probabilities[action]
                    - (1.0 if action is record.gold_action else 0.0)
                )
                ** 2
                for action in Action
            )
        )
        nll_values.append(-math.log(max(record.action_probabilities[record.gold_action], 1e-12)))
        index = min(int(record.top_probability * bin_count), bin_count - 1)
        members[index].append(record)
    bins: list[CalibrationBin] = []
    ece = 0.0
    for index, group in enumerate(members):
        confidence = mean(record.top_probability for record in group) if group else None
        accuracy = (
            mean(record.raw_action is record.gold_action for record in group) if group else None
        )
        if confidence is not None and accuracy is not None:
            ece += len(group) / len(scored) * abs(accuracy - confidence)
        bins.append(
            CalibrationBin(
                index=index,
                lower=index / bin_count,
                upper=(index + 1) / bin_count,
                count=len(group),
                mean_confidence=confidence,
                empirical_accuracy=accuracy,
            )
        )
    high_confidence = {}
    for threshold in high_confidence_thresholds:
        group = [record for record in scored if record.top_probability >= threshold]
        errors = sum(record.raw_action is not record.gold_action for record in group)
        high_confidence[threshold] = HighConfidenceMetric(
            threshold=threshold,
            count=len(group),
            error_rate=errors / len(group) if group else None,
        )
    return CalibrationSummary(
        scored_count=len(scored),
        multiclass_brier=mean(brier_values),
        negative_log_likelihood=mean(nll_values),
        ece=ece,
        bins=tuple(bins),
        high_confidence=high_confidence,
    )
