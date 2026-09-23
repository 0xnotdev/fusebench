"""The public risk figure makes the low-error region legible without hiding the outlier."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from artifacts.final import build_results


def test_public_risk_figure_zooms_main_axis_and_preserves_terra_outlier() -> None:
    summary = {
        "systems": {
            "terra_only": {
                "coverage": {
                    "continuous_tie_aware": [
                        {"coverage": 0.65, "action_error_rate": 0.186},
                        {"coverage": 0.658, "action_error_rate": 0.190},
                    ]
                }
            },
            "terra_jev": {
                "coverage": {
                    "continuous_tie_aware": [
                        {"coverage": 0.50, "action_error_rate": 0.0},
                        {"coverage": 0.996, "action_error_rate": 0.0167},
                    ]
                }
            },
        }
    }

    assert hasattr(build_results, "_risk_coverage_figure")
    figure, main = build_results._risk_coverage_figure(summary)
    try:
        assert main.get_ylim() == pytest.approx((0, 0.05))
        assert len(main.child_axes) == 1
        inset = main.child_axes[0]
        assert inset.get_ylim() == pytest.approx((0.15, 0.21))
        assert list(inset.lines[0].get_ydata()) == pytest.approx([0.186, 0.190])
    finally:
        plt.close(figure)
