"""Scenario-first deterministic development dataset generation."""

from random import Random

from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase, VisibleCase
from fusebench.dataset.messages import render_message
from fusebench.dataset.perturbations import perturb_message
from fusebench.dataset.scenarios import (
    DEV_CATEGORY_COUNTS,
    TEST_ACTION_COUNTS,
    TEST_CATEGORY_COUNTS,
    ScenarioBlueprint,
    build_scenario_state,
    development_blueprints,
    test_blueprints,
)
from fusebench.policy.oracle import decide

__all__ = [
    "DEV_CATEGORY_COUNTS",
    "TEST_ACTION_COUNTS",
    "TEST_CATEGORY_COUNTS",
    "build_dev_dataset",
    "build_test_dataset",
]


def build_dev_dataset(seed: int) -> list[BenchmarkCase]:
    """Build all 60 development cases deterministically from structured state."""

    return _build_dataset(development_blueprints(), seed=seed, split="DEV")


def build_test_dataset(seed: int) -> list[BenchmarkCase]:
    """Build the frozen 240-case test design without any model calls."""

    return _build_dataset(test_blueprints(), seed=seed, split="TEST")


def _build_dataset(
    blueprints: tuple[ScenarioBlueprint, ...],
    *,
    seed: int,
    split: str,
) -> list[BenchmarkCase]:
    rng = Random(seed)
    shuffled = list(blueprints)
    rng.shuffle(shuffled)
    return [
        _build_case(blueprint, index, rng, split=split)
        for index, blueprint in enumerate(shuffled, 1)
    ]


def _build_case(
    blueprint: ScenarioBlueprint,
    index: int,
    rng: Random,
    *,
    split: str,
) -> BenchmarkCase:
    state = build_scenario_state(blueprint)
    case_id = f"{split}_{index:04d}"
    semantic_id = (
        f"{blueprint.category}-{blueprint.ordinal:02d}-"
        f"{blueprint.target_action.value.lower()}"
    )
    visible = VisibleCase(
        case_id=case_id,
        customer_id=f"CUS-{index:04d}",
        order_id=f"ORD-{index:04d}",
        sku=f"SKU-{(index % 17) + 1:03d}",
        customer_message="message-rendered-after-oracle",
        amount_inr=state.amount_inr,
        basic_status=state.basic_status,
    )
    provisional = BenchmarkCase(
        visible=visible,
        hidden=state.hidden,
        category=blueprint.category,
        gold_action=Action.ESCALATE,
        minimal_required_read_tools=frozenset(),
        allowed_autonomous_actions=frozenset(),
        generation_metadata={"semantic_scenario_id": semantic_id, "seed": seed_from_rng(rng)},
    )
    oracle = decide(provisional)
    if oracle.action is not blueprint.target_action:
        raise ValueError(
            f"scenario {semantic_id} expected {blueprint.target_action.value} "
            f"but oracle returned {oracle.action.value}"
        )
    base_message = render_message(
        state.issue_type,
        days=state.hidden.days_without_carrier_movement,
        amount=state.amount_inr,
        variant=blueprint.ordinal,
        adversarial=blueprint.category == "adversarial",
    )
    message = (
        base_message
        if blueprint.category == "adversarial"
        else perturb_message(base_message, rng)
    )
    return provisional.model_copy(
        update={
            "visible": visible.model_copy(update={"customer_message": message}),
            "gold_action": oracle.action,
            "minimal_required_read_tools": oracle.minimal_required_read_tools,
            "allowed_autonomous_actions": oracle.allowed_autonomous_actions,
        }
    )


def seed_from_rng(rng: Random) -> int:
    """Record a deterministic per-case generation nonce without external state."""

    return rng.getrandbits(64)
