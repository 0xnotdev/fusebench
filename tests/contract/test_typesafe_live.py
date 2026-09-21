from pathlib import Path

import pytest

from fusebench.benchmark.budget import JevBudget
from fusebench.config import get_settings
from fusebench.dataset.validation import canonical_json
from fusebench.providers.typesafe_jev import TypeSafeJevProvider


@pytest.mark.live
@pytest.mark.asyncio
async def test_typesafe_live_contract_reports_model_answers_and_usage() -> None:
    settings = get_settings()
    if not settings.typesafe_api_key:
        pytest.skip("TYPESAFE_API_KEY is not configured")
    provider = TypeSafeJevProvider.from_api_key(
        api_key=settings.typesafe_api_key,
        model=settings.jev_model,
        budget=JevBudget(Path("artifacts/budget/jev_usage.json"), hard_cap_usd=1.0),
    )

    result = await provider.infer_raw(
        state={"probe": "A synthetic contract check with no customer data."},
        questions={"works": provider.noul_question("Is the probe field present?")},
    )

    provider.model = result.model
    concrete_result = await provider.infer_raw(
        state={"probe": "A concrete-model pinning check with no customer data."},
        questions={"works": provider.noul_question("Is the probe field present?")},
    )

    assert result.model
    assert concrete_result.model == result.model
    assert result.usage.input_tokens is not None
    assert result.answers["works"].noul >= 0

    report_path = Path("artifacts/preflight/typesafe-contract.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        canonical_json(
            {
                "answer_noul": result.answers["works"].noul,
                "concrete_model_accepted": True,
                "model": result.model,
                "requested_model": provider.model,
                "usage": result.usage.model_dump(mode="json"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
