"""Tool-use, latency, token, and cost accounting metrics."""

from collections.abc import Sequence
from statistics import mean

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.results import RunRecord


class ToolUseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_applicable_cases: int = Field(ge=0)
    mean_necessary_tool_recall: float | None
    total_extra_tools: int = Field(ge=0)
    mean_extra_tools_per_case: float
    cases_with_extra_tools_rate: float
    total_model_requested_reads: int = Field(ge=0)
    mean_model_requested_reads: float
    total_infrastructure_retries: int = Field(ge=0)
    invalid_tool_call_count: int = Field(ge=0)
    invalid_tool_call_rate: float | None


class EfficiencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_count: int = Field(ge=0)
    decision_latency_p50_ms: float
    decision_latency_p90_ms: float
    decision_latency_p95_ms: float
    decision_latency_p99_ms: float
    terra_input_tokens: int = Field(ge=0)
    terra_output_tokens: int = Field(ge=0)
    jev_input_tokens: int = Field(ge=0)
    jev_output_tokens: int = Field(ge=0)
    terra_normalized_api_cost_usd: float
    terra_actual_marginal_spend_usd: float
    jev_promotional_credit_cost_usd: float
    normalized_cost_per_1000_cases_usd: float
    cost_basis: str


def summarize_tool_use(records: Sequence[RunRecord]) -> ToolUseSummary:
    if not records:
        raise ValueError("tool metrics require at least one record")
    recalls: list[float] = []
    extras: list[int] = []
    reads = 0
    invalid = 0
    for record in records:
        required = set(record.minimal_required_read_tools)
        requested = tuple(record.read_tools_requested)
        if required:
            recalls.append(len(set(requested) & required) / len(required))
        extras.append(sum(tool not in required for tool in requested))
        reads += len(requested)
        invalid += record.invalid_tool_requests
    return ToolUseSummary(
        required_applicable_cases=len(recalls),
        mean_necessary_tool_recall=mean(recalls) if recalls else None,
        total_extra_tools=sum(extras),
        mean_extra_tools_per_case=mean(extras),
        cases_with_extra_tools_rate=sum(value > 0 for value in extras) / len(records),
        total_model_requested_reads=reads,
        mean_model_requested_reads=reads / len(records),
        total_infrastructure_retries=sum(record.infrastructure_retries for record in records),
        invalid_tool_call_count=invalid,
        invalid_tool_call_rate=invalid / reads if reads else None,
    )


def summarize_efficiency(records: Sequence[RunRecord]) -> EfficiencySummary:
    if not records:
        raise ValueError("efficiency metrics require at least one record")
    latencies = [
        record.decision_path_latency_ms
        for record in records
        if record.decision_path_latency_ms is not None
    ]
    if not latencies:
        raise ValueError("efficiency metrics require decision latency")
    terra_input = sum(record.terra_input_tokens for record in records)
    terra_output = sum(record.terra_output_tokens for record in records)
    jev_input = sum(record.jev_input_tokens for record in records)
    jev_output = sum(record.jev_output_tokens for record in records)
    terra_cost = terra_input * 2.0 / 1_000_000 + terra_output * 12.0 / 1_000_000
    jev_cost = jev_input * 42.0 / 1_000_000_000
    total_cost = terra_cost + jev_cost
    return EfficiencySummary(
        case_count=len(records),
        decision_latency_p50_ms=float(np.percentile(latencies, 50)),
        decision_latency_p90_ms=float(np.percentile(latencies, 90)),
        decision_latency_p95_ms=float(np.percentile(latencies, 95)),
        decision_latency_p99_ms=float(np.percentile(latencies, 99)),
        terra_input_tokens=terra_input,
        terra_output_tokens=terra_output,
        jev_input_tokens=jev_input,
        jev_output_tokens=jev_output,
        terra_normalized_api_cost_usd=terra_cost,
        terra_actual_marginal_spend_usd=0.0,
        jev_promotional_credit_cost_usd=jev_cost,
        normalized_cost_per_1000_cases_usd=total_cost / len(records) * 1000,
        cost_basis="Terra API-equivalent normalization; Jev promotional-credit estimate",
    )
