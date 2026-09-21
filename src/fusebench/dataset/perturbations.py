"""Seeded, deterministic linguistic perturbations."""

from random import Random

from fusebench.dataset.messages import NOISY_TEMPLATES, POLITE_TEMPLATES, TERSE_TEMPLATES


def perturb_message(message: str, rng: Random) -> str:
    """Apply at most one reproducible surface perturbation without changing truth."""

    choice = rng.randrange(8)
    if choice == 0:
        return message.lower()
    if choice == 1:
        return message.rstrip(".!?")
    if choice == 2:
        return f"{message.rstrip('.')}!!!"
    if choice == 3:
        return message.replace("please", "pls").replace("Tracking", "Trackng")
    if choice == 4:
        return f"{message} {NOISY_TEMPLATES[rng.randrange(len(NOISY_TEMPLATES))]}."
    if choice == 5:
        return f"This is frustrating. {message}"
    if choice == 6:
        return f"{POLITE_TEMPLATES[rng.randrange(len(POLITE_TEMPLATES))]} {message}"
    return f"{TERSE_TEMPLATES[rng.randrange(len(TERSE_TEMPLATES))]} — {message}"
