"""User-facing CP-12 preflight and development-run orchestration."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fusebench.agents.responder import SharedTerraResponder
from fusebench.agents.terra_jev import DEFAULT_INFORMATION_THRESHOLD, TerraJevAgent
from fusebench.agents.terra_only import TerraOnlyAgent
from fusebench.benchmark.budget import JevBudget
from fusebench.benchmark.manifest import build_dev_manifest, write_dev_manifest
from fusebench.benchmark.preflight import (
    PreflightReport,
    evaluate_preflight,
    write_preflight_report,
)
from fusebench.benchmark.recorder import RunRecorder
from fusebench.benchmark.runner import BenchmarkRunner
from fusebench.config import get_settings
from fusebench.dataset.validation import canonical_json, load_cases_jsonl
from fusebench.metrics.report import generate_analysis
from fusebench.plots import generate_headline_plots
from fusebench.providers.codex_app_server import CodexAppServerProvider
from fusebench.providers.isolation import CaseSandboxManager
from fusebench.providers.typesafe_jev import TypeSafeJevProvider

DEV_SEED = 20260921


def _pytest(paths: tuple[str, ...], *, live: bool) -> bool:
    command = [sys.executable, "-m", "pytest", "-o", "addopts=", *paths, "-q"]
    if live:
        command.extend(("-m", "live"))
    completed = subprocess.run(command, check=False)
    return completed.returncode == 0


def _codex_version(executable: str | None) -> str:
    if executable is None:
        return ""
    completed = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def execute_preflight(*, run_live: bool) -> PreflightReport:
    """Run or reuse provider evidence, validate the simulator, and persist the gate."""

    settings = get_settings()
    artifact_dir = settings.fusebench_artifact_dir
    preflight_dir = artifact_dir / "preflight"
    live_ok = True
    if run_live:
        live_ok = _pytest(
            (
                "tests/contract/test_typesafe_live.py",
                "tests/contract/test_codex_app_server_live.py",
                "tests/contract/test_codex_isolation_live.py",
            ),
            live=True,
        )
    simulator_ok = _pytest(
        (
            "tests/unit/simulator",
            "tests/integration/test_simulator_replay.py",
        ),
        live=False,
    )
    codex = shutil.which("codex")
    report = evaluate_preflight(
        artifact_dir=artifact_dir,
        codex_evidence=preflight_dir / "codex-contract.json",
        typesafe_evidence=preflight_dir / "typesafe-contract.json",
        isolation_evidence=preflight_dir / "isolation.json",
        test_dataset=Path("data/test/cases.jsonl"),
        typesafe_key_present=bool(settings.typesafe_api_key),
        codex_executable=codex,
        live_contracts_passed=live_ok,
        simulator_contracts_passed=simulator_ok,
        codex_version=_codex_version(codex),
    )
    write_preflight_report(report, preflight_dir / "report.json")
    return report


def execute_dev_evaluation(
    *,
    systems: tuple[str, ...],
    run_id: str,
    run_seed: int = DEV_SEED,
    information_threshold: float = DEFAULT_INFORMATION_THRESHOLD,
) -> dict[str, Any]:
    """Run or safely resume the paired 60-case live development evaluation."""

    return asyncio.run(
        _execute_dev_evaluation(
            systems=systems,
            run_id=run_id,
            run_seed=run_seed,
            information_threshold=information_threshold,
        )
    )


async def _execute_dev_evaluation(
    *,
    systems: tuple[str, ...],
    run_id: str,
    run_seed: int,
    information_threshold: float,
) -> dict[str, Any]:
    if systems != ("terra_only", "terra_jev"):
        raise ValueError("CP-12 requires exactly terra_only,terra_jev")
    settings = get_settings()
    if not settings.typesafe_api_key:
        raise RuntimeError("TYPESAFE_API_KEY is required for the live development run")
    preflight_path = settings.fusebench_artifact_dir / "preflight" / "report.json"
    if not preflight_path.is_file():
        raise RuntimeError("run `uv run fusebench preflight` before the development run")
    preflight = PreflightReport.model_validate_json(
        preflight_path.read_text(encoding="utf-8")
    )
    if not preflight.passed:
        raise RuntimeError("development run requires a passing preflight")

    cases_path = Path("data/dev/cases.jsonl")
    cases = load_cases_jsonl(cases_path)
    if len(cases) != 60:
        raise RuntimeError("CP-12 requires the complete 60-case development set")

    provider = await CodexAppServerProvider.start(turn_timeout_seconds=120.0)
    try:
        codex_version = provider.codex_user_agent or "unknown"
        expected_versions = {
            "terra": provider.model,
            "codex": codex_version,
            "jev": settings.jev_model,
            "response_terra": provider.model,
            "response_codex": codex_version,
        }
        recorder = RunRecorder(
            settings.fusebench_artifact_dir / "runs",
            run_id,
            secrets=(settings.typesafe_api_key,),
            provider_versions=expected_versions,
        )
        manifest = build_dev_manifest(
            dev_dataset=cases_path,
            critical_paths=_critical_dev_paths(),
            test_dataset=Path("data/test/cases.jsonl"),
            run_seed=run_seed,
            information_threshold=information_threshold,
            terra_model=provider.model,
            jev_model=settings.jev_model,
            tool_protocol=provider.tool_protocol,
        )
        write_dev_manifest(manifest, recorder.run_dir / "dev_manifest.json")

        jev = TypeSafeJevProvider.from_api_key(
            api_key=settings.typesafe_api_key,
            model=settings.jev_model,
            budget=JevBudget(
                settings.fusebench_artifact_dir / "budget" / f"{run_id}-jev.json",
                hard_cap_usd=settings.jev_hard_cap_usd,
            ),
        )
        sandbox_manager = CaseSandboxManager(
            settings.fusebench_artifact_dir / "case_sandboxes"
        )
        runner = BenchmarkRunner(
            cases=cases,
            agents={
                "terra_only": TerraOnlyAgent(
                    provider=provider,
                    policy_text=_policy_text(),
                    sandbox_manager=sandbox_manager,
                ),
                "terra_jev": TerraJevAgent(
                    provider=jev,
                    policy_text=_policy_text(),
                    information_threshold=information_threshold,
                ),
            },
            recorder=recorder,
            preflight=preflight,
            run_seed=run_seed,
            responder=SharedTerraResponder(
                provider=provider,
                sandbox_manager=sandbox_manager,
            ),
        )
        run_summary = await runner.run()
        records = recorder.load_records()
        analysis_dir = settings.fusebench_artifact_dir / "analysis" / run_id
        plots: tuple[Path, ...] = ()
        if len(records) == 120 and not run_summary.stopped_for_usage_limit:
            generate_analysis(
                records,
                analysis_dir,
                bootstrap_samples=10_000,
                bootstrap_seed=run_seed,
            )
            plots = generate_headline_plots(analysis_dir)
        result = {
            "run_id": run_id,
            "scheduled": run_summary.scheduled,
            "completed": len(records),
            "completed_this_invocation": run_summary.completed,
            "skipped": run_summary.skipped,
            "stopped_for_usage_limit": run_summary.stopped_for_usage_limit,
            "record_checksums_verified": False,
            "analysis_dir": str(analysis_dir.resolve()) if plots else None,
            "plots": [str(path.resolve()) for path in plots],
            "provider_versions": expected_versions,
            "information_threshold": information_threshold,
            "run_seed": run_seed,
        }
        (recorder.run_dir / "dev_summary.json").write_text(
            canonical_json(result) + "\n", encoding="utf-8"
        )
        recorder.refresh_checksums()
        result["record_checksums_verified"] = recorder.verify_checksums()
        (recorder.run_dir / "dev_summary.json").write_text(
            canonical_json(result) + "\n", encoding="utf-8"
        )
        recorder.refresh_checksums()
        return result
    finally:
        await provider.close()


def _policy_text() -> str:
    return Path("src/fusebench/policy/policy.md").read_text(encoding="utf-8")


def _critical_dev_paths() -> tuple[Path, ...]:
    paths = {
        Path("spec(4).md"),
        Path("pyproject.toml"),
        *Path("src/fusebench").rglob("*.py"),
        *Path("src/fusebench").rglob("*.md"),
        *Path("prompts").glob("*.md"),
    }
    return tuple(sorted(paths, key=lambda path: path.as_posix()))
