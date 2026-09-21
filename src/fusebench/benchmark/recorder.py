"""Durable append-only normalized and raw benchmark artifact recording."""

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from fusebench.contracts.results import RunRecord
from fusebench.dataset.validation import canonical_json

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_KEYS = frozenset(
    {"api_key", "authorization", "access_token", "refresh_token", "secret", "password"}
)


class DuplicateRunRecord(RuntimeError):
    """A completed system-case-repetition key cannot be overwritten."""


class ProviderVersionChanged(RuntimeError):
    """A provider version changed within a resumable benchmark run."""


class RunRecorder:
    """Append, flush, hash, resume, and redact one benchmark run."""

    def __init__(
        self,
        root: Path,
        run_id: str,
        *,
        secrets: Sequence[str] = (),
        provider_versions: Mapping[str, str] | None = None,
        raw_root: Path | None = None,
    ) -> None:
        _validate_component(run_id)
        self.run_id = run_id
        self.run_dir = (root / run_id).absolute()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.run_dir / "records.jsonl"
        self.record_hashes_path = self.run_dir / "record_hashes.jsonl"
        self.checksums_path = self.run_dir / "checksums.json"
        self.raw_run_dir = (
            (raw_root / run_id).absolute()
            if raw_root is not None
            else self.run_dir / "raw"
        )
        self.secrets = tuple(value for value in secrets if value)
        self.provider_versions = dict(provider_versions or {})
        records = self.load_records()
        for record in records:
            self._check_provider_versions(record.provider_versions)
        self.completed_keys = {
            (record.case_id, record.system, record.repetition)
            for record in records
        }

    def append(self, record: RunRecord) -> None:
        key = (record.case_id, record.system, record.repetition)
        if key in self.completed_keys:
            raise DuplicateRunRecord(f"run record already exists for {key}")
        self._check_provider_versions(record.provider_versions)
        payload = canonical_json(record)
        digest = sha256(payload.encode("utf-8")).hexdigest()
        _append_line(self.records_path, payload)
        _append_line(
            self.record_hashes_path,
            canonical_json(
                {
                    "case_id": record.case_id,
                    "system": record.system,
                    "repetition": record.repetition,
                    "sha256": digest,
                }
            ),
        )
        self.completed_keys.add(key)
        self._write_checksums()

    def _check_provider_versions(self, versions: Mapping[str, str]) -> None:
        for provider, version in versions.items():
            expected = self.provider_versions.get(provider)
            if expected is not None and expected != version:
                raise ProviderVersionChanged(
                    f"provider {provider} changed from {expected} to {version}"
                )
            self.provider_versions[provider] = version

    def load_records(self) -> list[RunRecord]:
        if not self.records_path.exists():
            return []
        return [
            RunRecord.model_validate_json(line)
            for line in self.records_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def raw_dir(
        self,
        *,
        system: str,
        case_id: str,
        repetition: int,
    ) -> Path:
        _validate_component(system)
        _validate_component(case_id)
        target = self.raw_run_dir / system / case_id / f"r{repetition}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_raw_json(
        self,
        *,
        system: str,
        case_id: str,
        repetition: int,
        name: str,
        value: Any,
    ) -> Path:
        _validate_filename(name)
        path = _next_available(self.raw_dir(
            system=system, case_id=case_id, repetition=repetition
        ) / name)
        sanitized = self._redact(value)
        path.write_text(canonical_json(sanitized) + "\n", encoding="utf-8")
        return path

    def write_raw_jsonl(
        self,
        *,
        system: str,
        case_id: str,
        repetition: int,
        name: str,
        values: Iterable[Any],
    ) -> Path:
        _validate_filename(name)
        path = _next_available(self.raw_dir(
            system=system, case_id=case_id, repetition=repetition
        ) / name)
        lines = [canonical_json(self._redact(value)) for value in values]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def refresh_checksums(self) -> None:
        """Hash the current durable normalized and raw artifact set."""

        self._write_checksums()

    def verify_checksums(self) -> bool:
        if not self.checksums_path.exists():
            return False
        expected = json.loads(self.checksums_path.read_text(encoding="utf-8"))
        return expected == self._checksums()

    def _redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): (
                    "[REDACTED]"
                    if str(key).lower() in _SECRET_KEYS
                    else self._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            redacted = value
            for secret in self.secrets:
                redacted = redacted.replace(secret, "[REDACTED]")
            return redacted
        if hasattr(value, "model_dump"):
            return self._redact(value.model_dump(mode="json"))
        return value

    def _checksums(self) -> dict[str, str]:
        checksums = {
            path.relative_to(self.run_dir).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.run_dir.rglob("*"))
            if path.is_file() and path != self.checksums_path
        }
        if self.raw_run_dir.exists() and not self.raw_run_dir.is_relative_to(self.run_dir):
            checksums.update(
                {
                    f"raw/{path.relative_to(self.raw_run_dir).as_posix()}": sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in sorted(self.raw_run_dir.rglob("*"))
                    if path.is_file()
                }
            )
        return checksums

    def _write_checksums(self) -> None:
        self.checksums_path.write_text(
            canonical_json(self._checksums()) + "\n", encoding="utf-8"
        )


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validate_component(value: str) -> None:
    if not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError("unsafe artifact path component")


def _validate_filename(value: str) -> None:
    if Path(value).name != value or value in {".", ".."}:
        raise ValueError("unsafe artifact filename")


def _next_available(path: Path) -> Path:
    if not path.exists():
        return path
    for attempt in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}.a{attempt:04d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("raw artifact attempt space exhausted")
