import pytest
from pydantic import ValidationError

from fusebench.contracts.tools import (
    EscalateInput,
    FailurePlan,
    GetTrackingInput,
    ReadTool,
    RequestInformationInput,
    ToolErrorKind,
)


def test_read_tool_enum_contains_only_specified_tools() -> None:
    assert {tool.value for tool in ReadTool} == {
        "get_tracking",
        "get_payment",
        "get_inventory",
        "get_damage_evidence",
    }


def test_tool_input_rejects_extra_arguments() -> None:
    with pytest.raises(ValidationError):
        GetTrackingInput(order_id="ORD-1", customer_id="CUS-1")  # type: ignore[call-arg]


def test_request_information_requires_nonempty_field() -> None:
    with pytest.raises(ValidationError):
        RequestInformationInput(order_id="ORD-1", field="")


def test_escalation_requires_nonempty_reason_code() -> None:
    with pytest.raises(ValidationError):
        EscalateInput(order_id="ORD-1", reason_code=" ")


def test_failure_plan_rejects_negative_attempt_count() -> None:
    with pytest.raises(ValidationError):
        FailurePlan(fail_first_n=-1, error_kind=ToolErrorKind.UNAVAILABLE)
