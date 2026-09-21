from typer.testing import CliRunner

from fusebench.benchmark.preflight import PreflightCheck, PreflightReport
from fusebench.cli import app


def test_cli_help_lists_preflight_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "preflight" in result.stdout


def test_preflight_command_writes_and_reports_passing_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        "fusebench.cli.execute_preflight",
        lambda run_live: PreflightReport(
            passed=True,
            checks={"mock": PreflightCheck(passed=True, detail="ok")},
        ),
    )

    result = CliRunner().invoke(app, ["preflight"])

    assert result.exit_code == 0
    assert "PASS" in result.stdout


def test_dev_run_command_executes_both_systems(monkeypatch) -> None:
    captured = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": kwargs["run_id"],
            "completed": 120,
            "scheduled": 120,
            "stopped_for_usage_limit": False,
        }

    monkeypatch.setattr("fusebench.cli.execute_dev_evaluation", fake_execute)

    result = CliRunner().invoke(
        app,
        ["dev-run", "--systems", "terra_only,terra_jev", "--run-id", "unit-dev"],
    )

    assert result.exit_code == 0
    assert "120/120" in result.stdout
    assert captured["systems"] == ("terra_only", "terra_jev")


def test_freeze_verify_reports_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        "fusebench.cli.verify_frozen_experiment",
        lambda root: {
            "passed": True,
            "errors": [],
            "critical_file_count": 123,
            "case_count": 240,
        },
    )

    result = CliRunner().invoke(app, ["freeze", "verify"])

    assert result.exit_code == 0
    assert "PASS" in result.stdout
    assert "240 cases" in result.stdout
