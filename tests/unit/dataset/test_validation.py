import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from fusebench.cli import app
from fusebench.dataset.generator import build_dev_dataset
from fusebench.dataset.validation import load_cases_jsonl, validate_dev_dataset


def test_build_dev_cli_writes_valid_cases_and_matching_manifest_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["dataset", "build-dev", "--seed", "20260921"])

    assert result.exit_code == 0, result.stdout
    cases_path = tmp_path / "data" / "dev" / "cases.jsonl"
    manifest_path = tmp_path / "data" / "dev" / "manifest.json"
    assert cases_path.exists()
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["case_count"] == 60
    assert manifest["dataset_sha256"] == hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert len(load_cases_jsonl(cases_path)) == 60


def test_validator_accepts_generated_dev_dataset() -> None:
    report = validate_dev_dataset(build_dev_dataset(seed=20260921))

    assert report.case_count == 60
