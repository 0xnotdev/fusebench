"""Repeatability metrics over independent case repetitions."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import combinations
from statistics import mean

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.results import RunRecord


class ConsistencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_group_count: int = Field(ge=0)
    mean_flip_rate: float
    mean_pairwise_disagreement: float
    mean_confidence_std: float
    mean_pairwise_tool_jaccard: float
    outcome_variance_rate: float


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def summarize_consistency(records: Sequence[RunRecord]) -> ConsistencySummary:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for record in records:
        groups[(record.system, record.case_id)].append(record)
    repeated = [group for group in groups.values() if len(group) >= 2]
    if not repeated:
        raise ValueError("consistency metrics require repeated case runs")
    flips: list[float] = []
    disagreements: list[float] = []
    confidence_stds: list[float] = []
    tool_jaccards: list[float] = []
    outcome_variances: list[bool] = []
    for group in repeated:
        actions = [record.raw_action for record in group]
        modal_count = max(Counter(actions).values())
        flips.append(1 - modal_count / len(actions))
        pairs = list(combinations(group, 2))
        disagreements.append(mean(left.raw_action is not right.raw_action for left, right in pairs))
        confidences = [
            record.top_probability for record in group if record.top_probability is not None
        ]
        confidence_stds.append(float(np.std(confidences)) if confidences else 0.0)
        tool_jaccards.append(
            mean(
                _jaccard(set(left.read_tools_requested), set(right.read_tools_requested))
                for left, right in pairs
            )
        )
        outcome_variances.append(len({record.executed_action for record in group}) > 1)
    return ConsistencySummary(
        case_group_count=len(repeated),
        mean_flip_rate=mean(flips),
        mean_pairwise_disagreement=mean(disagreements),
        mean_confidence_std=mean(confidence_stds),
        mean_pairwise_tool_jaccard=mean(tool_jaccards),
        outcome_variance_rate=mean(outcome_variances),
    )
