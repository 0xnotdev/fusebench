"""Structured event contracts for audit logs."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventStage(StrEnum):
    CASE_STARTED = "case.started"
    TERRA_THREAD_STARTED = "terra.thread_started"
    TERRA_TURN_STARTED = "terra.turn_started"
    TERRA_TURN_COMPLETED = "terra.turn_completed"
    JEV_REQUEST_STARTED = "jev.request_started"
    JEV_REQUEST_COMPLETED = "jev.request_completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    DECISION_FINALIZED = "decision.finalized"
    ACTION_EXECUTED = "action.executed"
    RESPONSE_GENERATED = "response.generated"
    CASE_COMPLETED = "case.completed"
    CASE_FAILED = "case.failed"


class ToolEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    system: Literal["terra_only", "terra_jev"]
    tool: str
    arguments: dict[str, Any]
    started_at_ns: int = Field(ge=0)
    ended_at_ns: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    attempt: int = Field(ge=1)
    infrastructure_retry: bool
    result_kind: Literal["success", "temporary_error", "unavailable", "not_found", "invalid"]
    result: dict[str, Any]

    @model_validator(mode="after")
    def validate_timing(self) -> "ToolEvent":
        if self.ended_at_ns < self.started_at_ns:
            raise ValueError("ended_at_ns must not precede started_at_ns")
        return self


class ApplicationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    case_id: str
    system: Literal["terra_only", "terra_jev"]
    stage: EventStage
    monotonic_ns: int = Field(ge=0)
    wall_clock: str
    provider: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
