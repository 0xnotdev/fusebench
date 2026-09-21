from pathlib import Path

import pytest

from fusebench.providers import isolation
from fusebench.providers.codex_app_server import (
    FUSEBENCH_PERMISSION_PROFILE,
    codex_app_server_command,
)
from fusebench.providers.isolation import (
    CaseSandboxManager,
    IsolationError,
    evaluate_isolation_probe,
)


def test_case_sandbox_is_unique_empty_and_under_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts" / "case_sandboxes"
    manager = CaseSandboxManager(root)

    boundary = manager.create("run-1", "case-1")

    assert boundary.case_sandbox == (root / "run-1" / "case-1").resolve()
    assert list(boundary.case_sandbox.iterdir()) == []
    assert boundary.approval_policy == "never"
    assert boundary.permission_profile == FUSEBENCH_PERMISSION_PROFILE
    assert boundary.runtime_workspace_roots == (boundary.case_sandbox,)
    assert boundary.network_enabled is False
    assert boundary.built_in_execution_disabled is True


def test_app_server_command_disables_non_benchmark_tool_surfaces() -> None:
    command = codex_app_server_command()
    disabled = {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--disable"
    }

    assert {
        "shell_tool",
        "unified_exec",
        "view_image",
        "browser_use",
        "browser_use_external",
        "computer_use",
        "apps",
        "plugins",
        "skill_search",
        "workspace_dependencies",
        "multi_agent",
    }.issubset(disabled)


@pytest.mark.parametrize(
    ("run_id", "case_id"),
    [
        ("../escape", "case"),
        ("run", "../escape"),
        ("run/subdir", "case"),
        ("run", "case\\subdir"),
        (".", "case"),
        ("run", ".."),
    ],
)
def test_case_sandbox_rejects_path_escape(
    tmp_path: Path,
    run_id: str,
    case_id: str,
) -> None:
    manager = CaseSandboxManager(tmp_path / "artifacts" / "case_sandboxes")

    with pytest.raises(IsolationError):
        manager.create(run_id, case_id)


def test_case_sandbox_rejects_reuse_and_copied_benchmark_files(tmp_path: Path) -> None:
    root = tmp_path / "artifacts" / "case_sandboxes"
    existing = root / "run" / "case"
    existing.mkdir(parents=True)
    (existing / "oracle.py").write_text("forbidden", encoding="utf-8")
    manager = CaseSandboxManager(root)

    with pytest.raises(IsolationError, match="already exists"):
        manager.create("run", "case")


def test_case_sandbox_fresh_attempt_uses_next_empty_suffix(tmp_path: Path) -> None:
    manager = CaseSandboxManager(tmp_path / "artifacts" / "case_sandboxes")

    first = manager.create_fresh("run", "case")
    second = manager.create_fresh("run", "case")

    assert first.case_sandbox.name == "case-a0001"
    assert second.case_sandbox.name == "case-a0002"
    assert list(second.case_sandbox.iterdir()) == []


def test_case_sandbox_rejects_reparse_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts" / "case_sandboxes"
    manager = CaseSandboxManager(root)
    original = isolation._is_reparse_point

    def fake_reparse(path: Path) -> bool:
        return path.name == "run" or original(path)

    monkeypatch.setattr(isolation, "_is_reparse_point", fake_reparse)

    with pytest.raises(IsolationError, match="reparse"):
        manager.create("run", "case")


def test_probe_evaluation_redacts_secrets_and_detects_leaks() -> None:
    secret = "canary-very-secret"
    marker = "oracle-private-marker"
    events = [
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "commandExecution",
                    "status": "failed",
                    "aggregatedOutput": "access denied",
                }
            },
        }
    ]

    safe = evaluate_isolation_probe(
        final_text='{"canary":null,"status":"denied"}',
        events=events,
        canary_secret=secret,
        forbidden_markers=(marker,),
    )
    leaked = evaluate_isolation_probe(
        final_text=f'{{"canary":"{secret}","status":"read"}}',
        events=events,
        canary_secret=secret,
        forbidden_markers=(marker,),
    )

    assert safe.passed is True
    assert safe.command_attempted is True
    assert leaked.passed is False
    assert leaked.canary_leaked is True
    assert secret not in safe.model_dump_json()
    assert secret not in leaked.model_dump_json()
