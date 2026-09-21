import os
from pathlib import Path

import pytest

from fusebench.benchmark.budget import JevBudget
from fusebench.providers.typesafe_jev import TypeSafeJevProvider


@pytest.mark.live
@pytest.mark.asyncio
async def test_typesafe_live_contract_reports_model_answers_and_usage(tmp_path: Path) -> None:
    if not os.getenv("TYPESAFE_API_KEY"):
        pytest.skip("TYPESAFE_API_KEY is not configured")
    provider = TypeSafeJevProvider.from_api_key(
        api_key=os.environ["TYPESAFE_API_KEY"],
        model=os.getenv("JEV_MODEL", "jev-latest"),
        budget=JevBudget(tmp_path / "usage.json", hard_cap_usd=1.0),
    )

    result = await provider.infer_raw(
        state={"probe": "A synthetic contract check with no customer data."},
        questions={"works": provider.noul_question("Is the probe field present?")},
    )

    assert result.model
    assert result.usage.input_tokens is not None
    assert result.answers["works"].noul >= 0
