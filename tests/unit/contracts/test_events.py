import pytest
from pydantic import ValidationError

from fusebench.contracts.events import EventStage, ToolEvent


def test_tool_event_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        ToolEvent(
            case_id="DEV_0001",
            system="terra_only",
            tool="get_tracking",
            arguments={"order_id": "ORD-1"},
            started_at_ns=20,
            ended_at_ns=10,
            duration_ms=0,
            attempt=1,
            infrastructure_retry=False,
            result_kind="success",
            result={"order_id": "ORD-1"},
        )


def test_event_stage_contains_auditable_case_lifecycle() -> None:
    assert EventStage.CASE_STARTED.value == "case.started"
    assert EventStage.DECISION_FINALIZED.value == "decision.finalized"
    assert EventStage.CASE_FAILED.value == "case.failed"
