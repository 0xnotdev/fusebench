import json
from pathlib import Path

import pytest

from fusebench.benchmark.budget import JevBudget, JevBudgetExceeded


def test_budget_records_input_tokens_and_current_price_atomically(tmp_path: Path) -> None:
    path = tmp_path / "jev_usage.json"
    budget = JevBudget(path=path, hard_cap_usd=1.0)

    budget.record_usage(input_tokens=1_000_000)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["input_tokens"] == 1_000_000
    assert stored["estimated_cost_usd"] == pytest.approx(0.042)
    assert stored["hard_cap_usd"] == pytest.approx(1.0)
    assert not list(tmp_path.glob("*.tmp"))


def test_budget_refuses_projected_request_above_cap(tmp_path: Path) -> None:
    budget = JevBudget(path=tmp_path / "jev_usage.json", hard_cap_usd=0.00001)

    with pytest.raises(JevBudgetExceeded):
        budget.ensure_can_spend(projected_input_tokens=1_000_000)


def test_budget_accumulates_existing_usage(tmp_path: Path) -> None:
    path = tmp_path / "jev_usage.json"
    first = JevBudget(path=path, hard_cap_usd=1.0)
    first.record_usage(input_tokens=100)
    second = JevBudget(path=path, hard_cap_usd=1.0)

    second.record_usage(input_tokens=50)

    assert json.loads(path.read_text(encoding="utf-8"))["input_tokens"] == 150
