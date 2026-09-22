"""Operational CP-14 resume launcher; imports only the frozen benchmark implementation."""

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from fusebench.agents.responder import SharedTerraResponder
from fusebench.agents.terra_jev import TerraJevAgent
from fusebench.agents.terra_only import TerraOnlyAgent
from fusebench.benchmark.budget import JevBudget
from fusebench.benchmark.freeze import verify_freeze
from fusebench.benchmark.preflight import PreflightReport
from fusebench.benchmark.recorder import RunRecorder
from fusebench.benchmark.runner import BenchmarkRunner
from fusebench.benchmark.scheduler import build_paired_schedule
from fusebench.config import get_settings
from fusebench.dataset.validation import canonical_json, load_cases_jsonl
from fusebench.providers.codex_app_server import CodexAppServerProvider
from fusebench.providers.isolation import CaseSandboxManager
from fusebench.providers.typesafe_jev import TypeSafeJevProvider

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "primary-v1"
RUN_SEED = 8193800051343574363
EXPECTED_HEAD = "c3f6b66b0b31c7fa8f1ecc60dd01162b0ab0bf99"


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected object: {path}")
    return value


def write_object(path: Path, value: dict) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


async def run() -> int:
    verification = verify_freeze(ROOT)
    if not verification["passed"]:
        raise RuntimeError(f"freeze verification failed: {verification['errors']}")
    if git("rev-parse", "HEAD") != EXPECTED_HEAD:
        raise RuntimeError("HEAD left the frozen commit")
    if git("rev-list", "-n", "1", "v1.0.1-freeze") != EXPECTED_HEAD:
        raise RuntimeError("freeze tag moved")
    if git("diff", "--name-only") or git("diff", "--cached", "--name-only"):
        raise RuntimeError("tracked working tree is dirty")

    settings = get_settings()
    if not settings.typesafe_api_key:
        raise RuntimeError("TYPESAFE_API_KEY is missing")
    if (
        settings.terra_model != "gpt-5.6-terra"
        or settings.terra_reasoning_effort != "medium"
        or settings.terra_tool_protocol != "dynamic_tools"
        or settings.jev_model != "jev-1.13.0"
        or settings.jev_hard_cap_usd != 1.0
    ):
        raise RuntimeError("runtime settings drift")
    codex_version = subprocess.run(
        ["codex", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if codex_version != "codex-cli 0.155.0-alpha.9.2":
        raise RuntimeError(f"Codex version drift: {codex_version}")

    freeze_path = ROOT / "artifacts/freeze/manifest.json"
    frozen = read_object(freeze_path)
    cases = load_cases_jsonl(ROOT / "data/test/cases.jsonl")
    schedule = build_paired_schedule(
        tuple(case.visible.case_id for case in cases), seed=RUN_SEED
    )
    schedule_payload = [item.model_dump(mode="json") for item in schedule]
    schedule_sha = sha256(canonical_json(schedule_payload).encode("utf-8")).hexdigest()
    stored_schedule = read_object(ROOT / "artifacts/runs/primary-v1/schedule.json")
    if (
        stored_schedule.get("executions") != schedule_payload
        or stored_schedule.get("sha256") != schedule_sha
    ):
        raise RuntimeError("stored primary schedule drift")

    preflight = PreflightReport.model_validate_json(
        (ROOT / "artifacts/preflight/report.json").read_text(encoding="utf-8")
    )
    if not preflight.passed:
        raise RuntimeError("frozen preflight is not passing")
    budget = JevBudget(ROOT / "artifacts/budget/jev_usage.json", hard_cap_usd=1.0)
    budget.ensure_can_spend(1)

    provider = await CodexAppServerProvider.start(turn_timeout_seconds=120.0)
    try:
        terra_config = frozen["terra_codex_configuration"]
        if (
            provider.model != "gpt-5.6-terra"
            or provider.effort != "medium"
            or provider.tool_protocol != "dynamic_tools"
            or provider.codex_user_agent != terra_config["codex_user_agent"]
        ):
            raise RuntimeError("live Codex configuration drift")

        versions = {
            "terra": "gpt-5.6-terra",
            "codex": terra_config["codex_user_agent"],
            "jev": "jev-1.13.0",
            "response_terra": "gpt-5.6-terra",
            "response_codex": terra_config["codex_user_agent"],
        }
        recorder = RunRecorder(
            ROOT / "artifacts/runs",
            RUN_ID,
            secrets=(settings.typesafe_api_key,),
            provider_versions=versions,
            raw_root=ROOT / "artifacts/raw",
        )
        primary_path = ROOT / "artifacts/runs/primary-v1/primary_manifest.json"
        primary = read_object(primary_path)
        expected = {
            "run_id": RUN_ID,
            "split": "test",
            "systems": ["terra_only", "terra_jev"],
            "run_seed": RUN_SEED,
            "dataset_sha256": frozen["dataset_sha256"],
            "freeze_manifest_sha256": sha256(freeze_path.read_bytes()).hexdigest(),
            "source_tag": "v1.0.1-freeze",
            "schedule_sha256": schedule_sha,
            "information_threshold": 0.5,
        }
        for key, value in expected.items():
            if primary.get(key) != value:
                raise RuntimeError(f"primary manifest drift: {key}")
        primary["invocation_count"] = int(primary["invocation_count"]) + 1
        primary["resumption_count"] = int(primary["invocation_count"]) - 1
        primary["last_started_at"] = datetime.now(UTC).isoformat()
        write_object(primary_path, primary)

        jev = TypeSafeJevProvider.from_api_key(
            api_key=settings.typesafe_api_key,
            model="jev-1.13.0",
            budget=budget,
            timeout_seconds=30.0,
        )
        jev.reported_model = "jev-1.13.0"
        sandboxes = CaseSandboxManager(ROOT / "artifacts/case_sandboxes")
        policy = (ROOT / "src/fusebench/policy/policy.md").read_text(encoding="utf-8")
        runner = BenchmarkRunner(
            cases=cases,
            agents={
                "terra_only": TerraOnlyAgent(
                    provider=provider,
                    policy_text=policy,
                    sandbox_manager=sandboxes,
                ),
                "terra_jev": TerraJevAgent(
                    provider=jev,
                    policy_text=policy,
                    information_threshold=0.5,
                ),
            },
            recorder=recorder,
            preflight=preflight,
            run_seed=RUN_SEED,
            responder=SharedTerraResponder(
                provider=provider,
                sandbox_manager=sandboxes,
            ),
        )
        print(
            f"RESUME PRECHECK PASS existing={len(recorder.completed_keys)} "
            f"invocation={primary['invocation_count']}",
            flush=True,
        )
        summary = await runner.run()
        recorder.refresh_checksums()
        state = {
            "invocation_count": primary["invocation_count"],
            "completed_total": len(recorder.completed_keys),
            "completed_this_invocation": summary.completed,
            "skipped_existing": summary.skipped,
            "scheduled": summary.scheduled,
            "stopped_for_usage_limit": summary.stopped_for_usage_limit,
            "ended_at": datetime.now(UTC).isoformat(),
            "checksums_verified": recorder.verify_checksums(),
        }
        write_object(
            ROOT
            / f"artifacts/runs/primary-v1/invocation_{primary['invocation_count']:03d}.json",
            state,
        )
        recorder.refresh_checksums()
        print("INVOCATION_RESULT " + canonical_json(state), flush=True)
        return 0 if len(recorder.completed_keys) == 480 else 2
    finally:
        await provider.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
