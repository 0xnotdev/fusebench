"""The share image preserves every frozen CP-14 figure in one canvas."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def _report_module():
    spec = importlib.util.find_spec("artifacts.final.build_social_report")
    assert spec is not None, "the social report builder is missing"
    return importlib.import_module("artifacts.final.build_social_report")


def _source_figures(tmp_path: Path) -> dict[str, Path]:
    figures = {}
    for name, color in (
        ("risk_coverage", (245, 12, 12)),
        ("calibration", (12, 205, 12)),
        ("latency_cost", (12, 12, 245)),
    ):
        path = tmp_path / f"{name}.png"
        Image.new("RGB", (480, 320), color).save(path)
        figures[name] = path
    return figures


def test_social_report_contains_all_three_figures_in_one_4_by_5_image(tmp_path: Path) -> None:
    report = _report_module()
    data = json.loads((ROOT / "artifacts/final/infographic-data.json").read_text(encoding="utf-8"))
    output = tmp_path / "report.png"

    report.render_social_report(data, _source_figures(tmp_path), output)

    with Image.open(output) as image:
        assert image.size == (2400, 3000)
        pixels = np.asarray(image.convert("RGB"))[::8, ::8]
        for color in ((245, 12, 12), (12, 205, 12), (12, 12, 245)):
            assert np.any(np.all(pixels == color, axis=2)), f"figure color {color} was omitted"


def test_social_report_rejects_missing_source_figure(tmp_path: Path) -> None:
    report = _report_module()
    data = json.loads((ROOT / "artifacts/final/infographic-data.json").read_text(encoding="utf-8"))
    figures = _source_figures(tmp_path)
    figures["calibration"] = tmp_path / "does-not-exist.png"

    with pytest.raises(FileNotFoundError, match="calibration"):
        report.render_social_report(data, figures, tmp_path / "report.png")


def test_calibration_summary_uses_frozen_valid_output_denominators() -> None:
    report = _report_module()
    data = json.loads((ROOT / "artifacts/final/infographic-data.json").read_text(encoding="utf-8"))

    assert report.calibration_summary(data) == (
        "ECE: 0.190 → 0.033",
        "Wrong at ≥90% confidence: 30/158 → 0/213",
    )
