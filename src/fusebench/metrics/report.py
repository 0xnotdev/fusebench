"""Regenerate analysis tables and neutral publication summaries from run records."""

import csv
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from fusebench.contracts.results import RunRecord
from fusebench.dataset.validation import canonical_json
from fusebench.metrics.calibration import summarize_calibration
from fusebench.metrics.correctness import summarize_correctness
from fusebench.metrics.coverage import continuous_risk_coverage, threshold_sweep
from fusebench.metrics.efficiency import summarize_efficiency, summarize_tool_use
from fusebench.metrics.statistics import MetricName, mcnemar_test, paired_bootstrap

_BOOTSTRAP_METRICS: tuple[MetricName, ...] = (
    "accuracy",
    "unsafe_rate",
    "terminal_success",
    "false_escalation",
    "brier",
    "nll",
    "business_loss",
    "median_latency",
    "tool_calls",
)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _system_summary(records: list[RunRecord]) -> dict[str, Any]:
    return {
        "correctness": summarize_correctness(records).model_dump(mode="json"),
        "calibration": summarize_calibration(records).model_dump(mode="json"),
        "tools": summarize_tool_use(records).model_dump(mode="json"),
        "efficiency": summarize_efficiency(records).model_dump(mode="json"),
        "coverage": continuous_risk_coverage(records).model_dump(mode="json"),
    }


def _breakdown_rows(
    records: Sequence[RunRecord],
    attribute: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for record in records:
        value = getattr(record, attribute)
        if hasattr(value, "value"):
            value = value.value
        groups[(str(value or "unknown"), record.system)].append(record)
    rows = []
    for (group, system), group_records in sorted(groups.items()):
        summary = summarize_correctness(group_records)
        rows.append(
            {
                "group": group,
                "system": system,
                "case_count": summary.case_count,
                "accuracy": summary.accuracy,
                "terminal_success_rate": summary.terminal_success_rate,
                "unsafe_autonomous_rate": summary.unsafe_autonomous_rate,
                "false_escalation_rate": summary.false_escalation_rate,
                "mean_business_loss": summary.mean_business_loss,
            }
        )
    return rows


def generate_analysis(
    records: Sequence[RunRecord],
    output_dir: Path,
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """Write every section-40 analysis artifact solely from normalized records."""

    systems: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        systems[record.system].append(record)
    if set(systems) != {"terra_only", "terra_jev"}:
        raise ValueError("analysis requires paired terra_only and terra_jev records")
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {system: _system_summary(values) for system, values in systems.items()}
    summary = {
        "record_count": len(records),
        "systems": summaries,
        "cost_note": (
            "Terra is an API-equivalent normalization with zero marginal subscription "
            "spend; Jev is estimated promotional-credit consumption."
        ),
    }
    breakdown_fields = [
        "group",
        "system",
        "case_count",
        "accuracy",
        "terminal_success_rate",
        "unsafe_autonomous_rate",
        "false_escalation_rate",
        "mean_business_loss",
    ]
    _write_csv(
        output_dir / "per_category.csv",
        _breakdown_rows(records, "category"),
        breakdown_fields,
    )
    _write_csv(
        output_dir / "per_action.csv",
        _breakdown_rows(records, "gold_action"),
        breakdown_fields,
    )
    _write_csv(
        output_dir / "per_issue.csv",
        _breakdown_rows(records, "issue_type"),
        breakdown_fields,
    )

    calibration_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for system, system_records in sorted(systems.items()):
        calibration = summarize_calibration(system_records)
        calibration_rows.extend(
            {"system": system, **item.model_dump(mode="json")} for item in calibration.bins
        )
        coverage_rows.extend(
            {"system": system, "kind": "threshold", **item.model_dump(mode="json")}
            for item in threshold_sweep(system_records)
        )
        coverage_rows.extend(
            {"system": system, "kind": "continuous", **item.model_dump(mode="json")}
            for item in continuous_risk_coverage(system_records).points
        )
    _write_csv(
        output_dir / "calibration_bins.csv",
        calibration_rows,
        [
            "system",
            "index",
            "lower",
            "upper",
            "count",
            "mean_confidence",
            "empirical_accuracy",
        ],
    )
    _write_csv(
        output_dir / "risk_coverage.csv",
        coverage_rows,
        [
            "system",
            "kind",
            "threshold",
            "confidence",
            "covered_count",
            "total_count",
            "coverage",
            "action_error_rate",
            "unsafe_error_rate",
        ],
    )

    bootstrap_summaries = []
    bootstrap_sample_rows = []
    for metric in _BOOTSTRAP_METRICS:
        result = paired_bootstrap(
            records,
            metric=metric,
            samples=bootstrap_samples,
            seed=bootstrap_seed,
        )
        bootstrap_summaries.append(
            {
                "metric": metric,
                "observed_difference": result.observed_difference,
                "lower": result.lower,
                "upper": result.upper,
                "samples": bootstrap_samples,
                "seed": bootstrap_seed,
            }
        )
        bootstrap_sample_rows.extend(
            {
                "metric": metric,
                "sample_index": index,
                "difference": difference,
                "seed": bootstrap_seed,
            }
            for index, difference in enumerate(result.samples)
        )
    _write_csv(
        output_dir / "paired_bootstrap.csv",
        bootstrap_sample_rows,
        ["metric", "sample_index", "difference", "seed"],
    )
    mcnemar = mcnemar_test(records)
    (output_dir / "mcnemar.json").write_text(canonical_json(mcnemar) + "\n", encoding="utf-8")
    summary["paired_bootstrap"] = bootstrap_summaries
    summary["mcnemar"] = mcnemar.model_dump(mode="json")
    (output_dir / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8")
    _write_methodology(output_dir / "methodology_snapshot.md", bootstrap_seed)
    _write_summary_markdown(output_dir / "summary.md", summaries, bootstrap_summaries)
    return summary


def _write_methodology(path: Path, seed: int) -> None:
    path.write_text(
        """# FuseBench methodology snapshot

Primary accuracy uses the raw top-probability action; invalid/no decision is incorrect.
Primary unsafe outcomes use the executed business action. Calibration uses unscaled
multiclass Brier, gold-label NLL clipped at `1e-12`, and 10 equal-width top-label bins.

Jev probabilities are native structured outputs while Terra probabilities are elicited
structured outputs. They are operational confidence signals but are not architecturally identical.
Confidence gates are evaluated offline across the preregistered threshold grid.

Claims of safety use the wording "0 observed unsafe errors in N covered test cases"; this
does not establish zero risk. Latency is end-to-end decision-path latency from this client
environment, not pure model inference latency.

Terra cost is a freeze-date API-equivalent normalization, not actual subscription spend.
Jev cost is estimated promotional-credit consumption. Terra marginal billed API spend is
reported separately as zero while within the existing subscription allowance.

Paired bootstrap uses 10,000 samples for primary analysis (or the explicit test override)
and preserves system pairs. Bootstrap seed: """
        + str(seed)
        + ".\n",
        encoding="utf-8",
    )


def _write_summary_markdown(
    path: Path,
    summaries: dict[str, dict[str, Any]],
    bootstrap_rows: list[dict[str, Any]],
) -> None:
    terra = summaries["terra_only"]
    hybrid = summaries["terra_jev"]
    differences = {row["metric"]: row["observed_difference"] for row in bootstrap_rows}
    rows = [
        (
            "Final action accuracy",
            terra["correctness"]["accuracy"],
            hybrid["correctness"]["accuracy"],
            "accuracy",
        ),
        (
            "End-to-end success",
            terra["correctness"]["terminal_success_rate"],
            hybrid["correctness"]["terminal_success_rate"],
            "terminal_success",
        ),
        (
            "Unsafe autonomous action rate",
            terra["correctness"]["unsafe_autonomous_rate"],
            hybrid["correctness"]["unsafe_autonomous_rate"],
            "unsafe_rate",
        ),
        (
            "False escalation rate",
            terra["correctness"]["false_escalation_rate"],
            hybrid["correctness"]["false_escalation_rate"],
            "false_escalation",
        ),
        (
            "Multiclass Brier ↓",
            terra["calibration"]["multiclass_brier"],
            hybrid["calibration"]["multiclass_brier"],
            "brier",
        ),
        (
            "NLL ↓",
            terra["calibration"]["negative_log_likelihood"],
            hybrid["calibration"]["negative_log_likelihood"],
            "nll",
        ),
        ("ECE ↓", terra["calibration"]["ece"], hybrid["calibration"]["ece"], None),
        (
            "≥90% confidence error",
            _high_confidence(terra, "0.9"),
            _high_confidence(hybrid, "0.9"),
            None,
        ),
        (
            "≥95% confidence error",
            _high_confidence(terra, "0.95"),
            _high_confidence(hybrid, "0.95"),
            None,
        ),
        (
            "Decision p50/median latency ↓",
            terra["efficiency"]["decision_latency_p50_ms"],
            hybrid["efficiency"]["decision_latency_p50_ms"],
            "median_latency",
        ),
        (
            "Decision p95 latency ↓",
            terra["efficiency"]["decision_latency_p95_ms"],
            hybrid["efficiency"]["decision_latency_p95_ms"],
            None,
        ),
        (
            "Read tools / case ↓",
            terra["tools"]["mean_model_requested_reads"],
            hybrid["tools"]["mean_model_requested_reads"],
            "tool_calls",
        ),
        (
            "Extra read tools / case ↓",
            terra["tools"]["mean_extra_tools_per_case"],
            hybrid["tools"]["mean_extra_tools_per_case"],
            None,
        ),
        (
            "Persistent failure handling ↑",
            terra["correctness"]["persistent_failure_accuracy"],
            hybrid["correctness"]["persistent_failure_accuracy"],
            None,
        ),
        (
            "Adversarial accuracy ↑",
            terra["correctness"]["adversarial_accuracy"],
            hybrid["correctness"]["adversarial_accuracy"],
            None,
        ),
        ("Repeatability flip rate ↓", None, None, None),
        (
            "Normalized cost / 1k cases ↓",
            terra["efficiency"]["normalized_cost_per_1000_cases_usd"],
            hybrid["efficiency"]["normalized_cost_per_1000_cases_usd"],
            None,
        ),
    ]
    lines = [
        "# FuseBench analysis summary",
        "",
        "| Metric | Terra-only | Terra + Jev | Paired difference |",
        "|---|---:|---:|---:|",
    ]
    for label, terra_value, hybrid_value, difference_key in rows:
        difference = differences.get(difference_key) if difference_key else None
        lines.append(
            f"| {label} | {_fmt(terra_value)} | {_fmt(hybrid_value)} | {_fmt(difference)} |"
        )
    lines.extend(
        [
            "",
            "No single winner score is computed. Interpret effect sizes, confidence "
            "intervals, safety, calibration, automation coverage, latency, and cost together.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _high_confidence(summary: dict[str, Any], key: str) -> float | None:
    metric = summary["calibration"]["high_confidence"].get(key)
    return metric["error_rate"] if metric is not None else None


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
