"""Explicit allowlisted state serialization for Jev."""

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from fusebench.contracts.case import BenchmarkCase
from fusebench.dataset.validation import (
    assert_no_forbidden_keys,
    canonical_json,
    serialize_visible_case,
)

OBSERVATION_SLOTS = (
    "tracking",
    "payment",
    "inventory",
    "damage_evidence",
    "customer_risk",
)


def build_initial_state(policy: str, case: BenchmarkCase) -> dict[str, Any]:
    state = {"policy": policy, "visible_case": serialize_visible_case(case)}
    assert_no_forbidden_keys(state)
    return state


def build_terminal_state(
    policy: str,
    case: BenchmarkCase,
    observations: Mapping[str, Any],
    observation_errors: Mapping[str, Any],
) -> dict[str, Any]:
    unknown_observations = set(observations) - set(OBSERVATION_SLOTS)
    unknown_errors = set(observation_errors) - set(OBSERVATION_SLOTS)
    if unknown_observations or unknown_errors:
        unknown = sorted(unknown_observations | unknown_errors)
        raise ValueError(f"unknown observation slots: {unknown}")
    state = {
        "policy": policy,
        "visible_case": serialize_visible_case(case),
        "observations": {slot: observations.get(slot) for slot in OBSERVATION_SLOTS},
        "observation_errors": dict(observation_errors),
    }
    assert_no_forbidden_keys(state)
    return state


def payload_sha256(state: Mapping[str, Any]) -> str:
    return sha256(canonical_json(state).encode("utf-8")).hexdigest()
