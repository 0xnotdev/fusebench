import hashlib
import json
from collections import Counter
from pathlib import Path

from fusebench.dataset.freeze import (
    REPEATABILITY_CATEGORIES,
    create_test_dataset,
    select_repeatability_cases,
    write_repeatability_selection,
)


def test_create_test_dataset_writes_exact_hash_and_balances(tmp_path: Path) -> None:
    cases, manifest = create_test_dataset(123456789, tmp_path / "test")

    cases_path = tmp_path / "test" / "cases.jsonl"
    assert len(cases) == 240
    assert manifest["dataset_sha256"] == hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert set(manifest["category_counts"].values()) == {30}
    assert set(manifest["action_counts"].values()) == {48}
    assert manifest["model_generated_labels_or_messages"] is False


def test_repeatability_selection_is_seeded_and_preregistered(tmp_path: Path) -> None:
    cases, _ = create_test_dataset(11, tmp_path / "test")

    first = select_repeatability_cases(cases, seed=22)
    second = select_repeatability_cases(cases, seed=22)
    write_repeatability_selection(first, tmp_path / "repeatability" / "selected.json")

    by_id = {case.visible.case_id: case for case in cases}
    counts = Counter(by_id[case_id].category for case_id in first)
    assert first == second
    assert len(first) == len(set(first)) == 50
    assert counts == Counter({category: 10 for category in REPEATABILITY_CATEGORIES})
    assert json.loads(
        (tmp_path / "repeatability" / "selected.json").read_text(encoding="utf-8")
    ) == first
