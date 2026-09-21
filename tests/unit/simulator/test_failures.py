from fusebench.contracts.tools import FailurePlan, ToolErrorKind
from fusebench.simulator.failures import FailureController


def test_fail_first_n_transitions_to_success() -> None:
    controller = FailureController(
        {
            "get_tracking": FailurePlan(
                fail_first_n=1,
                error_kind=ToolErrorKind.TEMPORARY_ERROR,
            )
        }
    )

    assert controller.next_error("get_tracking") is ToolErrorKind.TEMPORARY_ERROR
    assert controller.next_error("get_tracking") is None


def test_persistent_failure_never_transitions_to_success() -> None:
    controller = FailureController(
        {
            "get_customer_risk": FailurePlan(
                persistent=True,
                error_kind=ToolErrorKind.UNAVAILABLE,
            )
        }
    )

    assert controller.next_error("get_customer_risk") is ToolErrorKind.UNAVAILABLE
    assert controller.next_error("get_customer_risk") is ToolErrorKind.UNAVAILABLE


def test_controllers_do_not_share_attempt_counters() -> None:
    plan = {
        "get_tracking": FailurePlan(
            fail_first_n=1,
            error_kind=ToolErrorKind.TEMPORARY_ERROR,
        )
    }
    first = FailureController(plan)
    second = FailureController(plan)

    first.next_error("get_tracking")

    assert second.next_error("get_tracking") is ToolErrorKind.TEMPORARY_ERROR
