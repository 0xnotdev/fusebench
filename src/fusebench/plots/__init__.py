"""Publication plot generation."""

from pathlib import Path

from fusebench.plots.calibration import plot_calibration
from fusebench.plots.cost import plot_accuracy_cost
from fusebench.plots.latency import plot_latency_accuracy
from fusebench.plots.risk_coverage import plot_risk_coverage


def generate_headline_plots(analysis_dir: Path) -> tuple[Path, ...]:
    """Generate exactly the four preregistered v1 headline plot files."""

    return (
        plot_risk_coverage(analysis_dir),
        plot_calibration(analysis_dir),
        plot_latency_accuracy(analysis_dir),
        plot_accuracy_cost(analysis_dir),
    )


__all__ = ["generate_headline_plots"]
