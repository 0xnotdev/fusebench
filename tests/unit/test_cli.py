from typer.testing import CliRunner

from fusebench.cli import app


def test_cli_help_lists_preflight_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "preflight" in result.stdout


def test_unimplemented_checkpoint_command_fails_actionably() -> None:
    result = CliRunner().invoke(app, ["preflight"])

    assert result.exit_code == 1
    assert "CP-12" in result.stdout
