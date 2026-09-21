"""Authorized CP-13 test generation and preregistered repeatability selection."""

from collections import Counter
from pathlib import Path
from random import Random
from typing import Any

from fusebench.contracts.case import BenchmarkCase
from fusebench.dataset.generator import build_test_dataset
from fusebench.dataset.validation import canonical_json, write_test_dataset

REPEATABILITY_CATEGORIES = (
    "boundary",
    "conflicting_evidence",
    "adversarial",
    "tool_failure",
    "multi_tool",
)


def create_test_dataset(seed: int, output_dir: Path) -> tuple[list[BenchmarkCase], dict[str, Any]]:
    """Create the validated model-free frozen test set exactly once."""

    cases = build_test_dataset(seed)
    return cases, write_test_dataset(cases, output_dir, seed)


def select_repeatability_cases(
    cases: list[BenchmarkCase],
    *,
    seed: int,
) -> list[str]:
    """Select ten cases from each preregistered high-value category."""

    rng = Random(seed)
    selected: list[str] = []
    for category in REPEATABILITY_CATEGORIES:
        candidates = sorted(
            case.visible.case_id for case in cases if case.category == category
        )
        if len(candidates) != 30:
            raise ValueError(f"repeatability category {category} must contain 30 cases")
        selected.extend(sorted(rng.sample(candidates, 10)))
    if len(selected) != 50 or len(set(selected)) != 50:
        raise ValueError("repeatability selection must contain 50 unique IDs")
    counts = Counter(
        next(case.category for case in cases if case.visible.case_id == case_id)
        for case_id in selected
    )
    if counts != Counter({category: 10 for category in REPEATABILITY_CATEGORIES}):
        raise ValueError("repeatability category selection is imbalanced")
    return selected


def write_repeatability_selection(case_ids: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(canonical_json(case_ids) + "\n", encoding="utf-8")
