"""CP-13 freeze creation and integrity verification."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from fusebench.benchmark.fairness import ACCEPTED_CP12_COMMIT
from fusebench.benchmark.manifest import file_sha256
from fusebench.config import get_settings
from fusebench.constants import BENCHMARK_VERSION, SPEC_VERSION
from fusebench.dataset.freeze import (
    REPEATABILITY_CATEGORIES,
    create_test_dataset,
    select_repeatability_cases,
    write_repeatability_selection,
)
from fusebench.dataset.validation import (
    canonical_json,
    load_cases_jsonl,
    validate_test_dataset,
)
from fusebench.providers.codex_app_server import (
    FUSEBENCH_PERMISSION_PROFILE,
    TERRA_EFFORT,
    TERRA_MODEL,
    TERRA_TOOL_PROTOCOL,
    codex_app_server_command,
)

FREEZE_MANIFEST = Path("artifacts/freeze/manifest.json")
FAIRNESS_AUDIT = Path("artifacts/freeze/fairness-audit.json")
ENVIRONMENT_SNAPSHOT = Path("artifacts/freeze/environment.json")
DEV_TUNING_LOG = Path("artifacts/freeze/dev_tuning_log.md")
TEST_CASES = Path("data/test/cases.jsonl")
TEST_MANIFEST = Path("data/test/manifest.json")
REPEATABILITY_IDS = Path("data/repeatability/selected_case_ids.json")
EXPERIMENT = Path("EXPERIMENT.md")
FREEZE_TAG = "v1.0.1-freeze"
INFORMATION_THRESHOLD = 0.50


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def _packages() -> list[dict[str, str]]:
    values = {
        (
            str(distribution.metadata.get("Name") or "unknown"),
            distribution.version,
        )
        for distribution in importlib.metadata.distributions()
    }
    return [
        {"name": name, "version": version}
        for name, version in sorted(values, key=lambda item: (item[0].lower(), item[1]))
    ]


def _codex_cli_version() -> str:
    completed = subprocess.run(
        ["codex", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("codex --version failed during freeze snapshot")
    return completed.stdout.strip()


def build_environment_snapshot(root: Path) -> dict[str, Any]:
    """Capture the local package/environment state without secrets or provider calls."""

    return {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "implementation": platform.python_implementation(),
        "os_platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "timezone": str(datetime.now().astimezone().tzinfo),
        "codex_cli_version": _codex_cli_version(),
        "typesafe_sdk_version": importlib.metadata.version("typesafe-sdk"),
        "uv_lock_sha256": file_sha256(root / "uv.lock"),
        "pyproject_sha256": file_sha256(root / "pyproject.toml"),
        "packages": _packages(),
    }


def _experiment_text(*, dataset_sha256: str, source_commit: str) -> str:
    return f"""# FuseBench v1 preregistered experiment

Frozen at CP-13 under specification `{SPEC_VERSION}` and benchmark version
`{BENCHMARK_VERSION}`. Source commit: `{source_commit}`. Frozen test dataset SHA-256:
`{dataset_sha256}`.

## Primary research question

> For a bounded, policy-governed, tool-using agent workflow, does inserting Jev as the
> decision layer improve the reliability-calibration-efficiency tradeoff compared with
> allowing GPT-5.6 Terra to make the same decisions itself?

## Systems

- `terra_only`: Terra selects trusted reads and the scored terminal action.
- `terra_jev`: Jev selects trusted reads and the scored terminal action; Terra is used
  only for the shared, post-action customer response.

No other scored system is part of v1. Both systems receive the same policy semantics,
case semantics, trusted simulator, action tools, and post-action Terra responder.

## Primary metrics

- final action accuracy;
- unsafe autonomous action rate;
- end-to-end terminal success;
- risk/coverage.

## Secondary metrics

All other frozen metrics, including calibration, business loss, category breakdowns,
tool use, decision-path latency, decision-path normalized cost, full-system response
latency, paired statistics, adversarial behavior, persistent-failure behavior, and
repeatability. Decision-path latency and normalized decision cost exclude the shared
Terra responder; full-response latency and responder usage are retained separately.

## Dataset

- 60-case development set used only before freeze;
- 240-case frozen test set;
- exactly 30 cases in each of eight categories;
- exactly 48 cases for each of the five gold actions;
- deterministic scenario-first labels from the frozen oracle, with curated templates and
  seeded perturbations and no model-generated labels or messages.

The 50 repeatability cases are selected before inference by the frozen seeded procedure:
10 each from boundary, conflicting-evidence, adversarial, tool-failure, and multi-tool.

## Frozen configuration

- Terra: `gpt-5.6-terra`, reasoning effort `medium`, Codex dynamic tools, fresh isolated
  read-only/network-off thread per decision and response.
- Jev: requested and reported `jev-1.13.0`, `typesafe-sdk==0.7.0`, hard cap USD 1.00.
- Jev information-read threshold: `{INFORMATION_THRESHOLD:.2f}`.
- Mandatory shared pre-action safety read: `get_customer_risk(customer_id)` before an
  otherwise autonomous `REFUND` or `RESHIP`.

## Freeze statement

> No benchmark cases, policies, prompts, Jev questions, provider settings, thresholds,
> labels, or metric definitions will be modified after the frozen test set is evaluated.
> If a material bug is found, the benchmark version will be incremented and both systems
> will be rerun.

At creation of this preregistration, zero Terra or Jev inference calls had been made on
the frozen test set and no test outcomes had been observed.
"""


def _dev_tuning_text() -> str:
    return """# Pre-freeze development tuning and correction log

## Experimental tuning

No outcome-driven tuning was performed. The final Terra prompt, Jev questions, policy,
oracle, loss matrix, dataset definitions, metric definitions, provider settings, and Jev
information threshold remained unchanged after development results were inspected. The
frozen information threshold is 0.50.

## CP-03 pre-freeze specification correction

The original specification made `prior_exception_refunds_90d` and
`trusted_records_conflict` oracle-relevant without a permitted trusted read surface. Per
the user's explicit correction, v1.0.1 added `get_customer_risk(customer_id)` as the fifth
trusted read and made it mandatory before an otherwise autonomous `REFUND` or `RESHIP`.
The result may override that candidate to `ESCALATE` under the existing global policy.
The two hidden fields remain absent from `VisibleCase` and unrelated tool responses; no
oracle threshold or global safety rule changed. This was a specification bug fix, not an
experiment redesign, and occurred before test freeze.

## External-API accommodations

- Codex currently reports ambient effort on `thread/start`; FuseBench sends and validates
  `effort: medium` on every scored `turn/start`.
- On this Windows host, built-in execution, file, browser, app, plugin, skill, dependency,
  and multi-agent surfaces are disabled; only the five benchmark dynamic reads are exposed.
- TypeSafe's accepted concrete model is pinned to `jev-1.13.0`.

## Non-semantic CP-12 corrections

- Raw outputs were placed at the specified `artifacts/raw/<run_id>` root.
- Semantic invalid Terra outputs retain provider events and token usage.
"""


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _critical_paths(root: Path) -> tuple[Path, ...]:
    fixed = {
        root / ".env.example",
        root / ".python-version",
        root / "EXPERIMENT.md",
        root / "pyproject.toml",
        root / "README.md",
        root / "spec.md",
        root / "spec(4).md",
        root / "uv.lock",
        root / "data/dev/cases.jsonl",
        root / "data/dev/manifest.json",
        root / TEST_CASES,
        root / TEST_MANIFEST,
        root / REPEATABILITY_IDS,
        root / FAIRNESS_AUDIT,
        root / ENVIRONMENT_SNAPSHOT,
        root / DEV_TUNING_LOG,
        root / "artifacts/preflight/codex-contract.json",
        root / "artifacts/preflight/isolation.json",
        root / "artifacts/preflight/report.json",
        root / "artifacts/preflight/typesafe-contract.json",
    }
    discovered = {
        *root.joinpath("src/fusebench").rglob("*.py"),
        *root.joinpath("src/fusebench").rglob("*.md"),
        *root.joinpath("prompts").rglob("*.md"),
        *root.joinpath("schemas/codex").rglob("*.json"),
    }
    paths = fixed | discovered
    missing = sorted(path.relative_to(root).as_posix() for path in paths if not path.is_file())
    if missing:
        raise RuntimeError(f"benchmark-critical files are missing: {missing}")
    return tuple(sorted(paths, key=lambda path: path.relative_to(root).as_posix()))


def _critical_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in _critical_paths(root)
    }


def _tree_is_clean(root: Path) -> bool:
    return not _git(root, "diff", "--name-only") and not _git(
        root, "diff", "--cached", "--name-only"
    )


def create_freeze(
    root: Path = Path("."),
    *,
    test_seed: int | None = None,
    repeatability_seed: int | None = None,
    primary_run_seed: int | None = None,
) -> dict[str, Any]:
    """Create the complete CP-13 freeze without importing or calling model providers."""

    root = root.resolve()
    if not _tree_is_clean(root):
        raise RuntimeError("tracked working tree must be clean before freeze creation")
    if any((root / path).exists() for path in (TEST_CASES.parent, REPEATABILITY_IDS.parent)):
        raise RuntimeError("frozen test or repeatability directory already exists")
    if (root / FREEZE_MANIFEST).exists() or (root / EXPERIMENT).exists():
        raise RuntimeError("freeze artifacts already exist")

    fairness = _json(root / FAIRNESS_AUDIT)
    if (
        not fairness.get("passed")
        or fairness.get("dev_outcomes_read") is not False
        or fairness.get("provider_calls") != 0
        or fairness.get("test_inference_calls") != 0
        or fairness.get("baseline_commit") != ACCEPTED_CP12_COMMIT
    ):
        raise RuntimeError("a passing pre-dataset mechanical fairness audit is required")
    preflight = _json(root / "artifacts/preflight/report.json")
    if not preflight.get("passed"):
        raise RuntimeError("a passing pre-freeze provider/isolation preflight is required")

    source_commit = _git(root, "rev-parse", "HEAD")
    generated_test_seed = test_seed if test_seed is not None else secrets.randbits(64)
    generated_repeatability_seed = (
        repeatability_seed if repeatability_seed is not None else secrets.randbits(64)
    )
    generated_primary_seed = (
        primary_run_seed if primary_run_seed is not None else secrets.randbits(64)
    )

    cases, dataset_manifest = create_test_dataset(
        generated_test_seed,
        root / TEST_CASES.parent,
    )
    selected = select_repeatability_cases(cases, seed=generated_repeatability_seed)
    write_repeatability_selection(selected, root / REPEATABILITY_IDS)
    _write_text(
        root / EXPERIMENT,
        _experiment_text(
            dataset_sha256=str(dataset_manifest["dataset_sha256"]),
            source_commit=source_commit,
        ),
    )
    _write_text(root / DEV_TUNING_LOG, _dev_tuning_text())
    environment = build_environment_snapshot(root)
    (root / ENVIRONMENT_SNAPSHOT).write_text(
        canonical_json(environment) + "\n", encoding="utf-8"
    )

    codex_evidence = _json(root / "artifacts/preflight/codex-contract.json")
    jev_evidence = _json(root / "artifacts/preflight/typesafe-contract.json")
    settings = get_settings()
    critical_files = _critical_hashes(root)
    critical_digest = sha256(canonical_json(critical_files).encode("utf-8")).hexdigest()
    repeatability_sha = file_sha256(root / REPEATABILITY_IDS)
    manifest: dict[str, Any] = {
        "manifest_format": "fusebench-freeze-v1",
        "spec_version": SPEC_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_git_commit": source_commit,
        "accepted_cp12_commit": ACCEPTED_CP12_COMMIT,
        "intended_freeze_tag": FREEZE_TAG,
        "git_remote": _git(root, "remote", "get-url", "origin"),
        "test_seed": generated_test_seed,
        "repeatability_selection_seed": generated_repeatability_seed,
        "primary_run_seed": generated_primary_seed,
        "dataset_path": TEST_CASES.as_posix(),
        "dataset_sha256": dataset_manifest["dataset_sha256"],
        "test_manifest_sha256": file_sha256(root / TEST_MANIFEST),
        "repeatability_selection_path": REPEATABILITY_IDS.as_posix(),
        "repeatability_selection_sha256": repeatability_sha,
        "repeatability_selection_count": len(selected),
        "repeatability_category_counts": {
            category: 10 for category in REPEATABILITY_CATEGORIES
        },
        "information_threshold": INFORMATION_THRESHOLD,
        "terra_codex_configuration": {
            "model": TERRA_MODEL,
            "reasoning_effort": TERRA_EFFORT,
            "tool_protocol": TERRA_TOOL_PROTOCOL,
            "permission_profile": FUSEBENCH_PERMISSION_PROFILE,
            "provider_fallback": False,
            "thread_ephemeral": True,
            "network_access": False,
            "dynamic_read_tools": 5,
            "app_server_command": list(codex_app_server_command()),
            "codex_cli_version": environment["codex_cli_version"],
            "codex_user_agent": codex_evidence["codex_user_agent"],
            "stable_schema_sha256": codex_evidence["stable_schema_sha256"],
            "experimental_schema_sha256": codex_evidence[
                "experimental_schema_sha256"
            ],
            "shared_responder_excluded_from_decision_metrics": True,
        },
        "jev_configuration": {
            "requested_model": settings.jev_model,
            "reported_model": jev_evidence["model"],
            "typesafe_sdk_version": environment["typesafe_sdk_version"],
            "hard_cap_usd": settings.jev_hard_cap_usd,
            "information_threshold": INFORMATION_THRESHOLD,
            "information_calls": 1,
            "terminal_calls": 1,
            "conditional_post_risk_terminal_call": 1,
        },
        "provider_versions": {
            "terra_model": codex_evidence["model"],
            "codex_user_agent": codex_evidence["codex_user_agent"],
            "codex_cli": environment["codex_cli_version"],
            "jev_requested": jev_evidence["requested_model"],
            "jev_reported": jev_evidence["model"],
            "typesafe_sdk": environment["typesafe_sdk_version"],
        },
        "policy_sha256": critical_files["src/fusebench/policy/policy.md"],
        "terra_prompt_sha256": critical_files["prompts/terra_agent.md"],
        "terra_response_prompt_sha256": critical_files["prompts/terra_response.md"],
        "jev_questions_sha256": critical_files["src/fusebench/jev/questions.py"],
        "tool_schema_sha256": critical_files["src/fusebench/contracts/tools.py"],
        "oracle_sha256": critical_files["src/fusebench/policy/oracle.py"],
        "loss_matrix_sha256": critical_files["src/fusebench/policy/loss.py"],
        "environment_path": ENVIRONMENT_SNAPSHOT.as_posix(),
        "environment_sha256": file_sha256(root / ENVIRONMENT_SNAPSHOT),
        "fairness_audit_path": FAIRNESS_AUDIT.as_posix(),
        "fairness_audit_sha256": file_sha256(root / FAIRNESS_AUDIT),
        "critical_files_sha256": critical_digest,
        "critical_files": critical_files,
        "test_inference_calls_at_freeze": 0,
        "test_outcomes_observed_at_freeze": False,
    }
    (root / FREEZE_MANIFEST).write_text(
        canonical_json(manifest) + "\n", encoding="utf-8"
    )
    verification = verify_freeze(root)
    if not verification["passed"]:
        raise RuntimeError(f"new freeze did not verify: {verification['errors']}")
    return manifest


def verify_freeze(root: Path = Path(".")) -> dict[str, Any]:
    """Re-hash and validate the complete frozen experiment without inference."""

    root = root.resolve()
    errors: list[str] = []
    try:
        manifest = _json(root / FREEZE_MANIFEST)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"passed": False, "errors": [f"freeze manifest unreadable: {error}"]}

    for relative, expected in manifest.get("critical_files", {}).items():
        path = root / relative
        if not path.is_file():
            errors.append(f"critical file missing: {relative}")
        elif file_sha256(path) != expected:
            errors.append(f"critical file drift: {relative}")
    actual_map = manifest.get("critical_files", {})
    actual_digest = sha256(canonical_json(actual_map).encode("utf-8")).hexdigest()
    if actual_digest != manifest.get("critical_files_sha256"):
        errors.append("critical file map digest mismatch")

    try:
        cases_path = root / str(manifest["dataset_path"])
        cases = load_cases_jsonl(cases_path)
        report = validate_test_dataset(cases)
        if file_sha256(cases_path) != manifest.get("dataset_sha256"):
            errors.append("test dataset SHA-256 mismatch")
        test_manifest = _json(root / TEST_MANIFEST)
        if test_manifest.get("dataset_sha256") != manifest.get("dataset_sha256"):
            errors.append("test manifest dataset SHA-256 mismatch")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"test dataset validation failed: {error}")
        report = None

    try:
        repeatability_path = root / str(manifest["repeatability_selection_path"])
        selected = json.loads(repeatability_path.read_text(encoding="utf-8"))
        if not isinstance(selected, list) or len(selected) != 50 or len(set(selected)) != 50:
            errors.append("repeatability selection is not 50 unique IDs")
        elif report is not None:
            by_id = {case.visible.case_id: case for case in cases}
            counts = {
                category: sum(
                    by_id.get(case_id) is not None
                    and by_id[case_id].category == category
                    for case_id in selected
                )
                for category in REPEATABILITY_CATEGORIES
            }
            if counts != {category: 10 for category in REPEATABILITY_CATEGORIES}:
                errors.append(f"repeatability category balance mismatch: {counts}")
        if file_sha256(repeatability_path) != manifest.get(
            "repeatability_selection_sha256"
        ):
            errors.append("repeatability selection SHA-256 mismatch")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"repeatability validation failed: {error}")

    try:
        fairness = _json(root / str(manifest["fairness_audit_path"]))
        if not fairness.get("passed") or fairness.get("test_inference_calls") != 0:
            errors.append("mechanical fairness audit is not passing and inference-free")
        if file_sha256(root / str(manifest["fairness_audit_path"])) != manifest.get(
            "fairness_audit_sha256"
        ):
            errors.append("mechanical fairness audit SHA-256 mismatch")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"fairness audit validation failed: {error}")

    if manifest.get("test_inference_calls_at_freeze") != 0:
        errors.append("freeze records nonzero test inference calls")
    if manifest.get("test_outcomes_observed_at_freeze") is not False:
        errors.append("freeze records observed test outcomes")
    if manifest.get("information_threshold") != INFORMATION_THRESHOLD:
        errors.append("frozen information threshold drift")
    if manifest.get("spec_version") != SPEC_VERSION:
        errors.append("specification version drift")
    if manifest.get("benchmark_version") != BENCHMARK_VERSION:
        errors.append("benchmark version drift")

    source_commit = str(manifest.get("source_git_commit", ""))
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if not source_commit or ancestor.returncode != 0:
        errors.append("recorded source commit is not an ancestor of HEAD")

    return {
        "passed": not errors,
        "errors": errors,
        "critical_file_count": len(manifest.get("critical_files", {})),
        "case_count": report.case_count if report is not None else 0,
        "dataset_sha256": manifest.get("dataset_sha256"),
        "repeatability_selection_sha256": manifest.get(
            "repeatability_selection_sha256"
        ),
        "test_inference_calls_at_freeze": manifest.get("test_inference_calls_at_freeze"),
    }
