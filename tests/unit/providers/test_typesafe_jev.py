from pathlib import Path
from typing import Any

import pytest

from fusebench.benchmark.budget import JevBudget
from fusebench.contracts.case import BenchmarkCase
from fusebench.providers.typesafe_jev import ModelVersionChanged, TypeSafeJevProvider
from tests.unit.jev.test_parsing import information_response, terminal_response


class FakeAsyncTypeSafeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def system_one(self, state, questions, **kwargs):
        self.calls.append({"state": state, "questions": questions, "kwargs": kwargs})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_provider_batches_information_questions_and_accounts_usage(
    tmp_path: Path,
    shipping_case: BenchmarkCase,
) -> None:
    client = FakeAsyncTypeSafeClient([information_response()])
    budget_path = tmp_path / "jev_usage.json"
    provider = TypeSafeJevProvider(
        client=client,
        model="jev-latest",
        budget=JevBudget(budget_path, hard_cap_usd=1.0),
    )

    result = await provider.infer_information_needs("policy", shipping_case)

    assert result.need_customer_risk == pytest.approx(0.99)
    assert len(client.calls) == 1
    assert "need_customer_risk" in client.calls[0]["questions"]
    assert client.calls[0]["kwargs"]["model"] == "jev-latest"
    assert client.calls[0]["kwargs"]["retry"].max_retries == 2
    assert budget_path.exists()


@pytest.mark.asyncio
async def test_provider_parses_terminal_call_and_preserves_model_version(
    tmp_path: Path,
    shipping_case: BenchmarkCase,
) -> None:
    client = FakeAsyncTypeSafeClient([information_response(), terminal_response()])
    provider = TypeSafeJevProvider(
        client=client,
        model="jev-latest",
        budget=JevBudget(tmp_path / "usage.json", hard_cap_usd=1.0),
    )
    await provider.infer_information_needs("policy", shipping_case)

    result = await provider.infer_terminal_action(
        "policy",
        shipping_case,
        observations={"tracking": {"carrier_status": "in_transit"}},
        observation_errors={},
    )

    assert result.action.value == "RESHIP"
    assert provider.reported_model == "jev-2026-09-01"


@pytest.mark.asyncio
async def test_provider_rejects_model_change_within_run(
    tmp_path: Path,
    shipping_case: BenchmarkCase,
) -> None:
    first = information_response()
    second = terminal_response()
    second["model"] = "jev-2026-09-15"
    provider = TypeSafeJevProvider(
        client=FakeAsyncTypeSafeClient([first, second]),
        model="jev-latest",
        budget=JevBudget(tmp_path / "usage.json", hard_cap_usd=1.0),
    )
    await provider.infer_information_needs("policy", shipping_case)

    with pytest.raises(ModelVersionChanged):
        await provider.infer_terminal_action(
            "policy",
            shipping_case,
            observations={},
            observation_errors={},
        )
