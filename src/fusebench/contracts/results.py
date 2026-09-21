"""Normalized benchmark result records."""

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fusebench.contracts.actions import Action, IssueType


class FailureTag(StrEnum):
    WRONG_BUSINESS_ACTION = "wrong_business_action"
    UNSAFE_AUTONOMOUS_ACTION = "unsafe_autonomous_action"
    FALSE_ESCALATION = "false_escalation"
    MISSING_REQUIRED_TOOL = "missing_required_tool"
    UNNECESSARY_TOOL = "unnecessary_tool"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    LOOP_LIMIT = "loop_limit"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_USAGE_LIMIT = "provider_usage_limit"
    PROVIDER_HTTP_ERROR = "provider_http_error"
    MODEL_VERSION_CHANGED = "model_version_changed"
    INVALID_PROBABILITY_DISTRIBUTION = "invalid_probability_distribution"
    PERSISTENT_TOOL_UNAVAILABLE = "persistent_tool_unavailable"
    PROMPT_INJECTION_FAILURE = "prompt_injection_failure"
    FILESYSTEM_ISOLATION_VIOLATION = "filesystem_isolation_violation"
    DATASET_INTEGRITY_FAILURE = "dataset_integrity_failure"
    UNKNOWN = "unknown"


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    case_id: str
    system: str
    repetition: int = Field(ge=0)
    category: str | None = None
    issue_type: IssueType | None = None
    gold_action: Action
    raw_action: Action | None
    executed_action: Action
    action_probabilities: dict[Action, float] | None = None
    top_probability: float | None = Field(default=None, ge=0, le=1)
    minimal_required_read_tools: frozenset[str] = frozenset()
    allowed_autonomous_actions: frozenset[Action] = frozenset()
    read_tools_requested: tuple[str, ...] = ()
    invalid_tool_requests: int = Field(default=0, ge=0)
    infrastructure_retries: int = Field(default=0, ge=0)
    model_calls: dict[str, int] = Field(default_factory=dict)
    decision_path_latency_ms: float | None = Field(default=None, ge=0)
    full_response_latency_ms: float | None = Field(default=None, ge=0)
    terra_input_tokens: int = Field(default=0, ge=0)
    terra_output_tokens: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)
    unsafe_autonomous: bool
    correct: bool
    business_loss: float = Field(ge=0)
    provider_versions: dict[str, str] = Field(default_factory=dict)
    terminal_success: bool = False
    persistent_tool_failure: bool = False
    hallucinated_state: bool = False
    errors: tuple[FailureTag, ...] = ()

    @model_validator(mode="after")
    def validate_probabilities(self) -> "RunRecord":
        if self.action_probabilities is None:
            if self.raw_action is not None or self.top_probability is not None:
                raise ValueError("raw action and top probability require probabilities")
            return self
        if set(self.action_probabilities) != set(Action):
            raise ValueError("probabilities must contain exactly all actions")
        if any(
            not math.isfinite(value) or not 0 <= value <= 1
            for value in self.action_probabilities.values()
        ):
            raise ValueError("probabilities must be finite values in [0, 1]")
        selected = max(Action, key=lambda action: self.action_probabilities[action])
        top = self.action_probabilities[selected]
        if self.raw_action != selected:
            raise ValueError("raw_action must equal probability argmax")
        if self.top_probability is None or not math.isclose(
            self.top_probability, top, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("top_probability must equal distribution maximum")
        return self
