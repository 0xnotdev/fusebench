"""Compose one 4:5 social research image from the three verified CP-14 figures.

Run locally, with no provider access:
    uv run python -m artifacts.final.build_social_report
"""

# Figure labels use intentional typographic dashes.
# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

W, H = 2400, 3000
OUT = Path(__file__).resolve().parent

PAPER = "#ffffff"
INK = "#172831"
MUTED = "#526169"
LINE = "#cdd6d2"
BLUE = "#3f6986"
ORANGE = "#c95837"
GREEN = "#236e63"


def render_social_report(data: dict, figures: dict[str, Path], output: Path) -> None:
    """Place all three source figures at legible scale in one social canvas."""
    required = ("risk_coverage", "calibration", "latency_cost")
    for name in required:
        if name not in figures or not figures[name].is_file():
            raise FileNotFoundError(f"missing {name} source figure")

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12, 15), dpi=200, facecolor=PAPER)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    def label(
        x: float,
        y: float,
        value: str,
        size: float,
        *,
        color: str = INK,
        weight: str = "normal",
        family: str = "DejaVu Sans",
        ha: str = "left",
    ) -> None:
        ax.text(
            x,
            y,
            value,
            fontsize=size,
            color=color,
            weight=weight,
            fontfamily=family,
            ha=ha,
            va="top",
            linespacing=1.07,
        )

    def rule(y: float) -> None:
        ax.plot((120, 2280), (y, y), color=LINE, lw=1.25)

    def source_figure(name: str, x: float, y: float, width: float, height: float) -> None:
        pixels = plt.imread(figures[name])
        actual_height, actual_width = pixels.shape[:2]
        scale = min(width / actual_width, height / actual_height)
        display_width, display_height = actual_width * scale, actual_height * scale
        left = x + (width - display_width) / 2
        top = y + (height - display_height) / 2
        ax.imshow(
            pixels,
            extent=(left, left + display_width, top + display_height, top),
            interpolation="nearest",
            zorder=2,
        )

    accuracy = data["metrics"]["accuracy"]
    risk = data["risk_coverage"]
    latency = data["metrics"]["median_decision_latency"]
    cost = data["metrics"]["normalized_decision_cost_per_1000"]

    # Editorial lead: a factual result, not a model-general claim.
    ax.add_patch(plt.Rectangle((120, 112), 38, 10, facecolor=ORANGE, edgecolor="none"))
    label(178, 96, "FUSEBENCH   /   FROZEN PRIMARY RUN", 14, color=GREEN, weight="bold")
    label(
        120,
        168,
        "Who owns the\nbounded decision?",
        50,
        weight="bold",
        family="DejaVu Serif",
    )
    label(
        125,
        492,
        "GPT-5.6 Terra alone vs. Terra + Jev on 240 frozen order-exception cases.",
        21,
        color=MUTED,
    )
    rule(584)

    label(120, 632, "FINAL-ACTION ACCURACY", 16, color=GREEN, weight="bold")
    label(120, 686, f"{accuracy['terra_only_rate']:.1%}", 58, color=BLUE, weight="bold")
    label(758, 705, "→", 44, color=MUTED)
    label(905, 686, f"{accuracy['terra_jev_rate']:.1%}", 58, color=ORANGE, weight="bold")
    label(126, 850, "TERRA-ONLY", 15, color=BLUE, weight="bold")
    label(910, 850, "TERRA + JEV", 15, color=ORANGE, weight="bold")
    label(
        1690, 687, f"+{accuracy['paired_difference'] * 100:.1f} pp", 39, color=ORANGE, weight="bold"
    )
    label(
        1692,
        820,
        f"95% CI: {accuracy['ci95_lower'] * 100:.1f}–{accuracy['ci95_upper'] * 100:.1f} pp",
        17,
        color=MUTED,
    )
    rule(893)

    # Evidence 01: the largest panel carries the risk/coverage result.
    label(120, 936, "01   /   RISK–COVERAGE", 18, color=GREEN, weight="bold")
    label(120, 996, "How much can confidence-gating automate?", 23, weight="bold")
    source_figure("risk_coverage", 112, 1088, 1390, 818)
    label(1570, 1092, "TERRA + JEV", 16, color=ORANGE, weight="bold")
    label(1565, 1138, f"{risk['terra_jev_coverage']:.1%}", 58, color=ORANGE, weight="bold")
    label(1570, 1310, f"{risk['terra_jev_covered_count']}/240 cases", 24, weight="bold")
    label(1570, 1384, "covered at ≤2% observed", 19, color=MUTED)
    label(1570, 1440, "action error", 19, color=MUTED)
    ax.plot((1570, 2240), (1530, 1530), color=LINE, lw=1.1)
    label(1570, 1572, "Terra-only", 17, color=BLUE, weight="bold")
    label(1570, 1630, "No attainable confidence gate", 19)
    label(1570, 1682, "met the same error cap.", 19)
    rule(1934)

    # Evidence 02/03: figures stay intact; large annotations remain readable in-feed.
    label(120, 1976, "02   /   CALIBRATION", 18, color=GREEN, weight="bold")
    label(1275, 1976, "03   /   DECISION EFFICIENCY", 18, color=GREEN, weight="bold")
    source_figure("calibration", 112, 2040, 1060, 814)
    source_figure("latency_cost", 1255, 2070, 1040, 400)
    label(
        1280,
        2520,
        f"{latency['terra_only_seconds']:.2f} → {latency['terra_jev_seconds']:.2f} s",
        33,
        weight="bold",
    )
    label(1282, 2630, "Median decision-path latency", 16, color=MUTED)
    label(
        1280,
        2700,
        f"\\${cost['terra_only_usd']:.2f} → \\${cost['terra_jev_usd']:.3f}",
        27,
        weight="bold",
    )
    label(1282, 2780, "Normalized decision cost / 1,000 cases", 16, color=MUTED)

    rule(2870)
    label(
        120,
        2890,
        "240 paired cases  •  480 scored executions  •  same policy, tools and environment",
        15,
        color=MUTED,
    )
    label(
        120,
        2947,
        "Primary scores include Terra decision timeouts. "
        "Decision metrics exclude the shared responder.",
        12,
        color=MUTED,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, facecolor=PAPER, pad_inches=0)
    plt.close(fig)


def main() -> None:
    from artifacts.final.build_infographic import _verify_data

    data = _verify_data()
    figures = {
        name: OUT / f"{name}.png" for name in ("risk_coverage", "calibration", "latency_cost")
    }
    output = OUT / "fusebench-social.png"
    render_social_report(data, figures, output)
    print(f"Rendered {output} ({W}x{H}); three source figures included")


if __name__ == "__main__":
    main()
