"""Codex App Server adapter pinned to GPT-5.6 Terra and medium effort."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fusebench.contracts.actions import Action
from fusebench.contracts.tools import (
    GetCustomerRiskInput,
    GetDamageEvidenceInput,
    GetInventoryInput,
    GetPaymentInput,
    GetTrackingInput,
    ReadTool,
)
from fusebench.dataset.validation import canonical_json
from fusebench.providers.codex_protocol import (
    CodexProtocolClient,
    CodexProtocolError,
    StdioJsonRpcTransport,
)

TERRA_MODEL = "gpt-5.6-terra"
TERRA_EFFORT = "medium"
TERRA_TOOL_PROTOCOL = "dynamic_tools"
FUSEBENCH_PERMISSION_PROFILE = ":read-only"


def codex_app_server_command() -> tuple[str, ...]:
    """Build App Server argv with all non-benchmark tool capabilities disabled."""

    return (
        "codex",
        "app-server",
        "--stdio",
        "--disable",
        "shell_tool",
        "--disable",
        "unified_exec",
        "--disable",
        "view_image",
        "--disable",
        "browser_use",
        "--disable",
        "browser_use_external",
        "--disable",
        "browser_use_full_cdp_access",
        "--disable",
        "computer_use",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "skill_search",
        "--disable",
        "workspace_dependencies",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
    )


class TerraProviderError(RuntimeError):
    """Base fail-closed Terra provider error."""


class TerraModelMismatch(TerraProviderError):
    """The requested exact Terra model is absent or was rerouted."""


class TerraEffortMismatch(TerraProviderError):
    """Medium reasoning effort is unavailable or changed."""


class TerraStructuredOutputError(TerraProviderError):
    """Terra emitted invalid structured-loop output."""

    def __init__(
        self,
        message: str,
        *,
        turn_id: str | None = None,
        raw_text: str | None = None,
        usage: TerraUsage | None = None,
        raw_token_events: tuple[dict[str, Any], ...] = (),
        raw_events: tuple[dict[str, Any], ...] = (),
        dynamic_tool_requests: tuple[dict[str, Any], ...] = (),
    ) -> None:
        super().__init__(message)
        self.turn_id = turn_id
        self.raw_text = raw_text
        self.usage = usage
        self.raw_token_events = raw_token_events
        self.raw_events = raw_events
        self.dynamic_tool_requests = dynamic_tool_requests


class CodexUsageLimitExceeded(TerraProviderError):
    """Codex usage or rate limit stopped the run."""


class TerraReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["read_tool"]
    tool: ReadTool
    arguments: dict[str, Any]

    @model_validator(mode="after")
    def validate_arguments(self) -> TerraReadRequest:
        input_types = {
            ReadTool.GET_TRACKING: GetTrackingInput,
            ReadTool.GET_PAYMENT: GetPaymentInput,
            ReadTool.GET_INVENTORY: GetInventoryInput,
            ReadTool.GET_DAMAGE_EVIDENCE: GetDamageEvidenceInput,
            ReadTool.GET_CUSTOMER_RISK: GetCustomerRiskInput,
        }
        input_types[self.tool].model_validate(self.arguments)
        return self


class TerraFinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["final"]
    action_probabilities: dict[Action, float]
    reason_code: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_probabilities(self) -> TerraFinalDecision:
        if set(self.action_probabilities) != set(Action):
            raise ValueError("action probabilities must contain exactly five actions")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in self.action_probabilities.values()
        ):
            raise ValueError("action probabilities must be finite values in [0, 1]")
        if sum(self.action_probabilities.values()) <= 0:
            raise ValueError("action probabilities must have positive total")
        return self

    @property
    def selected_action(self) -> Action:
        return max(Action, key=lambda action: self.action_probabilities[action])


TerraOutput = TerraReadRequest | TerraFinalDecision


class TerraUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_output_tokens: int = Field(ge=0)


class TerraSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    session_id: str
    case_sandbox: Path
    permission_profile: Literal[":read-only"] = FUSEBENCH_PERMISSION_PROFILE
    effective_sandbox: dict[str, Any]
    runtime_workspace_roots: tuple[Path, ...]
    thread_start_effort: str | None = None
    model: Literal["gpt-5.6-terra"] = TERRA_MODEL
    effort: Literal["medium"] = TERRA_EFFORT


class TerraTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    turn_id: str
    output: TerraOutput
    raw_text: str
    usage: TerraUsage
    raw_token_events: tuple[dict[str, Any], ...]
    dynamic_tool_requests: tuple[dict[str, Any], ...] = ()
    raw_events: tuple[dict[str, Any], ...] = ()


class TerraResponseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    turn_id: str
    text: str = Field(min_length=1)
    usage: TerraUsage
    raw_token_events: tuple[dict[str, Any], ...]
    raw_events: tuple[dict[str, Any], ...] = ()


def terra_output_schema() -> dict[str, Any]:
    """Return the selected dynamic-tools terminal response schema."""

    probabilities = {
        "type": "object",
        "properties": {
            action.value: {"type": "number", "minimum": 0.0, "maximum": 1.0}
            for action in Action
        },
        "required": [action.value for action in Action],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "action_probabilities": probabilities,
            "reason_code": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        "required": ["action_probabilities", "reason_code"],
        "additionalProperties": False,
    }


def terra_read_tool_definitions() -> list[dict[str, Any]]:
    """Return the five isolated trusted read tools exposed to Terra."""

    definitions = [
        (
            ReadTool.GET_TRACKING,
            "Read trusted carrier status and days without movement for one order.",
            "order_id",
        ),
        (
            ReadTool.GET_PAYMENT,
            "Read trusted payment charges for one order.",
            "order_id",
        ),
        (
            ReadTool.GET_INVENTORY,
            "Read trusted available inventory units for one SKU.",
            "sku",
        ),
        (
            ReadTool.GET_DAMAGE_EVIDENCE,
            "Read trusted damage-evidence requirement, presence, and validity for one order.",
            "order_id",
        ),
        (
            ReadTool.GET_CUSTOMER_RISK,
            (
                "Read trusted prior exception-refund count and record-conflict status "
                "for one customer."
            ),
            "customer_id",
        ),
    ]
    return [
        {
            "type": "function",
            "name": tool.value,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {field: {"type": "string", "minLength": 1}},
                "required": [field],
                "additionalProperties": False,
            },
        }
        for tool, description, field in definitions
    ]


def parse_terra_output(raw_text: str) -> TerraOutput:
    """Parse a structured-loop step and reject inconsistent nullable fields."""

    try:
        raw = json.loads(raw_text)
        if not isinstance(raw, dict):
            raise ValueError("output is not an object")
        kind = raw.get("kind", "final")
        if kind == "read_tool":
            if raw.get("action_probabilities") is not None or raw.get("reason_code") is not None:
                raise ValueError("read request contains final fields")
            parsed = TerraReadRequest.model_validate(
                {"kind": kind, "tool": raw.get("tool"), "arguments": raw.get("arguments")}
            )
        elif kind == "final":
            if raw.get("tool") is not None or raw.get("arguments") is not None:
                raise ValueError("final decision contains tool fields")
            parsed = TerraFinalDecision.model_validate(
                {
                    "kind": kind,
                    "action_probabilities": raw.get("action_probabilities"),
                    "reason_code": raw.get("reason_code"),
                }
            )
        else:
            raise ValueError("unknown output kind")
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        raise TerraStructuredOutputError("Terra emitted invalid structured output") from exc
    return parsed


class CodexAppServerProvider:
    """One App Server process serving fresh exact-Terra threads per case."""

    def __init__(
        self,
        client: CodexProtocolClient,
        *,
        model: str = TERRA_MODEL,
        effort: str = TERRA_EFFORT,
        turn_timeout_seconds: float = 120.0,
    ) -> None:
        if model != TERRA_MODEL:
            raise TerraModelMismatch(f"FuseBench requires exact model {TERRA_MODEL}")
        if effort != TERRA_EFFORT:
            raise TerraEffortMismatch(f"FuseBench requires exact effort {TERRA_EFFORT}")
        self.client = client
        self.model = model
        self.effort = effort
        self.turn_timeout_seconds = turn_timeout_seconds
        self.tool_protocol = TERRA_TOOL_PROTOCOL
        self.account_type: str | None = None
        self.codex_user_agent: str | None = None
        self._turn_lock = asyncio.Lock()

    @classmethod
    async def start(
        cls,
        *,
        command: Sequence[str] | None = None,
        turn_timeout_seconds: float = 120.0,
    ) -> CodexAppServerProvider:
        transport = await StdioJsonRpcTransport.start(
            command if command is not None else codex_app_server_command()
        )
        client = CodexProtocolClient(
            transport,
            request_timeout_seconds=turn_timeout_seconds,
            experimental_api=True,
        )
        provider = cls(client, turn_timeout_seconds=turn_timeout_seconds)
        await provider.initialize_and_check()
        return provider

    async def initialize_and_check(self) -> None:
        initialized = await self.client.initialize()
        user_agent = initialized.get("userAgent")
        self.codex_user_agent = user_agent if isinstance(user_agent, str) else None

        account_response = await self.client.request("account/read", {})
        account = account_response.get("account")
        if not isinstance(account, Mapping) or not isinstance(account.get("type"), str):
            raise TerraProviderError("Codex App Server has no authenticated account")
        self.account_type = account["type"]

        cursor: str | None = None
        model_entry: Mapping[str, Any] | None = None
        while True:
            params: dict[str, Any] = {"includeHidden": True}
            if cursor is not None:
                params["cursor"] = cursor
            response = await self.client.request("model/list", params)
            models = response.get("data")
            if not isinstance(models, list):
                raise TerraProviderError("Codex model catalog response is invalid")
            model_entry = next(
                (
                    item
                    for item in models
                    if isinstance(item, Mapping)
                    and item.get("model") == self.model
                    and item.get("id") == self.model
                ),
                None,
            )
            if model_entry is not None:
                break
            next_cursor = response.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise TerraModelMismatch(f"Codex model catalog lacks exact {self.model}")
            cursor = next_cursor

        efforts = model_entry.get("supportedReasoningEfforts")
        if not isinstance(efforts, list):
            raise TerraProviderError("Codex model effort catalog is invalid")
        supported = {
            item.get("reasoningEffort")
            for item in efforts
            if isinstance(item, Mapping)
        }
        if self.effort not in supported:
            raise TerraEffortMismatch(
                f"Codex model {self.model} does not advertise effort {self.effort}"
            )

    async def start_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession:
        return await self._start_thread(
            case_sandbox,
            developer_instructions,
            dynamic_tools=terra_read_tool_definitions(),
        )

    async def start_response_case(
        self,
        case_sandbox: Path,
        developer_instructions: str,
    ) -> TerraSession:
        """Start a fresh response-only thread with no callable benchmark tools."""

        return await self._start_thread(
            case_sandbox,
            developer_instructions,
            dynamic_tools=[],
        )

    async def _start_thread(
        self,
        case_sandbox: Path,
        developer_instructions: str,
        *,
        dynamic_tools: list[dict[str, Any]],
    ) -> TerraSession:
        sandbox = case_sandbox.resolve()
        sandbox.mkdir(parents=True, exist_ok=True)
        if any(sandbox.iterdir()):
            raise TerraProviderError("case sandbox must be empty when a thread starts")
        response = await self.client.request(
            "thread/start",
            {
                "allowProviderModelFallback": False,
                "approvalPolicy": "never",
                "cwd": str(sandbox),
                "developerInstructions": developer_instructions,
                "dynamicTools": dynamic_tools,
                "ephemeral": True,
                "model": self.model,
                "permissions": FUSEBENCH_PERMISSION_PROFILE,
                "runtimeWorkspaceRoots": [str(sandbox)],
                "serviceName": "fusebench",
            },
        )
        reported_model = response.get("model")
        if reported_model != self.model:
            raise TerraModelMismatch(
                f"Codex started {reported_model!r}; required exact {self.model!r}"
            )
        reported_effort = response.get("reasoningEffort")
        thread = response.get("thread")
        if not isinstance(thread, Mapping):
            raise TerraProviderError("thread/start omitted thread")
        thread_id = thread.get("id")
        session_id = thread.get("sessionId")
        if not isinstance(thread_id, str) or not isinstance(session_id, str):
            raise TerraProviderError("thread/start omitted thread/session id")
        active_profile = response.get("activePermissionProfile")
        if (
            not isinstance(active_profile, Mapping)
            or active_profile.get("id") != FUSEBENCH_PERMISSION_PROFILE
        ):
            raise TerraProviderError(
                "Codex did not activate the required read-only permission profile"
            )
        effective_sandbox = response.get("sandbox")
        if (
            not isinstance(effective_sandbox, Mapping)
            or effective_sandbox.get("type") != "readOnly"
            or effective_sandbox.get("networkAccess", False) is not False
        ):
            raise TerraProviderError("Codex did not activate read-only, network-off sandboxing")
        reported_roots = response.get("runtimeWorkspaceRoots")
        if not isinstance(reported_roots, list) or reported_roots != [str(sandbox)]:
            raise TerraProviderError("Codex runtime workspace roots differ from case sandbox")
        return TerraSession(
            thread_id=thread_id,
            session_id=session_id,
            case_sandbox=sandbox,
            effective_sandbox=dict(effective_sandbox),
            runtime_workspace_roots=(sandbox,),
            thread_start_effort=(
                reported_effort if isinstance(reported_effort, str) else None
            ),
        )

    async def turn(
        self,
        session: TerraSession,
        message: str,
        *,
        tool_handler: Callable[
            [ReadTool, dict[str, Any]], Awaitable[Mapping[str, Any]]
        ]
        | None = None,
    ) -> TerraTurnResult:
        async with self._turn_lock:
            return await self._turn_locked(session, message, tool_handler)

    async def _turn_locked(
        self,
        session: TerraSession,
        message: str,
        tool_handler: Callable[
            [ReadTool, dict[str, Any]], Awaitable[Mapping[str, Any]]
        ]
        | None,
    ) -> TerraTurnResult:
        try:
            response = await self.client.request(
                "turn/start",
                {
                    "effort": self.effort,
                    "input": [{"type": "text", "text": message}],
                    "model": self.model,
                    "outputSchema": terra_output_schema(),
                    "permissions": FUSEBENCH_PERMISSION_PROFILE,
                    "threadId": session.thread_id,
                },
                timeout_seconds=self.turn_timeout_seconds,
            )
        except CodexProtocolError as exc:
            if exc.kind in {"usageLimitExceeded", "rateLimitExceeded"}:
                raise CodexUsageLimitExceeded("Codex usage limit exceeded") from exc
            raise
        turn = response.get("turn")
        if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
            raise TerraProviderError("turn/start omitted turn id")
        turn_id = turn["id"]
        events_task = asyncio.create_task(
            self.client.wait_for_turn(
                turn_id,
                timeout_seconds=self.turn_timeout_seconds,
            )
        )
        request_task = asyncio.create_task(
            self.client.next_server_request(timeout_seconds=self.turn_timeout_seconds)
        )
        dynamic_requests: list[dict[str, Any]] = []
        try:
            while True:
                done, _ = await asyncio.wait(
                    {events_task, request_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if request_task in done:
                    request = await request_task
                    dynamic_requests.append(
                        await self._handle_tool_request(
                            request,
                            session=session,
                            turn_id=turn_id,
                            tool_handler=tool_handler,
                        )
                    )
                    request_task = asyncio.create_task(
                        self.client.next_server_request(
                            timeout_seconds=self.turn_timeout_seconds
                        )
                    )
                if events_task in done:
                    events = await events_task
                    break
        finally:
            request_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await request_task
        completion = next(
            (event for event in reversed(events) if event.get("method") == "turn/completed"),
            None,
        )
        if completion is None:
            raise TerraProviderError("turn ended without completion event")
        completed_turn = completion.get("params", {}).get("turn", {})
        if completed_turn.get("status") != "completed":
            self._raise_turn_failure(completed_turn)

        token_events = tuple(
            event for event in events if event.get("method") == "thread/tokenUsage/updated"
        )
        if not token_events:
            raise TerraProviderError("Terra turn emitted no token usage event")
        usage = _parse_usage(token_events[-1])
        raw_events = tuple(dict(event) for event in events)
        messages = [
            event.get("params", {}).get("item", {}).get("text")
            for event in events
            if event.get("method") == "item/completed"
            and event.get("params", {}).get("item", {}).get("type") == "agentMessage"
        ]
        raw_text = next((text for text in reversed(messages) if isinstance(text, str)), None)
        if raw_text is None:
            raise TerraStructuredOutputError(
                "Terra turn emitted no final agent message",
                turn_id=turn_id,
                usage=usage,
                raw_token_events=token_events,
                raw_events=raw_events,
                dynamic_tool_requests=tuple(dynamic_requests),
            )
        try:
            output = parse_terra_output(raw_text)
        except TerraStructuredOutputError as exc:
            raise TerraStructuredOutputError(
                str(exc),
                turn_id=turn_id,
                raw_text=raw_text,
                usage=usage,
                raw_token_events=token_events,
                raw_events=raw_events,
                dynamic_tool_requests=tuple(dynamic_requests),
            ) from exc
        return TerraTurnResult(
            thread_id=session.thread_id,
            turn_id=turn_id,
            output=output,
            raw_text=raw_text,
            usage=usage,
            raw_token_events=token_events,
            dynamic_tool_requests=tuple(dynamic_requests),
            raw_events=raw_events,
        )

    async def response_turn(
        self,
        session: TerraSession,
        message: str,
    ) -> TerraResponseResult:
        """Generate free text on a response-only thread without a decision schema."""

        async with self._turn_lock:
            try:
                response = await self.client.request(
                    "turn/start",
                    {
                        "effort": self.effort,
                        "input": [{"type": "text", "text": message}],
                        "model": self.model,
                        "permissions": FUSEBENCH_PERMISSION_PROFILE,
                        "threadId": session.thread_id,
                    },
                    timeout_seconds=self.turn_timeout_seconds,
                )
            except CodexProtocolError as exc:
                if exc.kind in {"usageLimitExceeded", "rateLimitExceeded"}:
                    raise CodexUsageLimitExceeded("Codex usage limit exceeded") from exc
                raise
            turn = response.get("turn")
            if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
                raise TerraProviderError("turn/start omitted turn id")
            turn_id = turn["id"]
            events = await self.client.wait_for_turn(
                turn_id,
                timeout_seconds=self.turn_timeout_seconds,
            )
            completion = next(
                (
                    event
                    for event in reversed(events)
                    if event.get("method") == "turn/completed"
                ),
                None,
            )
            if completion is None:
                raise TerraProviderError("response turn ended without completion event")
            completed_turn = completion.get("params", {}).get("turn", {})
            if completed_turn.get("status") != "completed":
                self._raise_turn_failure(completed_turn)
            token_events = tuple(
                event
                for event in events
                if event.get("method") == "thread/tokenUsage/updated"
            )
            if not token_events:
                raise TerraProviderError("Terra response turn emitted no token usage event")
            usage = _parse_usage(token_events[-1])
            raw_events = tuple(dict(event) for event in events)
            messages = [
                event.get("params", {}).get("item", {}).get("text")
                for event in events
                if event.get("method") == "item/completed"
                and event.get("params", {}).get("item", {}).get("type")
                == "agentMessage"
            ]
            text = next(
                (item.strip() for item in reversed(messages) if isinstance(item, str)),
                None,
            )
            if not text:
                raise TerraStructuredOutputError(
                    "Terra response turn emitted no message",
                    turn_id=turn_id,
                    usage=usage,
                    raw_token_events=token_events,
                    raw_events=raw_events,
                )
            return TerraResponseResult(
                thread_id=session.thread_id,
                turn_id=turn_id,
                text=text,
                usage=usage,
                raw_token_events=token_events,
                raw_events=raw_events,
            )

    async def _handle_tool_request(
        self,
        request: Mapping[str, Any],
        *,
        session: TerraSession,
        turn_id: str,
        tool_handler: Callable[
            [ReadTool, dict[str, Any]], Awaitable[Mapping[str, Any]]
        ]
        | None,
    ) -> dict[str, Any]:
        request_id = request.get("id")
        params = request.get("params")
        if (
            request.get("method") != "item/tool/call"
            or not isinstance(request_id, int)
            or not isinstance(params, Mapping)
            or params.get("threadId") != session.thread_id
            or params.get("turnId") != turn_id
        ):
            raise TerraProviderError("unexpected or out-of-scope Codex server request")
        try:
            tool = ReadTool(params.get("tool"))
            arguments = dict(params.get("arguments"))
            validated = TerraReadRequest(
                kind="read_tool",
                tool=tool,
                arguments=arguments,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            await self.client.respond(
                request_id,
                {
                    "success": False,
                    "contentItems": [
                        {"type": "inputText", "text": '{"error":"invalid_tool_request"}'}
                    ],
                },
            )
            raise TerraProviderError("Terra issued an invalid dynamic tool request") from exc
        if tool_handler is None:
            await self.client.respond(
                request_id,
                {
                    "success": False,
                    "contentItems": [
                        {"type": "inputText", "text": '{"error":"tool_handler_missing"}'}
                    ],
                },
            )
            raise TerraProviderError("dynamic tool request has no handler")
        result = await tool_handler(validated.tool, validated.arguments)
        if not isinstance(result, Mapping):
            raise TerraProviderError("dynamic tool handler result must be an object")
        await self.client.respond(
            request_id,
            {
                "success": True,
                "contentItems": [
                    {"type": "inputText", "text": canonical_json(dict(result))}
                ],
            },
        )
        return {
            "call_id": params.get("callId"),
            "tool": validated.tool.value,
            "arguments": validated.arguments,
        }

    async def close(self) -> None:
        await self.client.close()

    @staticmethod
    def _raise_turn_failure(turn: Mapping[str, Any]) -> None:
        error = turn.get("error")
        info = error.get("codexErrorInfo") if isinstance(error, Mapping) else None
        if info in {"usageLimitExceeded", "rateLimitExceeded"}:
            raise CodexUsageLimitExceeded("Codex usage limit exceeded")
        raise TerraProviderError("Codex turn did not complete successfully")


def _parse_usage(event: Mapping[str, Any]) -> TerraUsage:
    params = event.get("params")
    token_usage = params.get("tokenUsage") if isinstance(params, Mapping) else None
    last = token_usage.get("last") if isinstance(token_usage, Mapping) else None
    if not isinstance(last, Mapping):
        raise TerraProviderError("Terra token usage event is malformed")
    try:
        return TerraUsage(
            input_tokens=last["inputTokens"],
            cached_input_tokens=last["cachedInputTokens"],
            output_tokens=last["outputTokens"],
            reasoning_output_tokens=last["reasoningOutputTokens"],
        )
    except (KeyError, ValidationError, TypeError) as exc:
        raise TerraProviderError("Terra token usage event is malformed") from exc
