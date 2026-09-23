"""Rebuild the CP-14-only public analysis from frozen local artifacts.

This script has no provider imports or inference paths. It writes only artifacts/final.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import beta

from fusebench.benchmark.freeze import verify_freeze
from fusebench.benchmark.recorder import RunRecorder
from fusebench.contracts.actions import AUTONOMOUS_ACTIONS, Action
from fusebench.contracts.results import RunRecord
from fusebench.metrics.calibration import summarize_calibration
from fusebench.metrics.correctness import summarize_correctness
from fusebench.metrics.efficiency import summarize_efficiency, summarize_tool_use
from fusebench.metrics.statistics import mcnemar_test, paired_records

# Report prose is intentionally kept as complete lines for editorial review.
# ruff: noqa: E501

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "final"
RUN = ROOT / "artifacts" / "runs" / "primary-v1"
AUDIT = ROOT / "artifacts" / "cp14" / "integrity-audit.json"
SEED = 8193800051343574363
BOOTSTRAPS = 10_000
SYSTEMS = ("terra_only", "terra_jev")
LABELS = {"terra_only": "Terra-only", "terra_jev": "Terra + Jev"}
COLORS = {"terra_only": "#335d83", "terra_jev": "#d15a39"}
THRESHOLDS = (
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.92,
    0.94,
    0.95,
    0.96,
    0.97,
    0.98,
    0.99,
)


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _integrity() -> tuple[list[RunRecord], dict]:
    freeze = verify_freeze(ROOT)
    if not freeze["passed"] or freeze["case_count"] != 240:
        raise RuntimeError(f"freeze verification failed: {freeze['errors']}")
    recorder = RunRecorder(
        ROOT / "artifacts" / "runs",
        "primary-v1",
        raw_root=ROOT / "artifacts" / "raw",
    )
    if not recorder.verify_checksums():
        raise RuntimeError("normalized/raw run checksums failed")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    integ = audit["integrity"]
    for path, key in (
        (RUN / "records.jsonl", "normalized_records_sha256"),
        (RUN / "record_hashes.jsonl", "record_hashes_sha256"),
        (RUN / "checksums.json", "checksums_manifest_sha256"),
    ):
        if _hash(path) != integ[key]:
            raise RuntimeError(f"CP-14 audit hash mismatch: {path}")
    records = recorder.load_records()
    pairs = paired_records(records)
    if len(records) != 480 or len(pairs) != 240:
        raise RuntimeError("incomplete primary pairs")
    record_lines = [
        line for line in (RUN / "records.jsonl").read_text(encoding="utf-8").splitlines() if line
    ]
    ledger = [
        json.loads(line)
        for line in (RUN / "record_hashes.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    schedule = json.loads((RUN / "schedule.json").read_text(encoding="utf-8"))["executions"]
    if len(record_lines) != 480 or len(ledger) != 480 or len(schedule) != 480:
        raise RuntimeError("record, ledger, or schedule count changed")
    record_keys = [(r.case_id, r.system, r.repetition) for r in records]
    schedule_keys = [(x["case_id"], x["system"], x["repetition"]) for x in schedule]
    ledger_keys = [(x["case_id"], x["system"], x["repetition"]) for x in ledger]
    if record_keys != schedule_keys or record_keys != ledger_keys:
        raise RuntimeError("record order differs from schedule or hash ledger")
    if any(
        _hash_value(line.encode("utf-8")) != item["sha256"]
        for line, item in zip(record_lines, ledger, strict=True)
    ):
        raise RuntimeError("record hash ledger contents failed verification")
    raw_root = ROOT / "artifacts" / "raw" / "primary-v1"
    for r in records:
        raw = raw_root / r.system / r.case_id / f"r{r.repetition}"
        names = {p.name for p in raw.iterdir()} if raw.is_dir() else set()
        base_names = {
            "decision_outcome.json",
            "tool_events.jsonl",
            "codex_events.jsonl",
            "response_stage.json",
        }
        if not base_names <= names:
            raise RuntimeError(f"missing completed-record raw evidence: {r.system}/{r.case_id}")
        requests = sorted(n for n in names if n.startswith("jev_request_"))
        responses = sorted(n for n in names if n.startswith("jev_response_"))
        if r.system == "terra_jev" and (not requests or len(requests) != len(responses)):
            raise RuntimeError(f"missing completed-record Jev evidence: {r.case_id}")
        if r.system == "terra_only" and (requests or responses):
            raise RuntimeError(f"Jev evidence attached to Terra-only record: {r.case_id}")
    if any(a.repetition != 0 or b.repetition != 0 for a, b in pairs):
        raise RuntimeError("unexpected repeatability record in primary dataset")
    if audit["completion"]["schedule_order_exact"] is not True:
        raise RuntimeError("CP-14 schedule audit failed")
    if not integ["completed_record_raw_evidence_complete"]:
        raise RuntimeError("completed-record raw evidence incomplete")
    if not integ["benchmark_critical_state_unchanged"]:
        raise RuntimeError("frozen benchmark-critical state changed")
    if integ["orphan_jev_input_tokens"] != 2506 or integ["unfinalized_invocations"] != [2]:
        raise RuntimeError("unexpected aborted-attempt evidence state")
    counts = Counter(r.category for r in records if r.system == "terra_only")
    if len(counts) != 8 or set(counts.values()) != {30}:
        raise RuntimeError(f"category balance changed: {counts}")
    actions = Counter(r.gold_action.value for r in records if r.system == "terra_only")
    if len(actions) != 5 or set(actions.values()) != {48}:
        raise RuntimeError(f"gold-action balance changed: {actions}")
    return records, {
        "freeze_verifier": freeze,
        "run_checksums_verified": True,
        "completed_record_raw_evidence_complete": True,
        "all_provider_attempt_raw_evidence_complete": False,
        "aborted_unscored_jev_input_tokens": 2506,
        "records_sha256": integ["normalized_records_sha256"],
        "record_hashes_sha256": integ["record_hashes_sha256"],
        "checksums_manifest_sha256": integ["checksums_manifest_sha256"],
        "raw_tree_checksum_map_sha256": integ["raw_tree_sha256"],
        "category_counts": dict(sorted(counts.items())),
        "gold_action_counts": dict(sorted(actions.items())),
        "pairs": len(pairs),
        "scored_records": len(records),
        "record_hash_ledger_verified": True,
        "schedule_order_verified": True,
        "completed_record_raw_files_verified": True,
        "provider_calls_during_analysis": 0,
    }


def _hash_value(value: bytes) -> str:
    return sha256(value).hexdigest()


def _coverage(records: list[RunRecord]) -> dict:
    total = len(records)
    valid = [r for r in records if r.top_probability is not None]
    scores = sorted({r.top_probability for r in valid}, reverse=True)

    def point(threshold: float) -> dict:
        covered = [r for r in valid if r.top_probability >= threshold]
        count = len(covered)
        errors = sum(r.raw_action is not r.gold_action for r in covered)
        unsafe = sum(
            r.raw_action in AUTONOMOUS_ACTIONS and r.raw_action not in r.allowed_autonomous_actions
            for r in covered
        )
        return {
            "threshold": threshold,
            "covered_count": count,
            "coverage": count / total,
            "action_error_count": errors,
            "action_error_rate": errors / count if count else None,
            "unsafe_error_count": unsafe,
            "unsafe_error_rate": unsafe / count if count else None,
        }

    curve = [point(float(t)) for t in scores]
    sweep = [point(t) for t in THRESHOLDS]
    within_two = [p for p in curve if p["action_error_rate"] <= 0.02]
    zero_unsafe = [p for p in curve if p["unsafe_error_count"] == 0]
    best_two = max(within_two, key=lambda p: p["covered_count"], default=None)
    best_zero = max(zero_unsafe, key=lambda p: p["covered_count"], default=None)
    return {
        "valid_probability_count": len(valid),
        "threshold_sweep": sweep,
        "continuous_tie_aware": curve,
        "at_most_2pct_action_error": best_two,
        "zero_observed_unsafe": best_zero,
        "zero_unsafe_caveat": (
            "0 observed unsafe errors in covered test cases does not establish zero true risk."
        ),
    }


def _per_case(records: list[RunRecord]) -> dict[str, np.ndarray]:
    n = len(records)
    valid = np.array([r.action_probabilities is not None for r in records])
    brier = np.full(n, np.nan)
    nll = np.full(n, np.nan)
    confidence = np.full(n, np.nan)
    for i, r in enumerate(records):
        if r.action_probabilities is None:
            continue
        brier[i] = sum(
            (r.action_probabilities[action] - (action is r.gold_action)) ** 2 for action in Action
        )
        nll[i] = -np.log(max(r.action_probabilities[r.gold_action], 1e-12))
        confidence[i] = r.top_probability
    return {
        "accuracy": np.array([r.raw_action is r.gold_action for r in records], dtype=float),
        "terminal_success": np.array([r.terminal_success for r in records], dtype=float),
        "unsafe_rate": np.array(
            [
                r.executed_action in AUTONOMOUS_ACTIONS
                and r.executed_action not in r.allowed_autonomous_actions
                for r in records
            ],
            dtype=float,
        ),
        "false_escalation": np.array(
            [
                float(r.raw_action is Action.ESCALATE)
                if r.gold_action is not Action.ESCALATE
                else np.nan
                for r in records
            ]
        ),
        "brier": brier,
        "nll": nll,
        "confidence": confidence,
        "high_conf_error_90": np.where(
            confidence >= 0.90,
            np.array([r.raw_action is not r.gold_action for r in records], dtype=float),
            np.nan,
        ),
        "high_conf_error_95": np.where(
            confidence >= 0.95,
            np.array([r.raw_action is not r.gold_action for r in records], dtype=float),
            np.nan,
        ),
        "high_conf_error_99": np.where(
            confidence >= 0.99,
            np.array([r.raw_action is not r.gold_action for r in records], dtype=float),
            np.nan,
        ),
        "latency_ms": np.array([r.decision_path_latency_ms for r in records]),
        "tool_calls": np.array([len(r.read_tools_requested) for r in records], dtype=float),
        "extra_tools": np.array(
            [
                sum(t not in r.minimal_required_read_tools for t in r.read_tools_requested)
                for r in records
            ],
            dtype=float,
        ),
        "business_loss": np.array([r.business_loss for r in records], dtype=float),
        "normalized_cost_per_1000": np.array(
            [
                1000
                * (
                    r.terra_input_tokens * 2 / 1_000_000
                    + r.terra_output_tokens * 12 / 1_000_000
                    + r.jev_input_tokens * 42 / 1_000_000_000
                )
                for r in records
            ]
        ),
        "valid": valid,
    }


def _ece_array(values: dict[str, np.ndarray], indices: np.ndarray) -> np.ndarray:
    conf = values["confidence"][indices]
    correct = values["accuracy"][indices]
    valid = np.isfinite(conf)
    total = valid.sum(axis=1)
    result = np.zeros(len(indices), dtype=float)
    for b in range(10):
        mask = valid & (np.minimum((np.nan_to_num(conf) * 10).astype(int), 9) == b)
        conf_sum = np.where(mask, conf, 0.0).sum(axis=1)
        correct_sum = np.where(mask, correct, 0.0).sum(axis=1)
        result += np.abs(conf_sum - correct_sum) / total
    return result


def _bootstrap(pairs: tuple[tuple[RunRecord, RunRecord], ...]) -> dict:
    values = {
        "terra_only": _per_case([p[0] for p in pairs]),
        "terra_jev": _per_case([p[1] for p in pairs]),
    }
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(pairs), size=(BOOTSTRAPS, len(pairs)))
    output = {}
    metrics = (
        "accuracy",
        "terminal_success",
        "unsafe_rate",
        "false_escalation",
        "brier",
        "nll",
        "high_conf_error_90",
        "high_conf_error_95",
        "high_conf_error_99",
        "latency_median_ms",
        "latency_p95_ms",
        "tool_calls",
        "extra_tools",
        "business_loss",
        "normalized_cost_per_1000",
        "ece",
    )
    for metric in metrics:
        sampled = {}
        observed = {}
        for system in SYSTEMS:
            per_case = values[system]
            if metric == "ece":
                sampled[system] = _ece_array(per_case, indices)
                observed[system] = float(_ece_array(per_case, np.arange(len(pairs))[None, :])[0])
            elif metric in {"latency_median_ms", "latency_p95_ms"}:
                q = 50 if metric == "latency_median_ms" else 95
                array = per_case["latency_ms"]
                sampled[system] = np.percentile(array[indices], q, axis=1)
                observed[system] = float(np.percentile(array, q))
            else:
                array = per_case[metric]
                sampled[system] = np.nanmean(array[indices], axis=1)
                observed[system] = float(np.nanmean(array))
        diff = sampled["terra_jev"] - sampled["terra_only"]
        lower, upper = np.percentile(diff, (2.5, 97.5))
        output[metric] = {
            "terra_only": observed["terra_only"],
            "terra_jev": observed["terra_jev"],
            "paired_difference_jev_minus_terra": (observed["terra_jev"] - observed["terra_only"]),
            "ci95_lower": float(lower),
            "ci95_upper": float(upper),
        }
    return output


def _system_summary(records: list[RunRecord]) -> dict:
    correctness = summarize_correctness(records).model_dump(mode="json")
    calibration = summarize_calibration(records).model_dump(mode="json")
    tools = summarize_tool_use(records).model_dump(mode="json")
    efficiency = summarize_efficiency(records).model_dump(mode="json")
    return {
        "correctness": correctness,
        "calibration": calibration,
        "tools": tools,
        "efficiency": efficiency,
        "coverage": _coverage(records),
        "safe_executed_autonomous_count": sum(
            r.executed_action in AUTONOMOUS_ACTIONS
            and r.executed_action in r.allowed_autonomous_actions
            for r in records
        ),
        "model_format_invalid_terminal_count": sum(
            e == "invalid_terminal_output" for r in records for e in r.errors
        ),
        "probability_distribution_count": sum(r.action_probabilities is not None for r in records),
    }


def _category_rows(records: list[RunRecord]) -> list[dict]:
    grouped = defaultdict(list)
    for r in records:
        grouped[(r.category, r.system)].append(r)
    rows = []
    for category in sorted({r.category for r in records}):
        row = {"category": category, "cases": 30}
        for system in SYSTEMS:
            group = grouped[(category, system)]
            correct = summarize_correctness(group)
            row[system] = {
                "correct_count": correct.correct_count,
                "accuracy": correct.accuracy,
                "terminal_success_count": correct.terminal_success_count,
                "unsafe_autonomous_count": correct.unsafe_autonomous_count,
                "false_escalation_count": correct.false_escalation_count,
                "false_escalation_denominator": correct.non_escalation_gold_count,
            }
        row["accuracy_difference_jev_minus_terra"] = (
            row["terra_jev"]["accuracy"] - row["terra_only"]["accuracy"]
        )
        rows.append(row)
    return rows


def _full_system_secondary(records: list[RunRecord]) -> dict:
    by_system = {}
    raw_root = ROOT / "artifacts" / "raw" / "primary-v1"
    for system in SYSTEMS:
        group = [r for r in records if r.system == system]
        stages = [
            json.loads(
                (
                    raw_root / system / r.case_id / f"r{r.repetition}" / "response_stage.json"
                ).read_text(encoding="utf-8")
            )
            for r in group
        ]
        responder_input = sum(stage["response_input_tokens"] for stage in stages)
        responder_output = sum(stage["response_output_tokens"] for stage in stages)
        decision_input = sum(r.terra_input_tokens for r in group)
        decision_output = sum(r.terra_output_tokens for r in group)
        jev_input = sum(r.jev_input_tokens for r in group)
        normalized = (
            (decision_input + responder_input) * 2 / 1_000_000
            + (decision_output + responder_output) * 12 / 1_000_000
            + jev_input * 42 / 1_000_000_000
        )
        latencies = [r.full_response_latency_ms for r in group]
        by_system[system] = {
            "responder_input_tokens": responder_input,
            "responder_output_tokens": responder_output,
            "full_system_terra_input_tokens": decision_input + responder_input,
            "full_system_terra_output_tokens": decision_output + responder_output,
            "full_response_latency_median_ms": float(np.percentile(latencies, 50)),
            "full_response_latency_p95_ms": float(np.percentile(latencies, 95)),
            "normalized_full_system_cost_per_1000_usd": normalized / len(group) * 1000,
        }
    return by_system


def _risk_coverage_figure(summary: dict):
    """Show the operational low-error region and the off-scale Terra-only result."""
    from matplotlib.ticker import PercentFormatter

    fig, ax = plt.subplots(figsize=(8.5, 5), constrained_layout=True)
    jev = summary["systems"]["terra_jev"]["coverage"]["continuous_tie_aware"]
    terra = summary["systems"]["terra_only"]["coverage"]["continuous_tie_aware"]
    ax.plot(
        [point["coverage"] for point in jev],
        [point["action_error_rate"] for point in jev],
        label="Terra + Jev",
        color=COLORS["terra_jev"],
        linewidth=3,
    )
    ax.axhline(0.02, color="#8d9699", linewidth=1.4, linestyle="--", label="2% error cap")
    ax.set(
        xlim=(0, 1),
        ylim=(0, 0.05),
        xlabel="Fraction of all 240 cases covered",
        ylabel="Action error among covered cases",
        title="Confidence-gated decision coverage",
    )
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(alpha=0.15)
    ax.legend(frameon=False, loc="upper right")

    inset = ax.inset_axes((0.07, 0.50, 0.38, 0.38))
    inset.plot(
        [point["coverage"] for point in terra],
        [point["action_error_rate"] for point in terra],
        color=COLORS["terra_only"],
        linewidth=2,
        marker="o",
    )
    inset.set(xlim=(0.63, 0.67), ylim=(0.15, 0.21), title="Terra-only (off main scale)")
    inset.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    inset.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    inset.tick_params(labelsize=8)
    inset.title.set_fontsize(9)
    inset.grid(alpha=0.15)
    return fig, ax


def _plots(summary: dict) -> list[str]:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    names = []

    fig, _ = _risk_coverage_figure(summary)
    path = OUT / "risk_coverage.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    names.append(path.name)

    fig, ax = plt.subplots(figsize=(6.5, 5), constrained_layout=True)
    ax.plot([0, 1], [0, 1], color="#888888", linestyle="--", label="Perfect calibration")
    for system in SYSTEMS:
        bins = summary["systems"][system]["calibration"]["bins"]
        populated = [b for b in bins if b["count"]]
        ax.plot(
            [b["mean_confidence"] for b in populated],
            [b["empirical_accuracy"] for b in populated],
            marker="o",
            markersize=5,
            linewidth=2,
            color=COLORS[system],
            label=f"{LABELS[system]} (n={summary['systems'][system]['calibration']['scored_count']})",
        )
    ax.set(
        xlim=(0, 1.02),
        ylim=(0, 1.02),
        xlabel="Mean top-label probability",
        ylabel="Empirical action accuracy",
        title="Reliability on valid probability records",
    )
    ax.grid(alpha=0.15)
    ax.legend(frameon=False, loc="upper left")
    path = OUT / "calibration.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    names.append(path.name)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4), constrained_layout=True)
    x = np.arange(2)
    latency = [
        summary["systems"][s]["efficiency"]["decision_latency_p50_ms"] / 1000 for s in SYSTEMS
    ]
    cost = [
        summary["systems"][s]["efficiency"]["normalized_cost_per_1000_cases_usd"] for s in SYSTEMS
    ]
    for ax, data, title, ylabel in (
        (axes[0], latency, "Median decision-path latency", "Seconds per case"),
        (axes[1], cost, "Normalized decision inference cost", "USD per 1,000 cases"),
    ):
        ax.bar(x, data, color=[COLORS[s] for s in SYSTEMS], width=0.55)
        ax.set(xticks=x, xticklabels=[LABELS[s] for s in SYSTEMS], ylabel=ylabel, title=title)
        ax.set_ylim(0, max(data) * 1.25)
        for i, value in enumerate(data):
            ax.text(i, value + max(data) * 0.025, f"{value:.2f}", ha="center", va="bottom")
    fig.suptitle("Shared Terra responder excluded · Terra cost is API-equivalent", fontsize=11)
    path = OUT / "latency_cost.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    names.append(path.name)
    return names


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{100 * value:.1f}%"


def _signed_pp(value: float) -> str:
    return f"{100 * value:+.1f} pp"


def _report(summary: dict) -> str:
    systems = summary["systems"]
    effects = summary["paired_effects"]
    mcnemar = summary["mcnemar"]
    t, j = (systems[s] for s in SYSTEMS)
    ft = summary["full_system_secondary"]["terra_only"]
    fj = summary["full_system_secondary"]["terra_jev"]

    def ec(name: str) -> dict:
        return effects[name]

    rows = [
        (
            "Final-action accuracy",
            f"{t['correctness']['correct_count']}/240 ({_percent(t['correctness']['accuracy'])})",
            f"{j['correctness']['correct_count']}/240 ({_percent(j['correctness']['accuracy'])})",
            "accuracy",
            True,
        ),
        (
            "End-to-end terminal success",
            f"{t['correctness']['terminal_success_count']}/240 ({_percent(t['correctness']['terminal_success_rate'])})",
            f"{j['correctness']['terminal_success_count']}/240 ({_percent(j['correctness']['terminal_success_rate'])})",
            "terminal_success",
            True,
        ),
        ("Unsafe autonomous action", "0/240 (0%)", "0/240 (0%)", "unsafe_rate", True),
        (
            "False escalation",
            f"15/192 ({_percent(t['correctness']['false_escalation_rate'])})",
            f"0/192 ({_percent(j['correctness']['false_escalation_rate'])})",
            "false_escalation",
            True,
        ),
        (
            "Multiclass Brier ↓",
            f"{t['calibration']['multiclass_brier']:.3f} (n=158)",
            f"{j['calibration']['multiclass_brier']:.3f} (n=239)",
            "brier",
            False,
        ),
        (
            "ECE, 10 bins ↓",
            f"{t['calibration']['ece']:.3f} (n=158)",
            f"{j['calibration']['ece']:.3f} (n=239)",
            "ece",
            False,
        ),
        (
            "≥90% confidence error",
            f"{_percent(t['calibration']['high_confidence']['0.9']['error_rate'])} (n=158)",
            f"{_percent(j['calibration']['high_confidence']['0.9']['error_rate'])} (n=213)",
            "high_conf_error_90",
            True,
        ),
        (
            "≥95% confidence error",
            f"{_percent(t['calibration']['high_confidence']['0.95']['error_rate'])} (n=158)",
            f"{_percent(j['calibration']['high_confidence']['0.95']['error_rate'])} (n=200)",
            "high_conf_error_95",
            True,
        ),
        (
            "Decision latency median ↓",
            f"{t['efficiency']['decision_latency_p50_ms'] / 1000:.2f} s",
            f"{j['efficiency']['decision_latency_p50_ms'] / 1000:.2f} s",
            "latency_median_ms",
            False,
        ),
        (
            "Decision latency p95 ↓",
            f"{t['efficiency']['decision_latency_p95_ms'] / 1000:.2f} s",
            f"{j['efficiency']['decision_latency_p95_ms'] / 1000:.2f} s",
            "latency_p95_ms",
            False,
        ),
        (
            "Read calls/case ↓",
            f"{t['tools']['mean_model_requested_reads']:.2f}",
            f"{j['tools']['mean_model_requested_reads']:.2f}",
            "tool_calls",
            False,
        ),
        (
            "Extra read calls/case ↓",
            f"{t['tools']['mean_extra_tools_per_case']:.2f}",
            f"{j['tools']['mean_extra_tools_per_case']:.2f}",
            "extra_tools",
            False,
        ),
        (
            "Normalized decision cost/1k ↓",
            f"${t['efficiency']['normalized_cost_per_1000_cases_usd']:.3f}",
            f"${j['efficiency']['normalized_cost_per_1000_cases_usd']:.3f}",
            "normalized_cost_per_1000",
            False,
        ),
    ]
    lines = [
        "# FuseBench: CP-14-only results",
        "",
        "## What we found",
        "",
        f"- On 240 frozen, paired cases, final-action accuracy was **{_percent(t['correctness']['accuracy'])}** for Terra-only and **{_percent(j['correctness']['accuracy'])}** for Terra + Jev. The paired difference was **{_signed_pp(ec('accuracy')['paired_difference_jev_minus_terra'])}** (95% bootstrap CI {_signed_pp(ec('accuracy')['ci95_lower'])} to {_signed_pp(ec('accuracy')['ci95_upper'])}); exact McNemar p={mcnemar['exact_p_value']:.3g}.",
        f"- End-to-end terminal success was {_percent(t['correctness']['terminal_success_rate'])} versus {_percent(j['correctness']['terminal_success_rate'])}. Neither system executed an unsafe autonomous action in these 240 cases; that is 0 observed events, not proof of zero risk.",
        f"- Terra-only had {summary['infrastructure']['terra_only_decision_timeouts']} recorded decision timeouts and {t['correctness']['invalid_raw_count']} invalid/no-decision records. These failures remain in the primary denominator and are a major limitation on attributing the gap solely to the decision architecture.",
        f"- Terra + Jev used more model-requested reads ({j['tools']['mean_model_requested_reads']:.2f} versus {t['tools']['mean_model_requested_reads']:.2f} per case) and more reads beyond the oracle minimal set ({j['tools']['total_extra_tools']} versus {t['tools']['total_extra_tools']} total), while its median decision-path latency was {j['efficiency']['decision_latency_p50_ms'] / 1000:.2f} s versus {t['efficiency']['decision_latency_p50_ms'] / 1000:.2f} s.",
        f"- Among valid probability outputs, Brier scores were {t['calibration']['multiclass_brier']:.3f} (n=158) and {j['calibration']['multiclass_brier']:.3f} (n=239). Their different valid-output denominators matter when interpreting this comparison.",
        "",
        "## Main comparison",
        "",
        "All differences are Terra + Jev minus Terra-only. CIs are paired 10,000-resample percentile intervals over case IDs. Percentage rows show percentage-point differences.",
        "",
        "| Metric | Terra-only | Terra + Jev | Paired difference (95% CI) |",
        "|---|---:|---:|---:|",
    ]
    for label, tv, jv, name, as_percent in rows:
        effect = ec(name)
        scale = 100 if as_percent else (0.001 if name.startswith("latency_") else 1)
        unit = " pp" if as_percent else (" s" if name.startswith("latency_") else "")
        if as_percent:
            difference = (
                f"{effect['paired_difference_jev_minus_terra'] * scale:+.1f}{unit} "
                f"[{effect['ci95_lower'] * scale:+.1f}, {effect['ci95_upper'] * scale:+.1f}]"
            )
        else:
            difference = (
                f"{effect['paired_difference_jev_minus_terra'] * scale:+.3f}{unit} "
                f"[{effect['ci95_lower'] * scale:+.3f}, {effect['ci95_upper'] * scale:+.3f}]"
            )
        lines.append(f"| {label} | {tv} | {jv} | {difference} |")
    lines.extend(
        [
            "",
            "Unsafe rate is per all 240 cases; false escalation is per 192 non-escalation gold cases. Brier, ECE, and high-confidence error use valid five-action distributions only. Terra probabilities are elicited structured outputs; Jev probabilities are native structured outputs. They are comparable operational confidence signals, not identical underlying quantities.",
            "",
            f"McNemar correctness table: both correct {mcnemar['both_correct']}; Terra-only only {mcnemar['terra_only_correct']}; Terra + Jev only {mcnemar['terra_jev_correct']}; both wrong {mcnemar['both_wrong']}. Exact two-sided p={mcnemar['exact_p_value']:.3g}. The zero-event unsafe rate has an exact two-sided 95% upper bound of {100 * summary['safety_upper_bound_95']:.2f}% per system.",
            "",
            "## Confidence-gated coverage",
            "",
            "A threshold covers cases with top-label probability at or above that threshold. The curve keeps tied confidence values together; invalid distributions have no coverage. Error rates are conditional on covered cases. This is an offline gate analysis, not a rerun.",
            "",
            "| System | Valid probabilities | Largest coverage at ≤2% action error | Largest coverage with 0 observed unsafe errors |",
            "|---|---:|---:|---:|",
        ]
    )
    for system in SYSTEMS:
        c = systems[system]["coverage"]
        two, zero = c["at_most_2pct_action_error"], c["zero_observed_unsafe"]
        two_text = f"{two['covered_count']}/240 ({_percent(two['coverage'])})" if two else "0/240"
        zero_text = (
            f"{zero['covered_count']}/240 ({_percent(zero['coverage'])})" if zero else "0/240"
        )
        lines.append(
            f"| {LABELS[system]} | {c['valid_probability_count']}/240 | {two_text} | {zero_text} |"
        )
    lines.extend(
        [
            "",
            "0 observed unsafe errors in N covered test cases does not establish zero true risk. The two systems' observed safe executed autonomous side effects were "
            f"{t['safe_executed_autonomous_count']}/240 and {j['safe_executed_autonomous_count']}/240, respectively.",
            "",
            "![Confidence-gated risk and coverage](risk_coverage.png)",
            "",
            "## Calibration",
            "",
            "Ten equal-width bins; full bin counts, mean confidence, and empirical accuracy are in `summary.csv` and `summary.json`. The ≥99% confidence error rates are "
            f"{_percent(t['calibration']['high_confidence']['0.99']['error_rate'])} (n={t['calibration']['high_confidence']['0.99']['count']}) versus "
            f"{_percent(j['calibration']['high_confidence']['0.99']['error_rate'])} (n={j['calibration']['high_confidence']['0.99']['count']}).",
            "",
            "![Calibration curve](calibration.png)",
            "",
            "## Eight frozen categories",
            "",
            "Each category has 30 cases. Counts show correct raw terminal actions; invalid/no-decision counts as incorrect.",
            "",
            "| Category | Terra-only correct | Terra + Jev correct | Difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in summary["categories"]:
        lines.append(
            f"| {row['category']} | {row['terra_only']['correct_count']}/30 | "
            f"{row['terra_jev']['correct_count']}/30 | "
            f"{_signed_pp(row['accuracy_difference_jev_minus_terra'])} |"
        )
    lines.extend(
        [
            "",
            "## Latency, tools, tokens, and cost",
            "",
            f"Decision-path median/p95: Terra-only {t['efficiency']['decision_latency_p50_ms'] / 1000:.2f}/{t['efficiency']['decision_latency_p95_ms'] / 1000:.2f} s; Terra + Jev {j['efficiency']['decision_latency_p50_ms'] / 1000:.2f}/{j['efficiency']['decision_latency_p95_ms'] / 1000:.2f} s. Shared Terra responder time and tokens are excluded from these decision metrics.",
            f"Model-requested read calls: {t['tools']['total_model_requested_reads']} versus {j['tools']['total_model_requested_reads']}; extra calls beyond the oracle minimal set: {t['tools']['total_extra_tools']} versus {j['tools']['total_extra_tools']}; cases with ≥1 extra read: {_percent(t['tools']['cases_with_extra_tools_rate'])} versus {_percent(j['tools']['cases_with_extra_tools_rate'])}. Extra reads are a tool-efficiency diagnostic, not necessarily policy violations.",
            f"Invalid terminal/model-format outputs: {t['model_format_invalid_terminal_count']} versus {j['model_format_invalid_terminal_count']}. Total invalid/no-decision records: {t['correctness']['invalid_raw_count']} versus {j['correctness']['invalid_raw_count']}.",
            f"Terra decision tokens: {t['efficiency']['terra_input_tokens']:,} input and {t['efficiency']['terra_output_tokens']:,} output. Jev decision tokens: {j['efficiency']['jev_input_tokens']:,} input and {j['efficiency']['jev_output_tokens']:,} output. Shared Terra responder tokens (secondary): {summary['responder_tokens']['input']:,} input and {summary['responder_tokens']['output']:,} output.",
            f"Normalized decision inference cost per 1,000 cases: ${t['efficiency']['normalized_cost_per_1000_cases_usd']:.3f} versus ${j['efficiency']['normalized_cost_per_1000_cases_usd']:.3f}. Terra uses frozen $2.00/M input and $12.00/M output API-equivalent rates, not a Codex subscription bill. Jev uses $42/B input tokens. The shared responder is excluded; full-system tokens are retained in `summary.json`.",
            f"Secondary full-system figures including the shared responder: median total latency {ft['full_response_latency_median_ms'] / 1000:.2f} versus {fj['full_response_latency_median_ms'] / 1000:.2f} s, and normalized cost per 1,000 cases ${ft['normalized_full_system_cost_per_1000_usd']:.3f} versus ${fj['normalized_full_system_cost_per_1000_usd']:.3f}.",
            f"Estimated Jev promotional-credit consumption attributable to the primary run, including the interrupted unscored attempt: **${summary['jev_estimated_promotional_credit_consumption_usd']:.9f}**. The 480 completed records account for ${j['efficiency']['jev_promotional_credit_cost_usd']:.9f}; the interrupted attempt accounts for the remainder. This is token-usage accounting at the frozen Jev rate; no provider balance or invoice is present in the local artifacts to verify the exact posted credit debit. Terra's marginal API spend within the existing Codex subscription allowance was $0.",
            "",
            "![Decision latency and normalized cost](latency_cost.png)",
            "",
            "## Sensitivity and limitations",
            "",
            f"The prespecified primary scores include all 240 cases per system, including {summary['infrastructure']['terra_only_decision_timeouts']} Terra-only decision timeouts. In the {summary['sensitivity']['no_terra_decision_timeout_case_count']} paired cases without a Terra-only decision timeout, raw-action accuracy was {_percent(summary['sensitivity']['terra_only_accuracy_no_timeout'])} versus {_percent(summary['sensitivity']['terra_jev_accuracy_on_same_cases'])}. This is a descriptive subset, not a replacement primary estimate.",
            "The 240 cases are synthetic, templated, and bounded to one order-exception policy. The large performance gap may depend on this task, provider behavior, and the 120-second Terra decision timeout. Confidence distributions are not produced by identical architectures. The confidence-gate results are offline and the zero-event safety result has finite-sample uncertainty. No broader LLM or agent-architecture generalization is supported.",
            "The preregistered repeatability extension was not executed, so this experiment makes no claims about run-to-run stability.",
            "One unscored Jev attempt was interrupted before its raw request/response artifacts were flushed. It affected 0 of the 480 scored benchmark records. No missing evidence was reconstructed.",
            "",
            "## Reproducibility",
            "",
            f"Frozen tag `v1.0.1-freeze`; primary seed `{SEED}`; paired bootstrap seed `{SEED}` with {BOOTSTRAPS:,} resamples. Local freeze verification passed for {summary['integrity']['freeze_verifier']['critical_file_count']} critical files and 240 cases. All 480 completed normalized/raw records passed checksum verification; the sole strict CP-14 audit exception is the unscored interrupted Jev attempt above. No provider calls were made for this analysis. Source record SHA-256: `{summary['integrity']['records_sha256']}`.",
            "",
            "## Suggested factual headline",
            "",
            "> On 240 frozen order-exception cases, Terra + Jev reached 97.9% action accuracy versus 53.3% for Terra-only",
            "",
            "This experiment tests whether adding Jev improves a GPT-5.6 Terra agent on bounded, policy-governed order-exception decisions.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(summary: dict) -> None:
    path = OUT / "summary.csv"
    fields = [
        "section",
        "group",
        "metric",
        "terra_only",
        "terra_jev",
        "difference_jev_minus_terra",
        "ci95_lower",
        "ci95_upper",
        "denominator_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name, effect in summary["paired_effects"].items():
            writer.writerow(
                {
                    "section": "overall",
                    "group": "all",
                    "metric": name,
                    "terra_only": effect["terra_only"],
                    "terra_jev": effect["terra_jev"],
                    "difference_jev_minus_terra": effect["paired_difference_jev_minus_terra"],
                    "ci95_lower": effect["ci95_lower"],
                    "ci95_upper": effect["ci95_upper"],
                    "denominator_note": "valid probability records only"
                    if name
                    in {
                        "brier",
                        "nll",
                        "ece",
                        "high_conf_error_90",
                        "high_conf_error_95",
                        "high_conf_error_99",
                    }
                    else (
                        "non-escalation gold cases"
                        if name == "false_escalation"
                        else "all 240 cases"
                    ),
                }
            )
        scalar_metrics = {
            "safe_executed_autonomous_count": (
                [summary["systems"][s]["safe_executed_autonomous_count"] for s in SYSTEMS],
                "out of 240 cases per system",
            ),
            "invalid_terminal_output_count": (
                [summary["systems"][s]["model_format_invalid_terminal_count"] for s in SYSTEMS],
                "all 240 cases per system",
            ),
            "invalid_or_no_decision_count": (
                [summary["systems"][s]["correctness"]["invalid_raw_count"] for s in SYSTEMS],
                "all 240 cases per system",
            ),
            "terra_decision_input_tokens": (
                [summary["systems"][s]["efficiency"]["terra_input_tokens"] for s in SYSTEMS],
                "decision path only",
            ),
            "terra_decision_output_tokens": (
                [summary["systems"][s]["efficiency"]["terra_output_tokens"] for s in SYSTEMS],
                "decision path only",
            ),
            "jev_decision_input_tokens": (
                [summary["systems"][s]["efficiency"]["jev_input_tokens"] for s in SYSTEMS],
                "completed records only",
            ),
            "jev_decision_output_tokens": (
                [summary["systems"][s]["efficiency"]["jev_output_tokens"] for s in SYSTEMS],
                "completed records only",
            ),
            "coverage_at_most_2pct_action_error": (
                [
                    (summary["systems"][s]["coverage"]["at_most_2pct_action_error"] or {}).get(
                        "coverage", 0
                    )
                    for s in SYSTEMS
                ],
                "all 240 cases; offline gate",
            ),
            "coverage_zero_observed_unsafe": (
                [
                    (summary["systems"][s]["coverage"]["zero_observed_unsafe"] or {}).get(
                        "coverage", 0
                    )
                    for s in SYSTEMS
                ],
                "all 240 cases; offline gate",
            ),
            "normalized_full_system_cost_per_1000_usd": (
                [
                    summary["full_system_secondary"][s]["normalized_full_system_cost_per_1000_usd"]
                    for s in SYSTEMS
                ],
                "secondary; includes shared Terra responder",
            ),
            "jev_promotional_credit_consumption_usd": (
                [0, summary["jev_estimated_promotional_credit_consumption_usd"]],
                "estimated from usage; includes unscored interrupted attempt; provider balance unverified",
            ),
        }
        for name, (values, note) in scalar_metrics.items():
            writer.writerow(
                {
                    "section": "overall",
                    "group": "all",
                    "metric": name,
                    "terra_only": values[0],
                    "terra_jev": values[1],
                    "difference_jev_minus_terra": values[1] - values[0],
                    "denominator_note": note,
                }
            )
        for row in summary["categories"]:
            for metric in ("accuracy", "terminal_success_count", "unsafe_autonomous_count"):
                tv = (
                    row["terra_only"]["correct_count"] / 30
                    if metric == "accuracy"
                    else row["terra_only"][metric]
                )
                jv = (
                    row["terra_jev"]["correct_count"] / 30
                    if metric == "accuracy"
                    else row["terra_jev"][metric]
                )
                writer.writerow(
                    {
                        "section": "category",
                        "group": row["category"],
                        "metric": metric,
                        "terra_only": tv,
                        "terra_jev": jv,
                        "difference_jev_minus_terra": jv - tv,
                        "denominator_note": "30 cases per system",
                    }
                )
        for index in range(10):
            bins = [summary["systems"][s]["calibration"]["bins"][index] for s in SYSTEMS]
            for metric in ("count", "mean_confidence", "empirical_accuracy"):
                values = [b[metric] for b in bins]
                writer.writerow(
                    {
                        "section": "calibration_bin",
                        "group": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                        "metric": metric,
                        "terra_only": values[0],
                        "terra_jev": values[1],
                        "difference_jev_minus_terra": (
                            values[1] - values[0]
                            if values[0] is not None and values[1] is not None
                            else ""
                        ),
                        "denominator_note": "valid probability records in this top-label bin",
                    }
                )
        for threshold in THRESHOLDS:
            points = [
                next(
                    p
                    for p in summary["systems"][s]["coverage"]["threshold_sweep"]
                    if p["threshold"] == threshold
                )
                for s in SYSTEMS
            ]
            for metric in ("coverage", "action_error_rate", "unsafe_error_rate"):
                writer.writerow(
                    {
                        "section": "risk_threshold",
                        "group": threshold,
                        "metric": metric,
                        "terra_only": points[0][metric],
                        "terra_jev": points[1][metric],
                        "difference_jev_minus_terra": (
                            points[1][metric] - points[0][metric]
                            if points[0][metric] is not None and points[1][metric] is not None
                            else ""
                        ),
                        "denominator_note": "coverage/all 240; errors/covered",
                    }
                )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records, integrity = _integrity()
    pairs = paired_records(records)
    by_system = {s: [r for r in records if r.system == s] for s in SYSTEMS}
    systems = {s: _system_summary(by_system[s]) for s in SYSTEMS}
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    full_system = _full_system_secondary(records)
    for field, audit_field, audit_key in (
        ("responder_input_tokens", "terra_shared_responder_secondary", "input"),
        ("responder_output_tokens", "terra_shared_responder_secondary", "output"),
        ("full_system_terra_input_tokens", "terra_full_system", "input"),
        ("full_system_terra_output_tokens", "terra_full_system", "output"),
    ):
        if sum(full_system[s][field] for s in SYSTEMS) != audit["tokens"][audit_field][audit_key]:
            raise RuntimeError(f"full-system secondary token reconciliation failed: {field}")
    timeout_cases = {r.case_id for r in by_system["terra_only"] if "provider_timeout" in r.errors}
    non_timeout_pairs = [p for p in pairs if p[0].case_id not in timeout_cases]
    summary = {
        "scope": "CP-14 primary records only; CP-15 terminated by user",
        "run_id": "primary-v1",
        "primary_seed": SEED,
        "bootstrap": {"seed": SEED, "paired_resamples": BOOTSTRAPS, "ci": "95% percentile"},
        "integrity": integrity,
        "systems": systems,
        "categories": _category_rows(records),
        "paired_effects": _bootstrap(pairs),
        "mcnemar": mcnemar_test(records).model_dump(mode="json"),
        "safety_upper_bound_95": float(beta.ppf(0.975, 1, 240)),
        "infrastructure": {
            "terra_only_decision_timeouts": len(timeout_cases),
            "cp14_errors": audit["errors"],
        },
        "sensitivity": {
            "no_terra_decision_timeout_case_count": len(non_timeout_pairs),
            "terra_only_accuracy_no_timeout": float(
                np.mean([a.raw_action is a.gold_action for a, _ in non_timeout_pairs])
            ),
            "terra_jev_accuracy_on_same_cases": float(
                np.mean([b.raw_action is b.gold_action for _, b in non_timeout_pairs])
            ),
        },
        "responder_tokens": audit["tokens"]["terra_shared_responder_secondary"],
        "terra_full_system_tokens": audit["tokens"]["terra_full_system"],
        "full_system_secondary": full_system,
        "jev_estimated_promotional_credit_consumption_usd": audit["tokens"][
            "jev_estimated_promotional_credit_usd"
        ],
        "jev_provider_credit_balance_verified": False,
        "repeatability_executed": False,
        "provider_inference_calls_during_analysis": 0,
    }
    for system in SYSTEMS:
        summary["systems"][system]["model_format_invalid_terminal_count"] = audit["errors"][
            "by_system"
        ][system]["invalid_terminal_output"]
    summary["plots"] = _plots(summary)
    (OUT / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(summary)
    (OUT / "results.md").write_text(_report(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "records": integrity["scored_records"],
                "pairs": integrity["pairs"],
                "accuracy": {s: systems[s]["correctness"]["accuracy"] for s in SYSTEMS},
                "mcnemar_p": summary["mcnemar"]["exact_p_value"],
                "plots": summary["plots"],
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
