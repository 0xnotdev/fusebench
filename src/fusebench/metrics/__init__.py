"""Pure benchmark metrics."""

from fusebench.metrics.calibration import summarize_calibration
from fusebench.metrics.consistency import summarize_consistency
from fusebench.metrics.correctness import summarize_correctness
from fusebench.metrics.coverage import continuous_risk_coverage, threshold_sweep
from fusebench.metrics.efficiency import summarize_efficiency, summarize_tool_use
from fusebench.metrics.statistics import mcnemar_test, paired_bootstrap

__all__ = [
    "continuous_risk_coverage",
    "mcnemar_test",
    "paired_bootstrap",
    "summarize_calibration",
    "summarize_consistency",
    "summarize_correctness",
    "summarize_efficiency",
    "summarize_tool_use",
    "threshold_sweep",
]
