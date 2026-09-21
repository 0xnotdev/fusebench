"""Deterministic per-environment tool failure transitions."""

from collections import defaultdict
from collections.abc import Mapping

from fusebench.contracts.tools import FailurePlan, ToolErrorKind


class FailureController:
    """Evaluate failure plans without sharing attempt state across case runs."""

    def __init__(self, plans: Mapping[str, FailurePlan]) -> None:
        self._plans = dict(plans)
        self._attempts: defaultdict[str, int] = defaultdict(int)

    def next_error(self, tool: str) -> ToolErrorKind | None:
        """Return the deterministic error for the next infrastructure attempt."""

        plan = self._plans.get(tool)
        self._attempts[tool] += 1
        if plan is None:
            return None
        attempt = self._attempts[tool]
        if plan.persistent or attempt <= plan.fail_first_n:
            return plan.error_kind
        return None

    def attempts(self, tool: str) -> int:
        return self._attempts[tool]
