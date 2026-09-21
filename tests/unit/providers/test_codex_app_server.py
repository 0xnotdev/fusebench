import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fusebench.contracts.actions import Action
from fusebench.contracts.tools import ReadTool
from fusebench.providers.codex_app_server import (
    CodexAppServerProvider,
    CodexUsageLimitExceeded,
    TerraFinalDecision,
    TerraModelMismatch,
    TerraReadRequest,
    TerraStructuredOutputError,
    parse_terra_output,
    terra_output_schema,
    terra_read_tool_definitions,
)
from fusebench.providers.codex_protocol import CodexProtocolClient


class TerraTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[Mapping[str, Any] | Exception] = asyncio.Queue()
        self.thread_count = 0
        self.turn_count = 0
        self.turn_error: dict[str, Any] | None = None
        self.emit_tool_call = False
        self.pending_turn_id: str | None = None
        self.output_text = (
            '{"action_probabilities":{"REFUND":0.02,"RESHIP":0.91,'
            '"REQUEST_INFO":0.02,"WAIT":0.03,"ESCALATE":0.02},'
            '"reason_code":"SHIPPING_STALLED_STOCK_AVAILABLE"}'
        )

    async def send(self, message: Mapping[str, Any]) -> None:
        copied = dict(message)
        self.sent.append(copied)
        if "method" not in copied:
            assert copied["id"] == 99
            assert copied["result"]["success"] is True
            await self._finish_turn()
            return
        if "id" not in copied:
            return
        method = copied["method"]
        if method == "initialize":
            result = {"userAgent": "codex-cli/0.155.0-alpha.9.2"}
        elif method == "account/read":
            result = {
                "account": {"type": "chatgpt", "email": None, "planType": "pro"},
                "requiresOpenaiAuth": True,
            }
        elif method == "model/list":
            result = {
                "data": [
                    {
                        "id": "gpt-5.6-terra",
                        "model": "gpt-5.6-terra",
                        "defaultReasoningEffort": "medium",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "medium", "description": "Balanced"}
                        ],
                    }
                ]
            }
        elif method == "thread/start":
            self.thread_count += 1
            result = {
                "thread": {
                    "id": f"thread-{self.thread_count}",
                    "sessionId": f"thread-{self.thread_count}",
                },
                "model": "gpt-5.6-terra",
                "reasoningEffort": "medium",
                "activePermissionProfile": {"id": copied["params"]["permissions"]},
                "approvalPolicy": "never",
                "runtimeWorkspaceRoots": copied["params"]["runtimeWorkspaceRoots"],
                "sandbox": {"type": "readOnly", "networkAccess": False},
            }
        elif method == "turn/start":
            if self.turn_error is not None:
                await self.incoming.put({"id": copied["id"], "error": self.turn_error})
                return
            self.turn_count += 1
            turn_id = f"turn-{self.turn_count}"
            self.pending_turn_id = turn_id
            result = {"turn": {"id": turn_id, "status": "inProgress", "items": []}}
            await self.incoming.put({"id": copied["id"], "result": result})
            if self.emit_tool_call:
                await self.incoming.put(
                    {
                        "id": 99,
                        "method": "item/tool/call",
                        "params": {
                            "arguments": {"order_id": "order-1"},
                            "callId": "call-1",
                            "threadId": f"thread-{self.thread_count}",
                            "tool": "get_tracking",
                            "turnId": turn_id,
                        },
                    }
                )
                return
            await self._finish_turn()
            return
        else:
            raise AssertionError(f"unexpected method: {method}")
        await self.incoming.put({"id": copied["id"], "result": result})

    async def _finish_turn(self) -> None:
        assert self.pending_turn_id is not None
        turn_id = self.pending_turn_id
        self.pending_turn_id = None
        await self.incoming.put(
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": f"thread-{self.thread_count}",
                    "turnId": turn_id,
                    "tokenUsage": {
                        "last": {
                            "inputTokens": 111,
                            "cachedInputTokens": 11,
                            "outputTokens": 22,
                            "reasoningOutputTokens": 7,
                            "totalTokens": 133,
                        },
                        "total": {
                            "inputTokens": 111,
                            "cachedInputTokens": 11,
                            "outputTokens": 22,
                            "reasoningOutputTokens": 7,
                            "totalTokens": 133,
                        },
                        "modelContextWindow": 1000,
                    },
                },
            }
        )
        await self.incoming.put(
            {
                "method": "item/completed",
                "params": {
                    "threadId": f"thread-{self.thread_count}",
                    "turnId": turn_id,
                    "item": {
                        "id": "message-1",
                        "type": "agentMessage",
                        "text": self.output_text,
                    },
                },
            }
        )
        await self.incoming.put(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": f"thread-{self.thread_count}",
                    "turn": {"id": turn_id, "status": "completed", "items": []},
                },
            }
        )

    async def receive(self) -> Mapping[str, Any]:
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        return None


async def make_provider(transport: TerraTransport) -> CodexAppServerProvider:
    client = CodexProtocolClient(
        transport,
        request_timeout_seconds=0.2,
        experimental_api=True,
    )
    provider = CodexAppServerProvider(client, turn_timeout_seconds=0.2)
    await provider.initialize_and_check()
    return provider


def test_output_schema_and_dynamic_tools_are_exact() -> None:
    schema = terra_output_schema()
    probabilities = schema["properties"]["action_probabilities"]
    definitions = terra_read_tool_definitions()

    assert schema["additionalProperties"] is False
    assert set(probabilities["properties"]) == {action.value for action in Action}
    assert set(schema["properties"]) == {"action_probabilities", "reason_code"}
    assert {definition["name"] for definition in definitions} == {
        tool.value for tool in ReadTool
    }
    assert all(definition["type"] == "function" for definition in definitions)


def test_parse_terra_output_accepts_tool_request_and_final_distribution() -> None:
    request = parse_terra_output(
        '{"kind":"read_tool","tool":"get_tracking",'
        '"arguments":{"order_id":"o-1"},"action_probabilities":null,'
        '"reason_code":null}'
    )
    final = parse_terra_output(
        '{"kind":"final","tool":null,"arguments":null,'
        '"action_probabilities":{"REFUND":0.02,"RESHIP":0.91,'
        '"REQUEST_INFO":0.02,"WAIT":0.03,"ESCALATE":0.02},'
        '"reason_code":"READY"}'
    )

    assert request == TerraReadRequest(
        kind="read_tool", tool=ReadTool.GET_TRACKING, arguments={"order_id": "o-1"}
    )
    assert isinstance(final, TerraFinalDecision)
    assert final.selected_action is Action.RESHIP


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"kind":"read_tool","tool":"get_tracking","arguments":null,'
        '"action_probabilities":null,"reason_code":null}',
        '{"kind":"final","tool":null,"arguments":null,'
        '"action_probabilities":{"REFUND":1},"reason_code":"BAD"}',
    ],
)
def test_parse_terra_output_fails_closed(raw: str) -> None:
    with pytest.raises(TerraStructuredOutputError):
        parse_terra_output(raw)


@pytest.mark.asyncio
async def test_preflight_requires_exact_model_and_medium_effort() -> None:
    transport = TerraTransport()
    provider = await make_provider(transport)

    assert provider.account_type == "chatgpt"
    assert provider.model == "gpt-5.6-terra"
    assert provider.effort == "medium"
    assert provider.tool_protocol == "dynamic_tools"
    await provider.close()


@pytest.mark.asyncio
async def test_model_catalog_mismatch_aborts() -> None:
    transport = TerraTransport()
    original_send = transport.send

    async def wrong_model_send(message: Mapping[str, Any]) -> None:
        if message.get("method") == "model/list":
            transport.sent.append(dict(message))
            await transport.incoming.put({"id": message["id"], "result": {"data": []}})
            return
        await original_send(message)

    transport.send = wrong_model_send  # type: ignore[method-assign]
    client = CodexProtocolClient(transport, request_timeout_seconds=0.2)
    provider = CodexAppServerProvider(client, turn_timeout_seconds=0.2)

    with pytest.raises(TerraModelMismatch):
        await provider.initialize_and_check()
    await provider.close()


@pytest.mark.asyncio
async def test_fresh_thread_and_turn_are_strictly_configured(tmp_path: Path) -> None:
    transport = TerraTransport()
    provider = await make_provider(transport)

    first = await provider.start_case(tmp_path / "case-1", "policy and tool rules")
    second = await provider.start_case(tmp_path / "case-2", "policy and tool rules")
    result = await provider.turn(first, "visible case JSON")

    assert first.thread_id != second.thread_id
    assert first.permission_profile == ":read-only"
    assert first.effective_sandbox == {"type": "readOnly", "networkAccess": False}
    assert first.runtime_workspace_roots == ((tmp_path / "case-1").resolve(),)
    thread_request = next(
        item for item in transport.sent if item.get("method") == "thread/start"
    )
    assert thread_request["params"] == {
        "allowProviderModelFallback": False,
        "approvalPolicy": "never",
        "cwd": str((tmp_path / "case-1").resolve()),
        "developerInstructions": "policy and tool rules",
        "dynamicTools": terra_read_tool_definitions(),
        "ephemeral": True,
        "model": "gpt-5.6-terra",
        "permissions": ":read-only",
        "runtimeWorkspaceRoots": [str((tmp_path / "case-1").resolve())],
        "serviceName": "fusebench",
    }
    turn_request = next(item for item in transport.sent if item.get("method") == "turn/start")
    assert turn_request["params"]["effort"] == "medium"
    assert turn_request["params"]["model"] == "gpt-5.6-terra"
    assert turn_request["params"]["permissions"] == ":read-only"
    assert "sandboxPolicy" not in turn_request["params"]
    assert turn_request["params"]["outputSchema"] == terra_output_schema()
    assert isinstance(result.output, TerraFinalDecision)
    assert result.usage.input_tokens == 111
    assert result.usage.output_tokens == 22
    assert result.raw_token_events[0]["method"] == "thread/tokenUsage/updated"
    await provider.close()


@pytest.mark.asyncio
async def test_response_thread_has_no_tools_or_decision_schema(tmp_path: Path) -> None:
    transport = TerraTransport()
    transport.output_text = "A replacement is on the way."
    provider = await make_provider(transport)

    session = await provider.start_response_case(
        tmp_path / "response-case",
        "Write a short response without changing the action.",
    )
    result = await provider.response_turn(session, "locked action payload")

    thread_request = next(
        item for item in transport.sent if item.get("method") == "thread/start"
    )
    turn_request = next(item for item in transport.sent if item.get("method") == "turn/start")
    assert thread_request["params"]["dynamicTools"] == []
    assert "outputSchema" not in turn_request["params"]
    assert result.text == "A replacement is on the way."
    assert result.usage.input_tokens == 111
    await provider.close()


@pytest.mark.asyncio
async def test_dynamic_tool_callback_is_scoped_and_serialized(tmp_path: Path) -> None:
    transport = TerraTransport()
    transport.emit_tool_call = True
    provider = await make_provider(transport)
    session = await provider.start_case(tmp_path / "case", "rules")
    calls: list[tuple[ReadTool, dict[str, Any]]] = []

    async def handle(tool: ReadTool, arguments: dict[str, Any]) -> Mapping[str, Any]:
        calls.append((tool, arguments))
        return {"order_id": "order-1", "carrier_status": "in_transit"}

    result = await provider.turn(session, "case", tool_handler=handle)

    assert calls == [(ReadTool.GET_TRACKING, {"order_id": "order-1"})]
    assert result.dynamic_tool_requests[0]["tool"] == "get_tracking"
    response = next(item for item in transport.sent if "method" not in item)
    assert response["result"]["contentItems"] == [
        {
            "type": "inputText",
            "text": '{"carrier_status":"in_transit","order_id":"order-1"}',
        }
    ]
    await provider.close()


@pytest.mark.asyncio
async def test_usage_limit_is_classified_without_retry() -> None:
    transport = TerraTransport()
    provider = await make_provider(transport)
    session = await provider.start_case(Path("artifacts/case_sandboxes/test/case"), "rules")
    transport.turn_error = {
        "code": -32000,
        "message": "limit reached",
        "data": {"type": "usageLimitExceeded"},
    }

    with pytest.raises(CodexUsageLimitExceeded):
        await provider.turn(session, "case")

    assert [item["method"] for item in transport.sent].count("turn/start") == 1
    await provider.close()
