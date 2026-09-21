"""Construction and redacted evaluation of Codex per-case isolation boundaries."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from fusebench.dataset.validation import canonical_json
from fusebench.providers.codex_app_server import FUSEBENCH_PERMISSION_PROFILE

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPARSE_POINT_ATTRIBUTE = 0x400


class IsolationError(RuntimeError):
    """A requested sandbox cannot satisfy the benchmark isolation boundary."""


class CaseIsolationBoundary(BaseModel):
    """Immutable effective isolation settings for one fresh case thread."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_sandbox: Path
    approval_policy: str = "never"
    permission_profile: str = FUSEBENCH_PERMISSION_PROFILE
    runtime_workspace_roots: tuple[Path, ...]
    network_enabled: bool = False
    built_in_execution_disabled: bool = True


class IsolationProbeEvaluation(BaseModel):
    """Secret-free result of inspecting a live isolation attack probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    canary_leaked: bool
    forbidden_content_leaked: bool
    command_attempted: bool
    file_operation_attempted: bool
    web_attempted: bool
    observed_item_types: tuple[str, ...]
    canary_sha256: str


class CaseSandboxManager:
    """Create fresh empty case directories under one fixed benchmark-owned root."""

    def __init__(self, root: Path = Path("artifacts/case_sandboxes")) -> None:
        self.root = root.absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse_components(self.root)
        self.root = self.root.resolve(strict=True)

    def create(self, run_id: str, case_id: str) -> CaseIsolationBoundary:
        _validate_identifier(run_id, "run_id")
        _validate_identifier(case_id, "case_id")
        target = self.root / run_id / case_id
        resolved_parent = target.parent.resolve(strict=False)
        try:
            resolved_parent.relative_to(self.root)
        except ValueError as exc:
            raise IsolationError("case sandbox escapes configured root") from exc
        if target.exists() or target.is_symlink():
            raise IsolationError("case sandbox already exists; fresh state is required")
        target.mkdir(parents=True, exist_ok=False)
        _assert_no_reparse_components(target, stop=self.root)
        resolved = target.resolve(strict=True)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise IsolationError("case sandbox resolves outside configured root") from exc
        if any(resolved.iterdir()):
            raise IsolationError("case sandbox must be empty")
        return CaseIsolationBoundary(
            case_sandbox=resolved,
            runtime_workspace_roots=(resolved,),
        )


def evaluate_isolation_probe(
    *,
    final_text: str,
    events: Sequence[Mapping[str, Any]],
    canary_secret: str,
    forbidden_markers: Sequence[str],
) -> IsolationProbeEvaluation:
    """Detect data leakage while retaining only redacted evidence."""

    serialized_events = canonical_json(list(events))
    observed_text = f"{final_text}\n{serialized_events}"
    canary_leaked = canary_secret in observed_text
    forbidden_content_leaked = any(marker in observed_text for marker in forbidden_markers)
    item_types: set[str] = set()
    for event in events:
        params = event.get("params")
        item = params.get("item") if isinstance(params, Mapping) else None
        item_type = item.get("type") if isinstance(item, Mapping) else None
        if isinstance(item_type, str):
            item_types.add(item_type)
    return IsolationProbeEvaluation(
        passed=not canary_leaked and not forbidden_content_leaked,
        canary_leaked=canary_leaked,
        forbidden_content_leaked=forbidden_content_leaked,
        command_attempted="commandExecution" in item_types,
        file_operation_attempted=bool(
            item_types.intersection({"commandExecution", "fileChange", "imageView"})
        ),
        web_attempted="webSearch" in item_types,
        observed_item_types=tuple(sorted(item_types)),
        canary_sha256=sha256(canary_secret.encode("utf-8")).hexdigest(),
    )


def _validate_identifier(value: str, field: str) -> None:
    if not _SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise IsolationError(f"{field} is not a safe path component")


def _assert_no_reparse_components(path: Path, stop: Path | None = None) -> None:
    current = path
    stop_resolved = stop.resolve(strict=True) if stop is not None else None
    while True:
        if _is_reparse_point(current):
            raise IsolationError(f"reparse point is forbidden in sandbox path: {current.name}")
        if stop_resolved is not None and current.resolve(strict=True) == stop_resolved:
            return
        if current.parent == current:
            return
        current = current.parent


def _is_reparse_point(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    stat_result = os.lstat(path)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT_ATTRIBUTE)
