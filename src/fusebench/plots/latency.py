"""Decision latency versus accuracy headline plot."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_latency_accuracy(analysis_dir: Path) -> Path:
    summary = json.loads((analysis_dir / "summary.json").read_text(encoding="utf-8"))
    systems = ("terra_only", "terra_jev")
    labels = ("Terra-only", "Terra + Jev")
    latency = [
        summary["systems"][system]["efficiency"]["decision_latency_p50_ms"] for system in systems
    ]
    accuracy = [summary["systems"][system]["correctness"]["accuracy"] for system in systems]
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.scatter(latency, accuracy, s=70)
    for label, x_value, y_value in zip(labels, latency, accuracy, strict=True):
        axis.annotate(label, (x_value, y_value), xytext=(5, 5), textcoords="offset points")
    axis.set(
        xlabel="Median end-to-end decision-path latency (ms)",
        ylabel="Raw action accuracy",
        title="Decision latency and correctness (descriptive, not causal)",
    )
    figure.tight_layout()
    path = analysis_dir / "latency_accuracy.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path
