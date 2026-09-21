"""FuseBench command-line interface."""

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, help="Run and analyze the FuseBench experiment.")
dataset_app = typer.Typer(help="Build deterministic benchmark datasets.")
freeze_app = typer.Typer(help="Create or verify an immutable benchmark freeze.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(freeze_app, name="freeze")


def _not_ready(checkpoint: str) -> None:
    typer.echo(f"This command is not available until {checkpoint} is complete.")
    raise typer.Exit(code=1)


@app.command()
def preflight() -> None:
    """Validate the local environment and live providers."""

    _not_ready("CP-12")


@dataset_app.command("build-dev")
def build_dev(
    seed: Annotated[int, typer.Option(help="Deterministic development dataset seed.")] = 20260921,
) -> None:
    """Build the deterministic development dataset."""

    from fusebench.dataset.generator import build_dev_dataset
    from fusebench.dataset.validation import write_dev_dataset

    cases = build_dev_dataset(seed)
    manifest = write_dev_dataset(cases, Path("data/dev"), seed)
    typer.echo(
        f"Wrote {manifest['case_count']} development cases "
        f"with SHA-256 {manifest['dataset_sha256']}"
    )


@app.command("dev-run")
def dev_run(
    systems: Annotated[str, typer.Option(help="Comma-separated system identifiers.")] = (
        "terra_only,terra_jev"
    ),
) -> None:
    """Run the development set against selected systems."""

    del systems
    _not_ready("CP-12")


@freeze_app.command("create")
def freeze_create() -> None:
    """Create the frozen test set and experiment manifest."""

    _not_ready("CP-13; explicit user authorization is required")


@freeze_app.command("verify")
def freeze_verify() -> None:
    """Verify benchmark-critical hashes against the freeze manifest."""

    _not_ready("CP-13; explicit user authorization is required")


@app.command("run")
def run_benchmark(
    split: Annotated[str, typer.Option()] = "test",
    systems: Annotated[str, typer.Option()] = "terra_only,terra_jev",
    run_id: Annotated[str, typer.Option()] = "primary-v1",
) -> None:
    """Run a frozen benchmark split."""

    del split, systems, run_id
    _not_ready("CP-14")


@app.command()
def repeatability(run_id: Annotated[str, typer.Option()] = "repeatability-v1") -> None:
    """Run the frozen repeatability experiment."""

    del run_id
    _not_ready("CP-15")


@app.command()
def analyze(run_id: Annotated[str, typer.Option()] = "primary-v1") -> None:
    """Analyze frozen normalized records."""

    del run_id
    _not_ready("CP-16")


@app.command()
def plot(run_id: Annotated[str, typer.Option()] = "primary-v1") -> None:
    """Generate benchmark plots."""

    del run_id
    _not_ready("CP-16")


@app.command()
def report(run_id: Annotated[str, typer.Option()] = "primary-v1") -> None:
    """Generate publication-ready benchmark reports."""

    del run_id
    _not_ready("CP-16")


if __name__ == "__main__":
    app()
