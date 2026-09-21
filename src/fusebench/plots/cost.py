"""Accuracy versus normalized inference-cost headline plot."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_accuracy_cost(analysis_dir: Path) -> Path:
    summary = json.loads((analysis_dir / "summary.json").read_text(encoding="utf-8"))
    systems = ("terra_only", "terra_jev")
    labels = ("Terra-only", "Terra + Jev")
    costs = [
        summary["systems"][system]["efficiency"]["normalized_cost_per_1000_cases_usd"]
        for system in systems
    ]
    accuracy = [summary["systems"][system]["correctness"]["accuracy"] for system in systems]
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.scatter(costs, accuracy, s=70)
    for label, x_value, y_value in zip(labels, costs, accuracy, strict=True):
        axis.annotate(label, (x_value, y_value), xytext=(5, 5), textcoords="offset points")
    axis.set(
        xlabel="Normalized inference cost / 1k cases (USD)",
        ylabel="Raw action accuracy",
        title="Accuracy vs normalized cost",
    )
    figure.text(
        0.5,
        0.01,
        "Terra: API-equivalent normalization; Jev: promotional-credit estimate",
        ha="center",
        fontsize=8,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    path = analysis_dir / "accuracy_cost.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path
