"""Decision distributions and normalized agent outcomes."""

import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fusebench.contracts.actions import Action


class ProbabilityNormalization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probabilities: dict[Action, float] = Field(default_factory=dict)
    selected_action: Action | None = None
    top_probability: float | None = None
    original_sum: float | None = None
    renormalized: bool = False
    valid: bool
    errors: tuple[str, ...] = ()


def normalize_action_probabilities(raw: Mapping[str | Action, Any]) -> ProbabilityNormalization:
    """Validate and, when possible, normalize a five-action distribution."""

    expected = {action.value for action in Action}
    normalized_keys = {
        key.value if isinstance(key, Action) else str(key): value for key, value in raw.items()
    }
    errors: list[str] = []
    if set(normalized_keys) != expected:
        errors.append("keys_mismatch")

    values: dict[Action, float] = {}
    invalid_numeric = False
    for action in Action:
        value = normalized_keys.get(action.value, 0.0)
        try:
            number = float(value)
        except (TypeError, ValueError):
            invalid_numeric = True
            continue
        if not math.isfinite(number):
            errors.append("non_finite")
            invalid_numeric = True
            continue
        if not 0.0 <= number <= 1.0:
            errors.append("outside_unit_interval")
            invalid_numeric = True
        values[action] = number

    if invalid_numeric:
        return ProbabilityNormalization(valid=False, errors=tuple(dict.fromkeys(errors)))

    total = sum(values.values())
    if total <= 0:
        errors.append("non_positive_total")
        return ProbabilityNormalization(
            original_sum=total,
            valid=False,
            errors=tuple(dict.fromkeys(errors)),
        )

    in_tolerance = 0.98 <= total <= 1.02
    if not in_tolerance:
        errors.append("sum_outside_tolerance")
    probabilities = {action: value / total for action, value in values.items()}
    selected = max(Action, key=lambda action: probabilities[action])
    return ProbabilityNormalization(
        probabilities=probabilities,
        selected_action=selected,
        top_probability=probabilities[selected],
        original_sum=total,
        renormalized=not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12),
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
    )


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_action: Action | None
    executed_action: Action
    action_probabilities: dict[Action, float] | None = None
    top_probability: float | None = Field(default=None, ge=0, le=1)
    reason_code: str | None = None
    invalid_probability_distribution: bool = False
    original_probability_sum: float | None = None
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_distribution_consistency(self) -> "DecisionResult":
        if self.action_probabilities is None:
            if self.raw_action is not None or self.top_probability is not None:
                raise ValueError("raw action and top probability require probabilities")
            return self
        if set(self.action_probabilities) != set(Action):
            raise ValueError("probabilities must contain exactly all actions")
        selected = max(Action, key=lambda action: self.action_probabilities[action])
        top = self.action_probabilities[selected]
        if self.raw_action != selected:
            raise ValueError("raw_action must equal probability argmax")
        if self.top_probability is None or not math.isclose(
            self.top_probability, top, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("top_probability must equal distribution maximum")
        return self
