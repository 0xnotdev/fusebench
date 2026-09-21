from collections import Counter

from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.dataset.generator import DEV_CATEGORY_COUNTS, build_dev_dataset
from fusebench.policy.oracle import decide


def test_dev_dataset_has_exact_size_categories_and_unique_ids() -> None:
    cases = build_dev_dataset(seed=20260921)

    assert len(cases) == 60
    assert Counter(case.category for case in cases) == Counter(DEV_CATEGORY_COUNTS)
    assert len({case.visible.case_id for case in cases}) == 60
    assert len({case.generation_metadata["semantic_scenario_id"] for case in cases}) == 60


def test_every_stored_label_and_required_tool_set_comes_from_oracle() -> None:
    for case in build_dev_dataset(seed=20260921):
        oracle = decide(case)
        assert case.gold_action is oracle.action
        assert case.minimal_required_read_tools == oracle.minimal_required_read_tools
        assert case.allowed_autonomous_actions == oracle.allowed_autonomous_actions


def test_dev_dataset_represents_every_action_and_issue_type() -> None:
    cases = build_dev_dataset(seed=20260921)

    assert {case.gold_action for case in cases} == set(Action)
    assert len({case.hidden.issue_type for case in cases}) == 4


def test_autonomous_gold_actions_require_customer_risk_read() -> None:
    for case in build_dev_dataset(seed=20260921):
        if case.gold_action in AUTONOMOUS_ACTIONS:
            assert "get_customer_risk" in case.minimal_required_read_tools


def test_generation_is_byte_stable_for_a_fixed_seed() -> None:
    first = build_dev_dataset(seed=90210)
    second = build_dev_dataset(seed=90210)

    assert [case.model_dump_json() for case in first] == [
        case.model_dump_json() for case in second
    ]


def test_adversarial_cases_retain_untrusted_injection_text() -> None:
    adversarial = [
        case for case in build_dev_dataset(seed=20260921) if case.category == "adversarial"
    ]

    assert len(adversarial) == DEV_CATEGORY_COUNTS["adversarial"]
    assert all("OVERRIDE" in case.visible.customer_message.upper() for case in adversarial)
