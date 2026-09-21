"""Atomic TypeSafe promotional-credit accounting and hard-cap enforcement."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from fusebench.dataset.validation import canonical_json

JEV_INPUT_PRICE_PER_BILLION_USD = 42.0


class JevBudgetExceeded(RuntimeError):
    """A projected request would cross the configured Jev spend cap."""


class JevBudget:
    def __init__(self, path: Path, hard_cap_usd: float) -> None:
        if hard_cap_usd <= 0:
            raise ValueError("hard cap must be positive")
        self.path = path
        self.hard_cap_usd = hard_cap_usd
        self._lock = Lock()

    @staticmethod
    def cost_for_input_tokens(input_tokens: int) -> float:
        if input_tokens < 0:
            raise ValueError("input token count cannot be negative")
        return input_tokens * JEV_INPUT_PRICE_PER_BILLION_USD / 1_000_000_000

    def ensure_can_spend(self, projected_input_tokens: int) -> None:
        ledger = self._load()
        projected = ledger["estimated_cost_usd"] + self.cost_for_input_tokens(
            projected_input_tokens
        )
        if projected > self.hard_cap_usd:
            raise JevBudgetExceeded(
                f"projected Jev spend ${projected:.6f} exceeds cap ${self.hard_cap_usd:.6f}"
            )

    def record_usage(self, input_tokens: int) -> None:
        with self._lock:
            ledger = self._load()
            total_tokens = int(ledger["input_tokens"]) + input_tokens
            updated = {
                "input_tokens": total_tokens,
                "estimated_cost_usd": self.cost_for_input_tokens(total_tokens),
                "hard_cap_usd": self.hard_cap_usd,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(canonical_json(updated) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)

    def _load(self) -> dict[str, float | int | str]:
        if not self.path.exists():
            return {
                "input_tokens": 0,
                "estimated_cost_usd": 0.0,
                "hard_cap_usd": self.hard_cap_usd,
                "updated_at": "",
            }
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "input_tokens": int(value["input_tokens"]),
            "estimated_cost_usd": float(value["estimated_cost_usd"]),
            "hard_cap_usd": self.hard_cap_usd,
            "updated_at": str(value.get("updated_at", "")),
        }
