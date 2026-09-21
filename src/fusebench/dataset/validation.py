"""Canonical serialization, leakage checks, and dataset validation."""

import json
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fusebench.constants import SPEC_VERSION
from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.dataset.scenarios import (
    DEV_CATEGORY_COUNTS,
    TEST_ACTION_COUNTS,
    TEST_CATEGORY_COUNTS,
)
from fusebench.policy.oracle import decide

FORBIDDEN_PROVIDER_KEYS = frozenset(
    {
        "gold",
        "gold_action",
        "expected_action",
        "oracle",
        "minimal_required",
        "minimal_required_read_tools",
        "allowed_autonomous",
        "allowed_autonomous_actions",
        "category",
        "difficulty",
        "business_loss",
        "test_label",
    }
)


@dataclass(frozen=True)
class DatasetValidationReport:
    case_count: int
    category_counts: dict[str, int]
    action_counts: dict[str, int]
    issue_counts: dict[str, int]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Set) and not isinstance(value, (str, bytes)):
        return sorted((_jsonable(item) for item in value), key=lambda item: str(item))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize deterministic UTF-8 JSON with no non-finite numeric values."""

    try:
        return json.dumps(
            _jsonable(value),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError as error:
        raise ValueError("canonical JSON requires finite numeric values") from error


def assert_no_forbidden_keys(value: Any, path: str = "$") -> None:
    """Reject evaluator-only names recursively before any provider call."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_PROVIDER_KEYS:
                raise ValueError(f"forbidden provider key {key!s} at {path}")
            assert_no_forbidden_keys(item, f"{path}.{key!s}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            assert_no_forbidden_keys(item, f"{path}[{index}]")


def serialize_visible_case(case: BenchmarkCase) -> dict[str, Any]:
    payload = case.visible.model_dump(mode="json")
    assert_no_forbidden_keys(payload)
    return payload


def validate_dev_dataset(cases: list[BenchmarkCase]) -> DatasetValidationReport:
    if len(cases) != 60:
        raise ValueError(f"development dataset must contain 60 cases, got {len(cases)}")
    ids = [case.visible.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case IDs must be unique")
    semantic_ids = [case.generation_metadata.get("semantic_scenario_id") for case in cases]
    if len(semantic_ids) != len(set(semantic_ids)):
        raise ValueError("semantic scenario IDs must be unique")
    category_counts = Counter(case.category for case in cases)
    if category_counts != Counter(DEV_CATEGORY_COUNTS):
        raise ValueError(f"unexpected development category counts: {dict(category_counts)}")
    if {case.gold_action for case in cases} != set(Action):
        raise ValueError("development dataset must represent every terminal action")
    for case in cases:
        oracle = decide(case)
        if (
            oracle.action is not case.gold_action
            or oracle.minimal_required_read_tools != case.minimal_required_read_tools
            or oracle.allowed_autonomous_actions != case.allowed_autonomous_actions
        ):
            raise ValueError(f"stored oracle metadata mismatch for {case.visible.case_id}")
        assert_no_forbidden_keys(serialize_visible_case(case))
    return DatasetValidationReport(
        case_count=len(cases),
        category_counts=dict(sorted(category_counts.items())),
        action_counts=dict(sorted(Counter(case.gold_action.value for case in cases).items())),
        issue_counts=dict(sorted(Counter(case.hidden.issue_type.value for case in cases).items())),
    )


def validate_test_dataset(cases: list[BenchmarkCase]) -> DatasetValidationReport:
    """Validate every frozen test balance, oracle, identity, and no-leak invariant."""

    if len(cases) != 240:
        raise ValueError(f"test dataset must contain 240 cases, got {len(cases)}")
    ids = [case.visible.case_id for case in cases]
    if len(ids) != len(set(ids)) or not all(case_id.startswith("TEST_") for case_id in ids):
        raise ValueError("test case IDs must be unique TEST_ identifiers")
    semantic_ids = [case.generation_metadata.get("semantic_scenario_id") for case in cases]
    if len(semantic_ids) != len(set(semantic_ids)):
        raise ValueError("test semantic scenario IDs must be unique")

    category_counts = Counter(case.category for case in cases)
    if category_counts != Counter(TEST_CATEGORY_COUNTS):
        raise ValueError(f"unexpected test category counts: {dict(category_counts)}")
    action_counts = Counter(case.gold_action for case in cases)
    if action_counts != Counter(TEST_ACTION_COUNTS):
        raise ValueError(
            "unexpected test action counts: "
            f"{dict(sorted((action.value, count) for action, count in action_counts.items()))}"
        )

    visible_fields = set(BenchmarkCase.model_fields["visible"].annotation.model_fields)  # type: ignore[union-attr]
    if {"prior_exception_refunds_90d", "trusted_records_conflict"} & visible_fields:
        raise ValueError("hidden customer-risk fields leaked into VisibleCase")
    for case in cases:
        oracle = decide(case)
        if (
            oracle.action is not case.gold_action
            or oracle.minimal_required_read_tools != case.minimal_required_read_tools
            or oracle.allowed_autonomous_actions != case.allowed_autonomous_actions
        ):
            raise ValueError(f"stored oracle metadata mismatch for {case.visible.case_id}")
        visible = serialize_visible_case(case)
        assert_no_forbidden_keys(visible)
        if {"prior_exception_refunds_90d", "trusted_records_conflict"} & set(visible):
            raise ValueError(f"hidden customer-risk fields leaked in {case.visible.case_id}")

    return DatasetValidationReport(
        case_count=len(cases),
        category_counts=dict(sorted(category_counts.items())),
        action_counts=dict(
            sorted((action.value, count) for action, count in action_counts.items())
        ),
        issue_counts=dict(sorted(Counter(case.hidden.issue_type.value for case in cases).items())),
    )


def cases_jsonl_bytes(cases: list[BenchmarkCase]) -> bytes:
    return ("\n".join(canonical_json(case) for case in cases) + "\n").encode("utf-8")


def write_dev_dataset(cases: list[BenchmarkCase], output_dir: Path, seed: int) -> dict[str, Any]:
    report = validate_dev_dataset(cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = cases_jsonl_bytes(cases)
    cases_path = output_dir / "cases.jsonl"
    cases_path.write_bytes(payload)
    manifest = {
        "spec_version": SPEC_VERSION,
        "seed": seed,
        "case_count": report.case_count,
        "dataset_sha256": sha256(payload).hexdigest(),
        "category_counts": report.category_counts,
        "action_counts": report.action_counts,
        "issue_counts": report.issue_counts,
    }
    (output_dir / "manifest.json").write_text(
        canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return manifest


def write_test_dataset(
    cases: list[BenchmarkCase], output_dir: Path, seed: int
) -> dict[str, Any]:
    """Write a validated frozen test set and its exact byte hash."""

    report = validate_test_dataset(cases)
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = cases_jsonl_bytes(cases)
    cases_path = output_dir / "cases.jsonl"
    cases_path.write_bytes(payload)
    manifest = {
        "spec_version": SPEC_VERSION,
        "seed": seed,
        "case_count": report.case_count,
        "dataset_sha256": sha256(payload).hexdigest(),
        "category_counts": report.category_counts,
        "action_counts": report.action_counts,
        "issue_counts": report.issue_counts,
        "generation_order": [
            "structured_hidden_state",
            "deterministic_oracle",
            "gold_action_locked",
            "message_rendering",
            "linguistic_perturbation",
            "validation",
        ],
        "model_generated_labels_or_messages": False,
    }
    (output_dir / "manifest.json").write_text(
        canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_cases_jsonl(path: Path) -> list[BenchmarkCase]:
    return [
        BenchmarkCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
