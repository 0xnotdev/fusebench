"""Calibration/reliability headline plot."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_calibration(analysis_dir: Path) -> Path:
    table = pd.read_csv(analysis_dir / "calibration_bins.csv")
    figure, axis = plt.subplots(figsize=(5, 5))
    labels = {"terra_only": "Terra-only", "terra_jev": "Terra + Jev"}
    for system, group in table.groupby("system"):
        populated = group[group["count"] > 0]
        axis.plot(
            populated["mean_confidence"],
            populated["empirical_accuracy"],
            marker="o",
            label=labels[system],
        )
    axis.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Ideal")
    axis.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Mean predicted top probability",
        ylabel="Empirical accuracy",
        title="Reliability",
    )
    axis.legend()
    figure.tight_layout()
    path = analysis_dir / "calibration.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path
