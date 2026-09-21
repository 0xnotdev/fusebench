import pytest

from fusebench.metrics.efficiency import summarize_efficiency, summarize_tool_use


def test_tool_recall_empty_required_sets_extras_and_invalid_rate(make_record) -> None:
    records = [
        make_record(
            required=frozenset({"get_tracking"}),
            requested=("get_tracking", "get_inventory"),
        ),
        make_record(
            required=frozenset({"get_payment", "get_customer_risk"}),
            requested=("get_payment",),
            invalid_tool_requests=1,
        ),
        make_record(
            required=frozenset(),
            requested=("get_damage_evidence",),
        ),
    ]

    summary = summarize_tool_use(records)

    assert summary.required_applicable_cases == 2
    assert summary.mean_necessary_tool_recall == pytest.approx(0.75)
    assert summary.total_extra_tools == 2
    assert summary.mean_extra_tools_per_case == pytest.approx(2 / 3)
    assert summary.cases_with_extra_tools_rate == pytest.approx(2 / 3)
    assert summary.total_model_requested_reads == 4
    assert summary.mean_model_requested_reads == pytest.approx(4 / 3)
    assert summary.invalid_tool_call_count == 1
    assert summary.invalid_tool_call_rate == pytest.approx(0.25)


def test_latency_percentiles_and_cost_labels(make_record) -> None:
    records = [
        make_record(
            latency=latency,
            terra_input_tokens=1_000_000 if index == 0 else 0,
            terra_output_tokens=100_000 if index == 0 else 0,
            jev_input_tokens=1_000_000 if index == 1 else 0,
        )
        for index, latency in enumerate((10.0, 20.0, 30.0, 40.0))
    ]

    summary = summarize_efficiency(records)

    assert summary.decision_latency_p50_ms == pytest.approx(25.0)
    assert summary.decision_latency_p90_ms == pytest.approx(37.0)
    assert summary.decision_latency_p95_ms == pytest.approx(38.5)
    assert summary.decision_latency_p99_ms == pytest.approx(39.7)
    assert summary.terra_normalized_api_cost_usd == pytest.approx(3.2)
    assert summary.terra_actual_marginal_spend_usd == 0.0
    assert summary.jev_promotional_credit_cost_usd == pytest.approx(0.042)
    assert summary.cost_basis == (
        "Terra API-equivalent normalization; Jev promotional-credit estimate"
    )
