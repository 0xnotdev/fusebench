"""FuseBench command-line interface."""

from pathlib import Path
from typing import Annotated

import typer

from fusebench.benchmark.commands import execute_dev_evaluation, execute_preflight
from fusebench.benchmark.fairness import (
    build_mechanical_fairness_audit,
    write_mechanical_fairness_audit,
)
from fusebench.benchmark.freeze import (
    FAIRNESS_AUDIT,
    create_freeze,
)
from fusebench.benchmark.freeze import (
    verify_freeze as verify_frozen_experiment,
)

app = typer.Typer(no_args_is_help=True, help="Run and analyze the FuseBench experiment.")
dataset_app = typer.Typer(help="Build deterministic benchmark datasets.")
freeze_app = typer.Typer(help="Create or verify an immutable benchmark freeze.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(freeze_app, name="freeze")


def _not_ready(checkpoint: str) -> None:
    typer.echo(f"This command is not available until {checkpoint} is complete.")
    raise typer.Exit(code=1)


@app.command()
def preflight(
    reuse_evidence: Annotated[
        bool,
        typer.Option(
            "--reuse-evidence",
            help="Skip new provider calls and validate existing sanitized evidence.",
        ),
    ] = False,
) -> None:
    """Validate the local environment and live providers."""

    report = execute_preflight(run_live=not reuse_evidence)
    typer.echo(f"Preflight {'PASS' if report.passed else 'FAIL'}")
    for name, check in report.checks.items():
        typer.echo(f"- {name}: {'PASS' if check.passed else 'FAIL'} ({check.detail})")
    if not report.passed:
        raise typer.Exit(code=1)


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
    run_id: Annotated[str, typer.Option(help="Resumable development run identifier.")] = (
        "dev-cp12-v1"
    ),
    seed: Annotated[int, typer.Option(help="Deterministic paired schedule seed.")] = 20260921,
    information_threshold: Annotated[
        float,
        typer.Option(help="Jev information-read selection threshold."),
    ] = 0.50,
) -> None:
    """Run the development set against selected systems."""

    selected = tuple(item.strip() for item in systems.split(",") if item.strip())
    try:
        result = execute_dev_evaluation(
            systems=selected,
            run_id=run_id,
            run_seed=seed,
            information_threshold=information_threshold,
        )
    except (RuntimeError, ValueError) as error:
        typer.echo(f"Development run blocked: {error}")
        raise typer.Exit(code=1) from error
    typer.echo(
        f"Development run {result['run_id']}: "
        f"{result['completed']}/{result['scheduled']} auditable records"
    )
    if result["stopped_for_usage_limit"]:
        typer.echo("Stopped safely at a provider usage or budget limit; rerun to resume.")


@freeze_app.command("create")
def freeze_create() -> None:
    """Create the frozen test set and experiment manifest."""

    try:
        manifest = create_freeze(Path("."))
    except (RuntimeError, ValueError) as error:
        typer.echo(f"Freeze creation failed: {error}")
        raise typer.Exit(code=1) from error
    typer.echo(
        "Frozen 240 test cases with SHA-256 "
        f"{manifest['dataset_sha256']} and 50 preregistered repeatability cases."
    )


@freeze_app.command("audit")
def freeze_audit() -> None:
    """Run the final mechanical fairness audit without provider calls."""

    try:
        report = build_mechanical_fairness_audit(Path("."))
        write_mechanical_fairness_audit(report, FAIRNESS_AUDIT)
    except (RuntimeError, ValueError, AssertionError) as error:
        typer.echo(f"Mechanical fairness audit failed: {error}")
        raise typer.Exit(code=1) from error
    typer.echo("Mechanical fairness audit PASS (0 provider calls; 0 test inference calls).")


@freeze_app.command("verify")
def freeze_verify() -> None:
    """Verify benchmark-critical hashes against the freeze manifest."""

    report = verify_frozen_experiment(Path("."))
    typer.echo(
        f"Freeze verifier {'PASS' if report['passed'] else 'FAIL'}: "
        f"{report.get('critical_file_count', 0)} critical files, "
        f"{report.get('case_count', 0)} cases."
    )
    for error in report["errors"]:
        typer.echo(f"- {error}")
    if not report["passed"]:
        raise typer.Exit(code=1)


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
