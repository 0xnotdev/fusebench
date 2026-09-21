"""Pre-freeze environment and sanitized live-contract gate evaluation."""

import importlib.util
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fusebench.dataset.validation import canonical_json


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    detail: str


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    checks: dict[str, PreflightCheck]
    generated_at: str = ""
    python_version: str = ""


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def evaluate_preflight(
    *,
    artifact_dir: Path,
    codex_evidence: Path,
    typesafe_evidence: Path,
    isolation_evidence: Path,
    test_dataset: Path,
    typesafe_key_present: bool,
    codex_executable: str | None,
    live_contracts_passed: bool = True,
    simulator_contracts_passed: bool = True,
    codex_version: str = "",
) -> PreflightReport:
    """Evaluate current sanitized evidence without making provider calls."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    probe = artifact_dir / ".write-probe"
    writable = True
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        writable = False
    codex = _load(codex_evidence)
    typesafe = _load(typesafe_evidence)
    isolation = _load(isolation_evidence)
    packages = ("pydantic", "typesafe_sdk", "numpy", "scipy", "pandas", "matplotlib")
    packages_ok = all(importlib.util.find_spec(name) is not None for name in packages)
    checks = {
        "python": PreflightCheck(
            passed=sys.version_info >= (3, 11), detail=platform.python_version()
        ),
        "dependencies": PreflightCheck(
            passed=packages_ok, detail="required packages importable"
        ),
        "artifact_writes": PreflightCheck(
            passed=writable, detail=str(artifact_dir.resolve())
        ),
        "codex_executable": PreflightCheck(
            passed=bool(codex_executable),
            detail=(
                f"{codex_executable or 'missing'}; {codex_version or 'version unavailable'}"
            ),
        ),
        "live_contract_execution": PreflightCheck(
            passed=live_contracts_passed,
            detail="Codex, TypeSafe, and isolation live contract suite",
        ),
        "codex_contract": PreflightCheck(
            passed=(
                codex.get("model") == "gpt-5.6-terra"
                and codex.get("effort") == "medium"
                and codex.get("selected_tool_protocol") == "dynamic_tools"
                and codex.get("dynamic_tool_called") is True
                and bool(codex.get("usage", {}).get("input_tokens"))
            ),
            detail="exact Terra/medium dynamic-tools contract",
        ),
        "typesafe_key": PreflightCheck(
            passed=typesafe_key_present, detail="configured" if typesafe_key_present else "missing"
        ),
        "typesafe_contract": PreflightCheck(
            passed=(
                str(typesafe.get("model", "")).startswith("jev-")
                and typesafe.get("requested_model") == typesafe.get("model")
                and typesafe.get("concrete_model_accepted") is True
                and bool(typesafe.get("usage", {}).get("input_tokens"))
            ),
            detail=str(typesafe.get("model", "missing")),
        ),
        "filesystem_isolation": PreflightCheck(
            passed=(
                isolation.get("passed") is True
                and isolation.get("built_in_execution_disabled") is True
                and isolation.get("evaluation", {}).get("passed") is True
            ),
            detail="canary and benchmark-path attack evidence",
        ),
        "simulator_contracts": PreflightCheck(
            passed=simulator_contracts_passed,
            detail="read, action side-effect, replay, and oracle agreement suite",
        ),
        "test_dataset_absent": PreflightCheck(
            passed=not test_dataset.exists(), detail=str(test_dataset.resolve())
        ),
    }
    return PreflightReport(
        passed=all(check.passed for check in checks.values()),
        checks=checks,
        generated_at=datetime.now(UTC).isoformat(),
        python_version=platform.python_version(),
    )


def write_preflight_report(report: PreflightReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")
