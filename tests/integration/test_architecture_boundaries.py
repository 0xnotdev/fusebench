import ast
import json
from pathlib import Path


def test_scored_agent_modules_do_not_import_oracle() -> None:
    for name in ("terra_only.py", "terra_jev.py"):
        path = Path("src/fusebench/agents") / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "fusebench.policy.oracle" not in imports


def test_cp12_evidence_records_that_test_data_was_absent_before_freeze() -> None:
    report = json.loads(
        Path("artifacts/preflight/report.json").read_text(encoding="utf-8")
    )

    assert report["checks"]["test_dataset_absent"]["passed"] is True
    assert report["checks"]["test_dataset_absent"]["detail"].endswith(
        "data\\test\\cases.jsonl"
    )
