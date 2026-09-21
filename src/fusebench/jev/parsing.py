"""Strict parsing of TypeSafe System One response models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer, SystemOneResponse

from fusebench.contracts.actions import Action
from fusebench.contracts.decisions import normalize_action_probabilities


class JevResponseError(ValueError):
    """A provider response violates the frozen benchmark contract."""


class InformationNeeds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_type: str
    issue_probabilities: dict[str, float]
    issue_confidence: float = Field(ge=0, le=1)
    need_tracking: float = Field(ge=0, le=1)
    need_payment: float = Field(ge=0, le=1)
    need_inventory: float = Field(ge=0, le=1)
    need_damage_evidence: float = Field(ge=0, le=1)
    need_customer_risk: float = Field(ge=0, le=1)
    reported_model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class JevDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    action_probabilities: dict[Action, float]
    action_confidence: float = Field(ge=0, le=1)
    information_sufficient: float = Field(ge=0, le=1)
    requires_human: float = Field(ge=0, le=1)
    risk_score: float
    risk_confidence: float = Field(ge=0, le=1)
    risk_legend: dict[int, Any]
    risk_probabilities: dict[int, float]
    reported_model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    raw_response: dict[str, Any] = Field(default_factory=dict)


def _response(value: Any) -> SystemOneResponse:
    try:
        return SystemOneResponse.model_validate(value)
    except ValidationError as error:
        raise JevResponseError(f"invalid System One response: {error}") from error


def _usage(response: SystemOneResponse) -> tuple[int, int]:
    if response.usage.input_tokens is None:
        raise JevResponseError("input token usage is required for budget accounting")
    if response.usage.output_tokens is None:
        raise JevResponseError("output token usage is required for audit accounting")
    return response.usage.input_tokens, response.usage.output_tokens


def _answer(response: SystemOneResponse, name: str, expected: type) -> Any:
    try:
        answer = response.answers[name]
    except KeyError as error:
        raise JevResponseError(f"missing answer: {name}") from error
    if not isinstance(answer, expected):
        raise JevResponseError(f"answer {name} has unexpected type")
    return answer


def parse_information_needs(value: Any, latency_ms: float) -> InformationNeeds:
    response = _response(value)
    input_tokens, output_tokens = _usage(response)
    issue = _answer(response, "issue_type", ChoiceAnswer)
    noul_names = (
        "need_tracking",
        "need_payment",
        "need_inventory",
        "need_damage_evidence",
        "need_customer_risk",
    )
    nouls = {name: _answer(response, name, NoulAnswer).noul for name in noul_names}
    return InformationNeeds(
        issue_type=issue.choice,
        issue_probabilities=issue.probabilities,
        issue_confidence=issue.confidence,
        reported_model=response.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        raw_response=response.model_dump(mode="json"),
        **nouls,
    )


def parse_terminal_decision(value: Any, latency_ms: float) -> JevDecision:
    response = _response(value)
    input_tokens, output_tokens = _usage(response)
    action_answer = _answer(response, "action", ChoiceAnswer)
    normalized = normalize_action_probabilities(action_answer.probabilities)
    if not normalized.valid or normalized.selected_action is None:
        raise JevResponseError(
            f"invalid action probability distribution: {', '.join(normalized.errors)}"
        )
    if action_answer.choice != normalized.selected_action.value:
        raise JevResponseError("action choice does not match probability argmax")
    information = _answer(response, "information_sufficient", NoulAnswer)
    requires_human = _answer(response, "requires_human", NoulAnswer)
    risk = _answer(response, "risk_level", ScoreAnswer)
    return JevDecision(
        action=normalized.selected_action,
        action_probabilities=normalized.probabilities,
        action_confidence=action_answer.confidence,
        information_sufficient=information.noul,
        requires_human=requires_human.noul,
        risk_score=risk.score,
        risk_confidence=risk.confidence,
        risk_legend=risk.legend,
        risk_probabilities=risk.probabilities,
        reported_model=response.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        raw_response=response.model_dump(mode="json"),
    )
