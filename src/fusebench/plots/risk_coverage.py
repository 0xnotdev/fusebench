"""Risk-versus-coverage headline plot."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_risk_coverage(analysis_dir: Path) -> Path:
    table = pd.read_csv(analysis_dir / "risk_coverage.csv")
    table = table[table["kind"] == "continuous"]
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), sharex=True)
    labels = {"terra_only": "Terra-only", "terra_jev": "Terra + Jev"}
    for system, group in table.groupby("system"):
        axes[0].plot(
            group["coverage"],
            group["action_error_rate"],
            marker="o",
            label=labels[system],
        )
        axes[1].plot(
            group["coverage"],
            group["unsafe_error_rate"],
            marker="o",
            label=labels[system],
        )
    axes[0].set(title="Action risk vs coverage", xlabel="Coverage", ylabel="Action error rate")
    axes[1].set(title="Unsafe risk vs coverage", xlabel="Coverage", ylabel="Unsafe error rate")
    axes[0].legend()
    figure.tight_layout()
    path = analysis_dir / "risk_coverage.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path
