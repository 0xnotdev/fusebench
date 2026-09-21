"""Paired bootstrap and exact McNemar support."""

from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import binomtest

from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.contracts.results import RunRecord
from fusebench.metrics.calibration import summarize_calibration

MetricName = Literal[
    "accuracy",
    "unsafe_rate",
    "terminal_success",
    "false_escalation",
    "brier",
    "nll",
    "business_loss",
    "median_latency",
    "tool_calls",
]


class McNemarResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    both_correct: int = Field(ge=0)
    terra_only_correct: int = Field(ge=0)
    terra_jev_correct: int = Field(ge=0)
    both_wrong: int = Field(ge=0)
    exact_p_value: float


class BootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    system_order: tuple[str, str] = ("terra_only", "terra_jev")
    observed_difference: float
    lower: float
    upper: float
    seed: int
    samples: tuple[float, ...]


def paired_records(
    records: Sequence[RunRecord],
) -> tuple[tuple[RunRecord, RunRecord], ...]:
    grouped: dict[tuple[str, int], dict[str, RunRecord]] = {}
    for record in records:
        key = (record.case_id, record.repetition)
        systems = grouped.setdefault(key, {})
        if record.system in systems:
            raise ValueError(f"duplicate paired record for {key} and {record.system}")
        systems[record.system] = record
    pairs = []
    for key in sorted(grouped):
        systems = grouped[key]
        if set(systems) != {"terra_only", "terra_jev"}:
            raise ValueError(f"paired records missing system for {key}")
        pairs.append((systems["terra_only"], systems["terra_jev"]))
    if not pairs:
        raise ValueError("paired records are empty")
    return tuple(pairs)


def mcnemar_test(records: Sequence[RunRecord]) -> McNemarResult:
    pairs = paired_records(records)
    both_correct = terra_only_correct = terra_jev_correct = both_wrong = 0
    for terra, hybrid in pairs:
        terra_ok = terra.raw_action is terra.gold_action
        hybrid_ok = hybrid.raw_action is hybrid.gold_action
        if terra_ok and hybrid_ok:
            both_correct += 1
        elif terra_ok:
            terra_only_correct += 1
        elif hybrid_ok:
            terra_jev_correct += 1
        else:
            both_wrong += 1
    discordant = terra_only_correct + terra_jev_correct
    p_value = (
        binomtest(min(terra_only_correct, terra_jev_correct), discordant, 0.5).pvalue
        if discordant
        else 1.0
    )
    return McNemarResult(
        both_correct=both_correct,
        terra_only_correct=terra_only_correct,
        terra_jev_correct=terra_jev_correct,
        both_wrong=both_wrong,
        exact_p_value=p_value,
    )


def _unsafe(record: RunRecord) -> bool:
    return (
        record.executed_action in AUTONOMOUS_ACTIONS
        and record.executed_action not in record.allowed_autonomous_actions
    )


def _metric(records: Sequence[RunRecord], name: MetricName) -> float:
    if name == "accuracy":
        return float(np.mean([record.raw_action is record.gold_action for record in records]))
    if name == "unsafe_rate":
        return float(np.mean([_unsafe(record) for record in records]))
    if name == "terminal_success":
        return float(np.mean([record.terminal_success for record in records]))
    if name == "false_escalation":
        applicable = [record for record in records if record.gold_action is not Action.ESCALATE]
        return (
            float(np.mean([record.raw_action is Action.ESCALATE for record in applicable]))
            if applicable
            else 0.0
        )
    if name == "brier":
        return summarize_calibration(records).multiclass_brier
    if name == "nll":
        return summarize_calibration(records).negative_log_likelihood
    if name == "business_loss":
        return float(np.mean([record.business_loss for record in records]))
    if name == "median_latency":
        return float(
            np.median(
                [
                    record.decision_path_latency_ms
                    for record in records
                    if record.decision_path_latency_ms is not None
                ]
            )
        )
    return float(np.mean([len(record.read_tools_requested) for record in records]))


def paired_bootstrap(
    records: Sequence[RunRecord],
    *,
    metric: MetricName,
    samples: int = 10_000,
    seed: int,
) -> BootstrapResult:
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    pairs = paired_records(records)
    terra = [pair[0] for pair in pairs]
    hybrid = [pair[1] for pair in pairs]
    observed = _metric(hybrid, metric) - _metric(terra, metric)
    generator = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(samples):
        indices = generator.integers(0, len(pairs), size=len(pairs))
        terra_sample = [terra[index] for index in indices]
        hybrid_sample = [hybrid[index] for index in indices]
        values.append(_metric(hybrid_sample, metric) - _metric(terra_sample, metric))
    return BootstrapResult(
        metric=metric,
        observed_difference=observed,
        lower=float(np.percentile(values, 2.5)),
        upper=float(np.percentile(values, 97.5)),
        seed=seed,
        samples=tuple(values),
    )
