"""Mutable simulated side effects built from an immutable case fixture."""

from dataclasses import dataclass
from hashlib import sha256

from fusebench.contracts.actions import Action
from fusebench.contracts.case import BenchmarkCase
from fusebench.simulator.failures import FailureController


@dataclass
class EnvironmentState:
    refund_executed: bool = False
    reship_executed: bool = False
    replacement_order_id: str | None = None
    requested_field: str | None = None
    wait_decision: bool = False
    escalation_reason: str | None = None
    terminal_action: Action | None = None


class SimulatorEnvironment:
    """One isolated simulator instance for one system-case execution."""

    def __init__(self, case: BenchmarkCase, seed: int) -> None:
        self.case = case
        self.seed = seed
        self.state = EnvironmentState()
        self.failures = FailureController(case.hidden.tool_failures)

    @classmethod
    def from_case(cls, case: BenchmarkCase, seed: int) -> "SimulatorEnvironment":
        return cls(case=case, seed=seed)

    def record_refund(self) -> dict[str, object]:
        self.state.refund_executed = True
        self.state.terminal_action = Action.REFUND
        return {"order_id": self.case.visible.order_id, "refund_executed": True}

    def record_reship(self) -> dict[str, object]:
        digest = sha256(
            f"{self.seed}:{self.case.visible.case_id}:replacement".encode()
        ).hexdigest()[:12]
        replacement = f"RPL-{digest.upper()}"
        self.state.reship_executed = True
        self.state.replacement_order_id = replacement
        self.state.terminal_action = Action.RESHIP
        return {
            "order_id": self.case.visible.order_id,
            "reship_executed": True,
            "replacement_order_id": replacement,
        }

    def record_request_information(self, field: str) -> dict[str, object]:
        self.state.requested_field = field
        self.state.terminal_action = Action.REQUEST_INFO
        return {"order_id": self.case.visible.order_id, "requested_field": field}

    def record_wait(self) -> dict[str, object]:
        self.state.wait_decision = True
        self.state.terminal_action = Action.WAIT
        return {"order_id": self.case.visible.order_id, "wait_recorded": True}

    def record_escalation(self, reason_code: str) -> dict[str, object]:
        self.state.escalation_reason = reason_code
        self.state.terminal_action = Action.ESCALATE
        return {
            "order_id": self.case.visible.order_id,
            "escalated": True,
            "reason_code": reason_code,
        }
