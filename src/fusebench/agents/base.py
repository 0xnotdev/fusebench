"""Shared execution outcome for benchmark decision agents."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fusebench.contracts.decisions import DecisionResult
from fusebench.contracts.events import ToolEvent


class AgentRunOutcome(BaseModel):
    """Auditable result of one isolated decision-path execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: DecisionResult
    thread_id: str | None = None
    turn_id: str | None = None
    read_tools_requested: tuple[str, ...] = ()
    infrastructure_retries: int = Field(default=0, ge=0)
    model_calls: dict[str, int] = Field(default_factory=dict)
    decision_path_latency_ms: float = Field(ge=0)
    terra_input_tokens: int = Field(default=0, ge=0)
    terra_cached_input_tokens: int = Field(default=0, ge=0)
    terra_output_tokens: int = Field(default=0, ge=0)
    terra_reasoning_output_tokens: int = Field(default=0, ge=0)
    tool_events: tuple[ToolEvent, ...] = ()
    provider_events: tuple[dict[str, Any], ...] = ()
    dynamic_tool_requests: tuple[dict[str, Any], ...] = ()
    loop_limit_exceeded: bool = False
    invalid_tool_requests: int = Field(default=0, ge=0)
    action_result: dict[str, Any]
    provider_versions: dict[str, str] = Field(default_factory=dict)

