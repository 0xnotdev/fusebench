from pathlib import Path

import pytest

from fusebench.benchmark.manifest import build_dev_manifest, verify_dev_manifest


def test_dev_manifest_hashes_inputs_and_detects_drift_without_test_data(tmp_path: Path) -> None:
    dev = tmp_path / "data" / "dev" / "cases.jsonl"
    dev.parent.mkdir(parents=True)
    dev.write_text('{"visible_case":{}}\n', encoding="utf-8")
    policy = tmp_path / "policy.md"
    policy.write_text("frozen policy", encoding="utf-8")
    test_path = tmp_path / "data" / "test" / "cases.jsonl"

    manifest = build_dev_manifest(
        dev_dataset=dev,
        critical_paths=(policy,),
        test_dataset=test_path,
        run_seed=17,
        information_threshold=0.5,
        terra_model="gpt-5.6-terra",
        jev_model="jev-1.13.0",
        tool_protocol="dynamic_tools",
    )

    assert manifest.test_dataset_absent is True
    assert verify_dev_manifest(manifest) == ()
    policy.write_text("changed", encoding="utf-8")
    assert verify_dev_manifest(manifest) == (str(policy.resolve()),)
    test_path.parent.mkdir(parents=True)
    test_path.write_text("forbidden", encoding="utf-8")
    with pytest.raises(ValueError, match="test dataset"):
        build_dev_manifest(
            dev_dataset=dev,
            critical_paths=(policy,),
            test_dataset=test_path,
            run_seed=17,
            information_threshold=0.5,
            terra_model="gpt-5.6-terra",
            jev_model="jev-1.13.0",
            tool_protocol="dynamic_tools",
        )
