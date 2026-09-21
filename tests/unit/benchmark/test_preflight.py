import json
from pathlib import Path

from fusebench.benchmark.preflight import evaluate_preflight


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_preflight_requires_provider_contracts_isolation_and_absent_test_set(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex.json"
    typesafe = tmp_path / "typesafe.json"
    isolation = tmp_path / "isolation.json"
    write_json(
        codex,
        {
            "model": "gpt-5.6-terra",
            "effort": "medium",
            "selected_tool_protocol": "dynamic_tools",
            "dynamic_tool_called": True,
            "usage": {"input_tokens": 1},
        },
    )
    write_json(
        typesafe,
        {
            "concrete_model_accepted": True,
            "model": "jev-1.13.0",
            "requested_model": "jev-1.13.0",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    write_json(
        isolation,
        {
            "passed": True,
            "built_in_execution_disabled": True,
            "evaluation": {"passed": True, "canary_leaked": False},
        },
    )

    report = evaluate_preflight(
        artifact_dir=tmp_path / "artifacts",
        codex_evidence=codex,
        typesafe_evidence=typesafe,
        isolation_evidence=isolation,
        test_dataset=tmp_path / "data" / "test" / "cases.jsonl",
        typesafe_key_present=True,
        codex_executable="codex",
    )

    assert report.passed is True
    assert all(check.passed for check in report.checks.values())

    write_json(isolation, {"passed": False, "evaluation": {"passed": False}})
    failed = evaluate_preflight(
        artifact_dir=tmp_path / "artifacts",
        codex_evidence=codex,
        typesafe_evidence=typesafe,
        isolation_evidence=isolation,
        test_dataset=tmp_path / "data" / "test" / "cases.jsonl",
        typesafe_key_present=True,
        codex_executable="codex",
    )
    assert failed.passed is False
    assert failed.checks["filesystem_isolation"].passed is False
