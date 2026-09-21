import json
from pathlib import Path

from fusebench.contracts.actions import Action, IssueType
from fusebench.metrics.report import generate_analysis
from fusebench.plots import generate_headline_plots


def test_analysis_outputs_and_exact_four_headline_plots(make_record, tmp_path: Path) -> None:
    records = []
    for index, gold in enumerate((Action.WAIT, Action.REFUND, Action.ESCALATE)):
        for system in ("terra_only", "terra_jev"):
            records.append(
                make_record(
                    case_id=f"REPORT_{index}",
                    system=system,
                    gold=gold,
                    raw=gold,
                    category=("clean", "adversarial", "tool_failure")[index],
                    issue_type=(
                        IssueType.SHIPPING,
                        IssueType.DUPLICATE_PAYMENT,
                        IssueType.OTHER,
                    )[index],
                    terra_input_tokens=100 if system == "terra_only" else 0,
                    terra_output_tokens=10 if system == "terra_only" else 0,
                    jev_input_tokens=100 if system == "terra_jev" else 0,
                )
            )
    output = tmp_path / "analysis"

    generate_analysis(records, output, bootstrap_samples=100, bootstrap_seed=9)
    plots = generate_headline_plots(output)

    expected = {
        "summary.json",
        "summary.md",
        "per_category.csv",
        "per_action.csv",
        "per_issue.csv",
        "calibration_bins.csv",
        "risk_coverage.csv",
        "paired_bootstrap.csv",
        "mcnemar.json",
        "methodology_snapshot.md",
    }
    assert expected <= {path.name for path in output.iterdir()}
    assert len(plots) == 4
    assert all(path.is_file() for path in plots)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["systems"]) == {"terra_only", "terra_jev"}
    assert len(summary["paired_bootstrap"]) == 9
    assert len((output / "paired_bootstrap.csv").read_text(encoding="utf-8").splitlines()) == 901
    methodology = (output / "methodology_snapshot.md").read_text(encoding="utf-8")
    assert "not architecturally identical" in methodology
    assert "API-equivalent" in methodology
    assert "0 observed unsafe errors" in methodology
    publication = (output / "summary.md").read_text(encoding="utf-8")
    assert "≥90% confidence error" in publication
    assert "Persistent failure handling" in publication
    assert "Repeatability flip rate" in publication
    assert "Normalized cost / 1k cases" in publication
