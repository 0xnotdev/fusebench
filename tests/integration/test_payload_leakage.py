from fusebench.dataset.validation import FORBIDDEN_PROVIDER_KEYS, assert_no_forbidden_keys
from fusebench.jev.state import build_initial_state, build_terminal_state


def test_all_constructed_jev_states_pass_recursive_leakage_audit(shipping_case) -> None:
    initial = build_initial_state("policy", shipping_case)
    terminal = build_terminal_state(
        "policy",
        shipping_case,
        {"tracking": {"order_id": shipping_case.visible.order_id}},
        {},
    )

    assert_no_forbidden_keys(initial)
    assert_no_forbidden_keys(terminal)
    serialized = str(initial) + str(terminal)
    assert all(key not in serialized for key in FORBIDDEN_PROVIDER_KEYS)
