"""Scenario-first deterministic development dataset generation."""

from random import Random

from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase, VisibleCase
from fusebench.dataset.messages import render_message
from fusebench.dataset.perturbations import perturb_message
from fusebench.dataset.scenarios import (
    DEV_CATEGORY_COUNTS,
    ScenarioBlueprint,
    build_scenario_state,
    development_blueprints,
)
from fusebench.policy.oracle import decide

__all__ = ["DEV_CATEGORY_COUNTS", "build_dev_dataset"]


def build_dev_dataset(seed: int) -> list[BenchmarkCase]:
    """Build all 60 development cases deterministically from structured state."""

    rng = Random(seed)
    blueprints = list(development_blueprints())
    rng.shuffle(blueprints)
    return [_build_case(blueprint, index, rng) for index, blueprint in enumerate(blueprints, 1)]


def _build_case(
    blueprint: ScenarioBlueprint,
    index: int,
    rng: Random,
) -> BenchmarkCase:
    state = build_scenario_state(blueprint)
    case_id = f"DEV_{index:04d}"
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
