import json

import pytest

from fusebench.dataset.freeze import FreezeNotAuthorized, create_test_dataset
from fusebench.dataset.generator import build_dev_dataset
from fusebench.dataset.validation import (
    FORBIDDEN_PROVIDER_KEYS,
    assert_no_forbidden_keys,
    canonical_json,
    serialize_visible_case,
)


def test_visible_serializer_exposes_only_visible_case_fields() -> None:
    case = build_dev_dataset(seed=1)[0]

    payload = serialize_visible_case(case)

    assert payload == case.visible.model_dump(mode="json")
    assert_no_forbidden_keys(payload)


def test_recursive_leakage_check_rejects_evaluator_key_at_any_depth() -> None:
    with pytest.raises(ValueError, match="gold_action"):
        assert_no_forbidden_keys({"nested": [{"gold_action": "REFUND"}]})


def test_canonical_json_sorts_keys_and_rejects_nonfinite_values() -> None:
    assert canonical_json({"z": 1, "a": {"y", "x"}}) == '{"a":["x","y"],"z":1}'
    with pytest.raises(ValueError, match="finite"):
        canonical_json({"value": float("nan")})


def test_forbidden_key_set_contains_specified_evaluator_fields() -> None:
    assert {"gold_action", "oracle", "category", "business_loss"} <= FORBIDDEN_PROVIDER_KEYS


def test_test_dataset_creation_is_blocked_before_cp13() -> None:
    with pytest.raises(FreezeNotAuthorized):
        create_test_dataset(seed=123)


def test_canonical_case_json_is_valid_json() -> None:
    encoded = canonical_json(build_dev_dataset(seed=1)[0])

    assert json.loads(encoded)["visible"]["case_id"].startswith("DEV_")
