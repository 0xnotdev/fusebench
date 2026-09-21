from random import Random

from fusebench.contracts.actions import IssueType
from fusebench.dataset.messages import (
    ADVERSARIAL_SNIPPETS,
    DAMAGE_TEMPLATES,
    DUPLICATE_PAYMENT_TEMPLATES,
    NOISY_TEMPLATES,
    OTHER_TEMPLATES,
    POLITE_TEMPLATES,
    SHIPPING_TEMPLATES,
    TERSE_TEMPLATES,
    render_message,
)
from fusebench.dataset.perturbations import perturb_message


def test_template_banks_meet_minimum_family_sizes() -> None:
    assert len(SHIPPING_TEMPLATES) >= 15
    assert len(DUPLICATE_PAYMENT_TEMPLATES) >= 15
    assert len(DAMAGE_TEMPLATES) >= 15
    assert len(OTHER_TEMPLATES) >= 10
    assert len(TERSE_TEMPLATES) >= 10
    assert len(POLITE_TEMPLATES) >= 10
    assert len(NOISY_TEMPLATES) >= 10
    assert len(ADVERSARIAL_SNIPPETS) >= 10


def test_message_rendering_and_perturbation_are_seed_deterministic() -> None:
    first_rng = Random(42)
    second_rng = Random(42)

    first = perturb_message(
        render_message(IssueType.SHIPPING, days=7, amount=3499, variant=3),
        first_rng,
    )
    second = perturb_message(
        render_message(IssueType.SHIPPING, days=7, amount=3499, variant=3),
        second_rng,
    )

    assert first == second


def test_adversarial_rendering_keeps_customer_injection_visible() -> None:
    message = render_message(
        IssueType.SHIPPING,
        days=2,
        amount=12_500,
        variant=0,
        adversarial=True,
    )

    assert ADVERSARIAL_SNIPPETS[0] in message
