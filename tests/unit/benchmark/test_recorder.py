import json
from pathlib import Path

import pytest

from fusebench.benchmark.recorder import (
    DuplicateRunRecord,
    ProviderVersionChanged,
    RunRecorder,
)
from fusebench.contracts.actions import Action, IssueType
from fusebench.contracts.results import RunRecord


def record() -> RunRecord:
    probabilities = {action: 0.8 if action is Action.WAIT else 0.05 for action in Action}
    return RunRecord(
        run_id="run-1",
        case_id="CASE_1",
        system="terra_only",
        repetition=0,
        category="clean",
        issue_type=IssueType.SHIPPING,
        gold_action=Action.WAIT,
        raw_action=Action.WAIT,
        executed_action=Action.WAIT,
        action_probabilities=probabilities,
        top_probability=0.8,
        terminal_success=True,
        unsafe_autonomous=False,
        correct=True,
        business_loss=0,
    )


def test_append_is_durable_unique_resumable_and_checksummed(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path, "run-1")

    recorder.append(record())

    assert recorder.completed_keys == {("CASE_1", "terra_only", 0)}
    assert RunRecorder(tmp_path, "run-1").completed_keys == recorder.completed_keys
    assert recorder.verify_checksums() is True
    with pytest.raises(DuplicateRunRecord):
        recorder.append(record())
    lines = recorder.records_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["case_id"] == "CASE_1"
    assert len(recorder.record_hashes_path.read_text(encoding="utf-8").splitlines()) == 1


def test_raw_artifacts_use_exact_layout_and_redact_secrets(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path, "run-1", secrets=("super-secret-value",))

    path = recorder.write_raw_json(
        system="terra_jev",
        case_id="CASE_2",
        repetition=0,
        name="jev_request_1.json",
        value={
            "authorization": "Bearer super-secret-value",
            "input_tokens": 50,
            "nested": {"api_key": "super-secret-value"},
        },
    )

    assert path == (
        tmp_path
        / "run-1"
        / "raw"
        / "terra_jev"
        / "CASE_2"
        / "r0"
        / "jev_request_1.json"
    )
    text = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in text
    assert "[REDACTED]" in text
    assert '"input_tokens":50' in text
    recorder.refresh_checksums()
    assert recorder.verify_checksums() is True


def test_provider_version_change_aborts_append_and_resume(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path, "run-1")
    first = record().model_copy(update={"provider_versions": {"terra": "v1"}})
    recorder.append(first)
    changed = first.model_copy(
        update={
            "case_id": "CASE_2",
            "provider_versions": {"terra": "v2"},
        }
    )

    with pytest.raises(ProviderVersionChanged, match="terra"):
        recorder.append(changed)

    with pytest.raises(ProviderVersionChanged, match="terra"):
        RunRecorder(tmp_path, "run-1", provider_versions={"terra": "v2"})
