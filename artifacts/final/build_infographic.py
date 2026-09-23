"""Build the CP-14 poster from verified local results, without provider access.

Run in order:
  uv run python artifacts/final/build_infographic.py data
  uv run python artifacts/final/build_infographic.py verify
  uv run python artifacts/final/build_infographic.py render
"""

# Poster copy uses intentional typographic characters and complete editorial lines.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

from fusebench.benchmark.freeze import verify_freeze
from fusebench.benchmark.recorder import RunRecorder

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "final"
DATA_PATH = OUT / "infographic-data.json"
SUMMARY_PATH = OUT / "summary.json"
AUDIT_PATH = ROOT / "artifacts" / "cp14" / "integrity-audit.json"
W, H = 1600, 2000

INK = "#17262e"
MUTED = "#52636a"
PAPER = "#f7f5ef"
WHITE = "#fffefa"
RULE = "#d7ded9"
BLUE = "#3f6986"
ORANGE = "#cf613f"
GREEN = "#237568"
GREEN_PALE = "#dcefe8"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _calculate_data() -> dict:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    freeze = verify_freeze(ROOT)
    if not freeze["passed"] or freeze["case_count"] != 240:
        raise RuntimeError("frozen benchmark verification failed")
    recorder = RunRecorder(
        ROOT / "artifacts" / "runs",
        "primary-v1",
        raw_root=ROOT / "artifacts" / "raw",
    )
    if not recorder.verify_checksums():
        raise RuntimeError("CP-14 normalized/raw checksum verification failed")
    records = recorder.load_records()
    if len(records) != 480 or summary["integrity"]["pairs"] != 240:
        raise RuntimeError("poster source is not the complete paired primary run")
    if _sha(recorder.records_path) != summary["integrity"]["records_sha256"]:
        raise RuntimeError("primary record hash changed")
    if summary["repeatability_executed"] or summary["provider_inference_calls_during_analysis"]:
        raise RuntimeError("poster source is not CP-14-only local analysis")
    if audit["integrity"]["orphan_jev_input_tokens"] != 2506:
        raise RuntimeError("CP-14 audit exception changed")
    timeout_source = ROOT / "artifacts" / "runs" / "primary-v1" / "resume_primary.py"
    if "turn_timeout_seconds=120.0" not in timeout_source.read_text(encoding="utf-8"):
        raise RuntimeError("Terra decision provider timeout setting changed")

    systems = summary["systems"]
    t, j = systems["terra_only"], systems["terra_jev"]
    effects = summary["paired_effects"]
    risk_t = t["coverage"]["at_most_2pct_action_error"]
    risk_j = j["coverage"]["at_most_2pct_action_error"]
    if risk_t is not None or risk_j["covered_count"] != 239:
        raise RuntimeError("risk-coverage headline changed")
    wrong_90 = {}
    for system in ("terra_only", "terra_jev"):
        subset = [
            record
            for record in records
            if record.system == system
            and record.top_probability is not None
            and record.top_probability >= 0.90
        ]
        wrong_90[system] = sum(record.raw_action is not record.gold_action for record in subset)
        reported = systems[system]["calibration"]["high_confidence"]["0.9"]
        if len(subset) != reported["count"] or wrong_90[system] != round(
            reported["error_rate"] * len(subset)
        ):
            raise RuntimeError("high-confidence error counts did not reconcile")

    latency_t = t["efficiency"]["decision_latency_p50_ms"] / 1000
    latency_j = j["efficiency"]["decision_latency_p50_ms"] / 1000
    cost_t = t["efficiency"]["normalized_cost_per_1000_cases_usd"]
    cost_j = j["efficiency"]["normalized_cost_per_1000_cases_usd"]
    return {
        "scope": "Completed CP-14 frozen primary records only; no new provider calls",
        "sources": {
            "summary": "artifacts/final/summary.json",
            "summary_sha256": _sha(SUMMARY_PATH),
            "cp14_audit": "artifacts/cp14/integrity-audit.json",
            "cp14_audit_sha256": _sha(AUDIT_PATH),
            "records": "artifacts/runs/primary-v1/records.jsonl",
            "records_sha256": _sha(recorder.records_path),
            "freeze_tag": "v1.0.1-freeze",
            "freeze_verified": True,
            "completed_record_checksums_verified": True,
        },
        "context": {
            "terra_model": "GPT-5.6 Terra",
            "jev_model": "Jev 1.13.0",
            "frozen_cases": 240,
            "scored_executions": 480,
            "systems": 2,
            "stress_categories": 8,
            "gold_actions": 5,
            "action_labels": ["REFUND", "RESHIP", "REQUEST INFO", "WAIT", "ESCALATE"],
            "category_labels": [
                "normal",
                "multi-tool",
                "boundaries",
                "missing info",
                "conflicting evidence",
                "prompt injection",
                "tool failures",
                "tool selection",
            ],
            "source": "EXPERIMENT.md#Dataset; summary.json#/integrity",
        },
        "risk_coverage": {
            "max_observed_action_error_rate": 0.02,
            "terra_only_covered_count": 0,
            "terra_jev_covered_count": risk_j["covered_count"],
            "terra_only_coverage": 0.0,
            "terra_jev_coverage": risk_j["coverage"],
            "terra_jev_action_error_count": risk_j["action_error_count"],
            "terra_jev_action_error_rate": risk_j["action_error_rate"],
            "terra_only_curve": t["coverage"]["continuous_tie_aware"],
            "terra_jev_curve": j["coverage"]["continuous_tie_aware"],
            "axis_coverage_ticks": [0, 0.25, 0.5, 0.75, 1.0],
            "axis_error_ticks": [0, 0.05, 0.10, 0.15, 0.20, 0.25],
            "source": "summary.json#/systems/*/coverage",
            "method_note": "Offline confidence gate; tied scores kept together; invalid distributions uncovered.",
        },
        "metrics": {
            "accuracy": {
                "terra_only_count": t["correctness"]["correct_count"],
                "terra_jev_count": j["correctness"]["correct_count"],
                "denominator": 240,
                "terra_only_rate": t["correctness"]["accuracy"],
                "terra_jev_rate": j["correctness"]["accuracy"],
                "paired_difference": effects["accuracy"]["paired_difference_jev_minus_terra"],
                "ci95_lower": effects["accuracy"]["ci95_lower"],
                "ci95_upper": effects["accuracy"]["ci95_upper"],
                "source": "summary.json#/systems/*/correctness; /paired_effects/accuracy",
            },
            "unsafe": {
                "terra_only_count": t["correctness"]["unsafe_autonomous_count"],
                "terra_jev_count": j["correctness"]["unsafe_autonomous_count"],
                "denominator": 240,
                "source": "summary.json#/systems/*/correctness",
            },
            "high_confidence_wrong": {
                "threshold": 0.90,
                "terra_only_wrong": wrong_90["terra_only"],
                "terra_only_count": t["calibration"]["high_confidence"]["0.9"]["count"],
                "terra_jev_wrong": wrong_90["terra_jev"],
                "terra_jev_count": j["calibration"]["high_confidence"]["0.9"]["count"],
                "terra_only_rate": t["calibration"]["high_confidence"]["0.9"]["error_rate"],
                "terra_jev_rate": j["calibration"]["high_confidence"]["0.9"]["error_rate"],
                "source": "summary.json#/systems/*/calibration/high_confidence/0.9; CP-14 records",
            },
            "ece": {
                "terra_only": t["calibration"]["ece"],
                "terra_jev": j["calibration"]["ece"],
                "terra_only_valid_count": t["calibration"]["scored_count"],
                "terra_jev_valid_count": j["calibration"]["scored_count"],
                "source": "summary.json#/systems/*/calibration",
            },
            "median_decision_latency": {
                "terra_only_seconds": latency_t,
                "terra_jev_seconds": latency_j,
                "terra_only_over_jev": latency_t / latency_j,
                "source": "summary.json#/systems/*/efficiency/decision_latency_p50_ms",
            },
            "normalized_decision_cost_per_1000": {
                "terra_only_usd": cost_t,
                "terra_jev_usd": cost_j,
                "terra_only_over_jev": cost_t / cost_j,
                "source": "summary.json#/systems/*/efficiency/normalized_cost_per_1000_cases_usd",
            },
            "read_calls_per_case": {
                "terra_only": t["tools"]["mean_model_requested_reads"],
                "terra_jev": j["tools"]["mean_model_requested_reads"],
                "difference": j["tools"]["mean_model_requested_reads"]
                - t["tools"]["mean_model_requested_reads"],
                "source": "summary.json#/systems/*/tools/mean_model_requested_reads",
            },
        },
        "limits": {
            "terra_decision_timeouts": summary["infrastructure"]["terra_only_decision_timeouts"],
            "terra_decision_timeout_seconds": 120,
            "repeatability_executed": False,
            "unscored_interrupted_jev_attempts": 1,
            "scored_records_affected_by_missing_attempt_evidence": 0,
            "source": "summary.json#/infrastructure; artifacts/cp14/integrity-audit.json; artifacts/runs/primary-v1/resume_primary.py:100",
        },
        "poster": {
            "width_px": W,
            "height_px": H,
            "aspect_ratio": "4:5",
            "methodology": (
                "Deterministic policy oracle; prompts, policy, tools, thresholds and "
                "provider versions frozen before test inference."
            ),
        },
    }


def _write_data() -> None:
    data = _calculate_data()
    OUT.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {DATA_PATH} from verified local CP-14 records")


def _verify_data() -> dict:
    if not DATA_PATH.is_file():
        raise RuntimeError("infographic-data.json does not exist")
    stored = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    calculated = _calculate_data()
    if stored != calculated:
        raise RuntimeError("infographic-data.json differs from verified source artifacts")
    if (
        stored["metrics"]["unsafe"]["terra_only_count"] != 0
        or stored["metrics"]["unsafe"]["terra_jev_count"] != 0
    ):
        raise RuntimeError("unsafe-action headline changed")
    if stored["risk_coverage"]["terra_jev_action_error_rate"] > 0.02:
        raise RuntimeError("risk-coverage claim exceeds observed error cap")
    print("Infographic data PASS: frozen hashes, 480 scored records, paired metrics, risk gate")
    return stored


def _render(data: dict) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "svg.fonttype": "none",
            "svg.hashsalt": "fusebench-cp14",
        }
    )
    fig = plt.figure(figsize=(10, 12.5), dpi=160, facecolor=PAPER)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    def box(
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        radius: float = 18,
        edge: str | None = None,
        lw: float = 1,
    ) -> None:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle=f"round,pad=0,rounding_size={radius}",
                linewidth=lw if edge else 0,
                edgecolor=edge if edge else fill,
                facecolor=fill,
            )
        )

    def txt(
        x: float,
        y: float,
        value: str,
        size: float = 11,
        weight: str = "normal",
        color: str = INK,
        ha: str = "left",
        va: str = "top",
        linespacing: float = 1.15,
    ) -> None:
        ax.text(
            x,
            y,
            value,
            fontsize=size,
            weight=weight,
            color=color,
            ha=ha,
            va=va,
            linespacing=linespacing,
        )

    def rule(y: float, x0: float = 90, x1: float = 1510, color: str = RULE) -> None:
        ax.plot([x0, x1], [y, y], color=color, lw=1.1)

    def arrow(x: float, y: float, color: str = MUTED) -> None:
        txt(x, y, "↓", 14, "bold", color, va="center")

    c = data["context"]
    m = data["metrics"]
    risk = data["risk_coverage"]
    limits = data["limits"]
    max_error = risk["axis_error_ticks"][-1]

    # Header: the question comes before the benchmark name.
    txt(92, 58, "FUSEBENCH  /  AGENT ARCHITECTURE", 10, "bold", GREEN)
    txt(
        90, 105, "Maybe your LLM shouldn’t\nmake every decision.", 40, "bold", INK, linespacing=1.00
    )
    txt(
        94,
        276,
        "I tested GPT-5.6 Terra against the same agent with Jev inserted as the decision layer.",
        12.7,
        color=MUTED,
    )
    txt(
        94,
        319,
        f"{c['frozen_cases']} frozen unseen tasks  •  {c['scored_executions']} scored executions  •  same policy  •  same tools  •  same environment",
        9.6,
        "bold",
        MUTED,
    )
    rule(357)

    # The actual CP-14 decision paths. Shared Terra response happens later.
    txt(94, 378, "THE ARCHITECTURE QUESTION", 11, "bold", GREEN)
    box(90, 417, 692, 244, WHITE, edge=RULE)
    box(818, 417, 692, 244, WHITE, edge=RULE)
    box(90, 417, 692, 9, BLUE, radius=0)
    box(818, 417, 692, 9, ORANGE, radius=0)
    txt(124, 447, "LLM-OWNED AGENT", 14, "bold", BLUE)
    txt(124, 485, "User case", 10, color=MUTED)
    arrow(125, 516, BLUE)
    txt(154, 520, "Terra selects reads + policy action", 10.3, "bold")
    txt(154, 550, "Open-ended language reasoning", 9.4, color=MUTED)
    arrow(125, 582, BLUE)
    txt(154, 586, "Deterministic action runtime", 9.9)
    txt(852, 447, "HYBRID AGENT", 14, "bold", ORANGE)
    txt(852, 485, "User case → harness structures visible state", 9.7, color=MUTED)
    arrow(853, 516, ORANGE)
    txt(882, 520, "Jev selects reads + bounded action", 10.3, "bold")
    txt(882, 550, "Five-action probabilities", 9.4, color=MUTED)
    arrow(853, 582, ORANGE)
    txt(882, 586, "Deterministic action runtime", 9.9)
    box(90, 674, 1420, 66, GREEN_PALE, radius=12)
    txt(118, 694, "TESTED CHANGE", 9.8, "bold", GREEN)
    txt(325, 686, "Bounded decision ownership changed, including read selection.", 10.0, "bold")
    txt(
        325,
        711,
        "Policy, tools, environment and post-action responder stayed fixed.",
        9.5,
        color=MUTED,
    )

    # Why an agent engineer should care, and what was tested.
    txt(94, 755, "OPEN-ENDED COGNITION", 11, "bold", BLUE)
    txt(94, 788, "Language  •  synthesis  •  responses  •  novelty", 9.7)
    txt(818, 755, "CLOSED DECISIONS INSIDE AGENTS", 11, "bold", ORANGE)
    txt(818, 788, "Refund or escalate?  Evidence enough?  Automate?", 9.7)
    rule(833)
    txt(94, 851, "THE TEST", 10.5, "bold", GREEN)
    txt(
        244,
        850,
        f"{c['frozen_cases']} cases  /  {c['stress_categories']} stress categories  /  {c['gold_actions']} allowed actions",
        12.4,
        "bold",
    )
    txt(94, 892, "REFUND  •  RESHIP  •  REQUEST INFO  •  WAIT  •  ESCALATE", 10.7, "bold", MUTED)
    txt(
        94,
        920,
        "Oracle: deterministic policy code, not an LLM judge. Prompts, policies, tools, thresholds and model versions were frozen.",
        8.8,
        color=MUTED,
    )
    txt(
        94,
        945,
        "Stress: normal • multi-tool • boundaries • missing info • conflicting evidence • prompt injection • tool failure • tool selection",
        8.5,
        color=MUTED,
    )

    # Risk versus automation coverage is the dominant result.
    box(90, 976, 1420, 425, WHITE, edge=RULE)
    txt(
        120, 1000, "HOW MUCH CAN YOU AUTOMATE BEFORE ERRORS BECOME UNACCEPTABLE?", 11, "bold", GREEN
    )
    cap = risk["max_observed_action_error_rate"]
    txt(120, 1041, f"At ≤{cap:.0%} observed action error", 17, "bold")
    chart_x, chart_y, chart_w, chart_h = 145, 1110, 846, 180
    ax.add_patch(
        Rectangle(
            (chart_x, chart_y + chart_h * (1 - cap / max_error)),
            chart_w,
            chart_h * (cap / max_error),
            facecolor=GREEN_PALE,
            edgecolor="none",
        )
    )
    for tick in risk["axis_error_ticks"]:
        yy = chart_y + chart_h * (1 - tick / max_error)
        ax.plot([chart_x, chart_x + chart_w], [yy, yy], color=RULE, lw=0.9)
        txt(chart_x - 14, yy, f"{tick:.0%}", 8.4, color=MUTED, ha="right", va="center")
    for tick in risk["axis_coverage_ticks"]:
        xx = chart_x + chart_w * tick
        ax.plot([xx, xx], [chart_y, chart_y + chart_h], color=RULE, lw=0.6)
        txt(xx, chart_y + chart_h + 9, f"{tick:.0%}", 8.4, color=MUTED, ha="center")
    txt(
        chart_x + chart_w / 2,
        chart_y + chart_h + 40,
        "AUTOMATION COVERAGE →",
        9.5,
        "bold",
        MUTED,
        ha="center",
    )
    for system, color in (("terra_only", BLUE), ("terra_jev", ORANGE)):
        curve = risk[f"{system}_curve"]
        xs = [chart_x + chart_w * p["coverage"] for p in curve]
        ys = [chart_y + chart_h * (1 - p["action_error_rate"] / max_error) for p in curve]
        ax.plot(xs, ys, color=color, lw=3.2, solid_capstyle="round")
        ax.scatter(xs[-1], ys[-1], s=65, color=color, zorder=4)
    txt(1025, 1105, "TERRA + JEV", 10, "bold", ORANGE)
    txt(1025, 1132, f"{risk['terra_jev_coverage']:.1%}", 30, "bold", ORANGE)
    txt(
        1025,
        1197,
        f"{risk['terra_jev_covered_count']}/{c['frozen_cases']} cases at ≤{cap:.0%} error",
        11,
    )
    txt(1025, 1240, "TERRA-ONLY", 10, "bold", BLUE)
    txt(1025, 1266, f"{risk['terra_only_coverage']:.0%}", 24, "bold", BLUE)
    txt(1025, 1320, "No attainable confidence gate\nmet that error level.", 10, color=MUTED)
    txt(
        120,
        1370,
        "Offline confidence gating; tied scores kept together; invalid outputs are not covered.",
        8.8,
        color=MUTED,
    )

    # Compact engineering metrics. Values are formatted only from infographic-data.json.
    txt(94, 1424, "MEASURED TRADE-OFFS", 11, "bold", GREEN)
    txt(750, 1424, "TERRA-ONLY", 9.2, "bold", BLUE, ha="right")
    txt(1090, 1424, "TERRA + JEV", 9.2, "bold", ORANGE, ha="right")
    txt(1488, 1424, "CHANGE", 9.5, "bold", MUTED, ha="right")

    rows = [
        (
            "Final action accuracy",
            f"{m['accuracy']['terra_only_rate']:.1%}",
            f"{m['accuracy']['terra_jev_rate']:.1%}",
            f"+{m['accuracy']['paired_difference'] * 100:.1f} pp",
        ),
        (
            "Unsafe autonomous actions",
            f"{m['unsafe']['terra_only_count']}/{m['unsafe']['denominator']}",
            f"{m['unsafe']['terra_jev_count']}/{m['unsafe']['denominator']}",
            "same observed rate",
        ),
        (
            f"Wrong at ≥{m['high_confidence_wrong']['threshold']:.0%} confidence",
            f"{m['high_confidence_wrong']['terra_only_rate']:.1%} ({m['high_confidence_wrong']['terra_only_wrong']}/{m['high_confidence_wrong']['terra_only_count']})",
            f"{m['high_confidence_wrong']['terra_jev_rate']:.0%} ({m['high_confidence_wrong']['terra_jev_wrong']}/{m['high_confidence_wrong']['terra_jev_count']})",
            f"−{(m['high_confidence_wrong']['terra_only_rate'] - m['high_confidence_wrong']['terra_jev_rate']) * 100:.1f} pp",
        ),
        (
            "Calibration error (ECE)",
            f"{m['ece']['terra_only']:.3f}",
            f"{m['ece']['terra_jev']:.3f}",
            "lower",
        ),
        (
            "Median decision latency",
            f"{m['median_decision_latency']['terra_only_seconds']:.2f} s",
            f"{m['median_decision_latency']['terra_jev_seconds']:.2f} s",
            f"{m['median_decision_latency']['terra_only_over_jev']:.1f}× lower",
        ),
        (
            "Decision cost / 1k cases",
            f"${m['normalized_decision_cost_per_1000']['terra_only_usd']:.2f}",
            f"${m['normalized_decision_cost_per_1000']['terra_jev_usd']:.3f}",
            f"{m['normalized_decision_cost_per_1000']['terra_only_over_jev']:.0f}× lower",
        ),
        (
            "Read calls / case",
            f"{m['read_calls_per_case']['terra_only']:.2f}",
            f"{m['read_calls_per_case']['terra_jev']:.2f}",
            f"+{m['read_calls_per_case']['difference']:.2f} reads",
        ),
    ]
    row_start, row_step = 1461, 36
    for i, (label, terra, hybrid, change) in enumerate(rows):
        yy = row_start + i * row_step
        rule(yy - 6)
        txt(94, yy, label, 9.4, "bold" if i == 0 else "normal")
        txt(750, yy, terra, 9.5, "bold", BLUE, ha="right")
        txt(1090, yy, hybrid, 9.5, "bold", ORANGE, ha="right")
        txt(1488, yy, change, 9.2, "bold", INK, ha="right")
    txt(
        94,
        1714,
        "Decision-path latency and normalized cost exclude the shared Terra responder.",
        8.1,
        color=MUTED,
    )
    txt(
        94,
        1736,
        "Terra cost uses frozen API-equivalent rates; both systems used the same post-action responder.",
        8.1,
        color=MUTED,
    )

    # Inference from evidence, with the operational trade-off visible.
    rule(1765)
    txt(94, 1781, "WHAT CHANGED WHEN JUDGMENT LEFT THE LLM?", 10.0, "bold", GREEN)
    txt(
        94,
        1803,
        "The result wasn’t “Jev is a better LLM.”",
        9.8,
        "bold",
    )
    txt(
        94, 1826, "It was that the LLM didn’t need to own the bounded decision at all.", 9.8, "bold"
    )

    txt(94, 1858, "WHEN TO USE IT", 8.8, "bold", GREEN)
    txt(94, 1885, "Finite actions • observable state", 7.8)
    txt(94, 1906, "Costly mistakes • human fallback", 7.8)
    txt(94, 1927, "Refunds, routing, approvals.", 7.8)
    txt(94, 1948, "Not coding, research, open planning.", 7.8)

    box(474, 1853, 652, 133, INK, radius=12)
    txt(498, 1866, "THE PATTERN THIS RESULT SUGGESTS", 8.4, "bold", "#a8dcc9")
    txt(800, 1894, "LLM: understand + generate", 9.2, "bold", WHITE, ha="center")
    txt(800, 1914, "↓", 10, "bold", "#a8dcc9", ha="center")
    txt(800, 1930, "Jev: bounded judgment", 9.2, "bold", WHITE, ha="center")
    txt(800, 1950, "↓", 10, "bold", "#a8dcc9", ha="center")
    txt(800, 1966, "Code: policy + actions + escalation", 9.2, "bold", WHITE, ha="center")

    txt(1150, 1852, "HONEST LIMITS", 8.8, "bold", GREEN)
    txt(1150, 1873, f"One {c['terra_model']}; synthetic domain.", 7.6)
    txt(
        1150,
        1893,
        f"{limits['terra_decision_timeouts']} Terra-only decision turns reached",
        7.6,
    )
    txt(
        1150,
        1913,
        f"the {limits['terra_decision_timeout_seconds']} s provider timeout.",
        7.6,
    )
    txt(1150, 1933, "No repeatability; no broad claim.", 7.6)
    txt(
        1150,
        1953,
        f"{limits['unscored_interrupted_jev_attempts']} unscored interrupted Jev attempt; raw missing.",
        7.2,
    )
    txt(
        1150,
        1973,
        f"{limits['scored_records_affected_by_missing_attempt_evidence']}/{c['scored_executions']} scored records affected.",
        7.2,
    )

    png = OUT / "fusebench-results.png"
    svg = OUT / "fusebench-results.svg"
    fig.savefig(png, dpi=160, facecolor=PAPER, pad_inches=0)
    fig.savefig(svg, facecolor=PAPER, pad_inches=0, metadata={"Date": None})
    svg.write_text(
        "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n",
        encoding="utf-8",
    )
    plt.close(fig)
    print(f"Rendered {png.name} ({W}×{H}) and {svg.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("data", "verify", "render"))
    args = parser.parse_args()
    if args.step == "data":
        _write_data()
    elif args.step == "verify":
        _verify_data()
    else:
        _render(_verify_data())


if __name__ == "__main__":
    main()
