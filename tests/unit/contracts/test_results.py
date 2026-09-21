import pytest
from pydantic import ValidationError

from fusebench.contracts.actions import Action
from fusebench.contracts.results import FailureTag, RunRecord


def test_failure_taxonomy_matches_spec() -> None:
    assert {tag.value for tag in FailureTag} == {
        "wrong_business_action",
        "unsafe_autonomous_action",
        "false_escalation",
        "missing_required_tool",
        "unnecessary_tool",
        "invalid_tool_arguments",
        "loop_limit",
        "provider_timeout",
        "provider_usage_limit",
        "provider_http_error",
        "model_version_changed",
        "invalid_probability_distribution",
        "persistent_tool_unavailable",
        "prompt_injection_failure",
        "filesystem_isolation_violation",
        "dataset_integrity_failure",
        "unknown",
    }


def test_run_record_accepts_a_complete_valid_decision() -> None:
    record = RunRecord(
        run_id="dev-v1",
        case_id="DEV_0001",
        system="terra_jev",
        repetition=0,
        gold_action=Action.RESHIP,
        raw_action=Action.RESHIP,
        executed_action=Action.RESHIP,
        action_probabilities={
            Action.REFUND: 0.02,
            Action.RESHIP: 0.94,
            Action.REQUEST_INFO: 0.01,
            Action.WAIT: 0.02,
            Action.ESCALATE: 0.01,
        },
        top_probability=0.94,
        read_tools_requested=["get_tracking", "get_inventory"],
        infrastructure_retries=0,
        model_calls={"terra": 0, "jev": 2},
        decision_path_latency_ms=712.3,
        unsafe_autonomous=False,
        correct=True,
        business_loss=0,
    )

    assert record.correct is True


def test_run_record_rejects_top_probability_mismatch() -> None:
    with pytest.raises(ValidationError):
        RunRecord(
            run_id="dev-v1",
            case_id="DEV_0001",
            system="terra_only",
            repetition=0,
            gold_action=Action.WAIT,
            raw_action=Action.WAIT,
            executed_action=Action.WAIT,
            action_probabilities={action: 0.2 for action in Action},
            top_probability=0.9,
            unsafe_autonomous=False,
            correct=True,
            business_loss=0,
        )
