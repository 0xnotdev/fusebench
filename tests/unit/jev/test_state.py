import pytest

from fusebench.contracts.case import BenchmarkCase
from fusebench.dataset.validation import assert_no_forbidden_keys
from fusebench.jev.state import build_initial_state, build_terminal_state, payload_sha256


def test_initial_state_contains_only_policy_and_visible_case(
    shipping_case: BenchmarkCase,
) -> None:
    state = build_initial_state("frozen policy", shipping_case)

    assert set(state) == {"policy", "visible_case"}
    assert state["visible_case"] == shipping_case.visible.model_dump(mode="json")
    assert_no_forbidden_keys(state)


def test_terminal_state_has_fixed_observation_slots_and_errors(
    shipping_case: BenchmarkCase,
) -> None:
    state = build_terminal_state(
        "frozen policy",
        shipping_case,
        observations={"tracking": {"carrier_status": "in_transit"}},
        observation_errors={"customer_risk": {"kind": "unavailable"}},
    )

    assert set(state["observations"]) == {
        "tracking",
        "payment",
        "inventory",
        "damage_evidence",
        "customer_risk",
    }
    assert state["observations"]["customer_risk"] is None
    assert state["observation_errors"]["customer_risk"] == {"kind": "unavailable"}
    assert_no_forbidden_keys(state)


def test_terminal_state_rejects_unknown_observation_slot(
    shipping_case: BenchmarkCase,
) -> None:
    with pytest.raises(ValueError, match="unknown observation"):
        build_terminal_state(
            "frozen policy",
            shipping_case,
            observations={"oracle": {"gold": "RESHIP"}},
            observation_errors={},
        )


def test_payload_hash_is_stable_for_equivalent_state(shipping_case: BenchmarkCase) -> None:
    first = build_initial_state("frozen policy", shipping_case)
    second = {"visible_case": first["visible_case"], "policy": "frozen policy"}

    assert payload_sha256(first) == payload_sha256(second)
