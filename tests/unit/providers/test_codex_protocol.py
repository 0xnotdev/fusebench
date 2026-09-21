import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from fusebench.providers.codex_protocol import (
    CodexProcessExited,
    CodexProtocolClient,
    CodexProtocolError,
    CodexRequestTimeout,
    parse_json_line,
)


class ScriptedTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[Mapping[str, Any] | Exception] = asyncio.Queue()
        self.responders: dict[str, Any] = {}
        self.closed = False

    async def send(self, message: Mapping[str, Any]) -> None:
        copied = dict(message)
        self.sent.append(copied)
        if "id" in copied and copied.get("method") in self.responders:
            result = self.responders[copied["method"]]
            if callable(result):
                result = result(copied)
            await self.incoming.put({"id": copied["id"], "result": result})

    async def receive(self) -> Mapping[str, Any]:
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def initialized_transport() -> ScriptedTransport:
    transport = ScriptedTransport()
    transport.responders["initialize"] = {
        "userAgent": "codex-cli/0.155.0-alpha.9.2",
        "platformFamily": "windows",
        "platformOs": "windows",
    }
    return transport


def test_parse_json_line_rejects_malformed_or_non_object_messages() -> None:
    assert parse_json_line(b'{"id":1,"result":{}}\n') == {"id": 1, "result": {}}
    with pytest.raises(CodexProtocolError, match="invalid JSON"):
        parse_json_line(b"not-json\n")
    with pytest.raises(CodexProtocolError, match="JSON object"):
        parse_json_line(b"[]\n")


@pytest.mark.asyncio
async def test_initialize_handshake_uses_monotonic_ids_and_initialized_notification() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(transport, request_timeout_seconds=0.2)

    result = await client.initialize()
    transport.responders["account/read"] = {"account": {"type": "chatgpt"}}
    account = await client.request("account/read", {})

    assert result["platformFamily"] == "windows"
    assert account["account"]["type"] == "chatgpt"
    assert transport.sent == [
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "fusebench",
                    "title": "FuseBench",
                    "version": "1.0.1",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"id": 2, "method": "account/read", "params": {}},
    ]
    await client.close()


@pytest.mark.asyncio
async def test_experimental_capability_is_explicit_opt_in() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(
        transport,
        request_timeout_seconds=0.2,
        experimental_api=True,
    )

    await client.initialize()

    assert transport.sent[0]["params"]["capabilities"] == {"experimentalApi": True}
    await client.close()


@pytest.mark.asyncio
async def test_notifications_are_routed_by_turn_even_before_waiter_starts() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(transport, request_timeout_seconds=0.2)
    await client.initialize()

    await transport.incoming.put(
        {
            "method": "item/completed",
            "params": {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "item": {"id": "item-a", "type": "agentMessage", "text": "{}"},
            },
        }
    )
    await transport.incoming.put(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-a",
                "turn": {"id": "turn-a", "status": "completed", "items": []},
            },
        }
    )

    events = await client.wait_for_turn("turn-a", timeout_seconds=0.2)

    assert [event["method"] for event in events] == [
        "item/completed",
        "turn/completed",
    ]
    await client.close()


@pytest.mark.asyncio
async def test_server_request_can_be_received_and_answered() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(transport, request_timeout_seconds=0.2)
    await client.initialize()
    await transport.incoming.put(
        {
            "id": 41,
            "method": "item/tool/call",
            "params": {
                "callId": "call-1",
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tool": "probe_echo",
                "arguments": {"value": "ping"},
            },
        }
    )

    request = await client.next_server_request(timeout_seconds=0.2)
    await client.respond(
        request["id"],
        {"success": True, "contentItems": [{"type": "inputText", "text": "pong"}]},
    )

    assert request["method"] == "item/tool/call"
    assert transport.sent[-1] == {
        "id": 41,
        "result": {
            "success": True,
            "contentItems": [{"type": "inputText", "text": "pong"}],
        },
    }
    await client.close()


@pytest.mark.asyncio
async def test_request_timeout_does_not_retry_semantically() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(transport, request_timeout_seconds=0.01)
    await client.initialize()

    with pytest.raises(CodexRequestTimeout):
        await client.request("model/list", {})

    assert [message["method"] for message in transport.sent].count("model/list") == 1
    await client.close()


@pytest.mark.asyncio
async def test_process_death_fails_pending_requests_closed() -> None:
    transport = initialized_transport()
    client = CodexProtocolClient(transport, request_timeout_seconds=0.2)
    await client.initialize()

    pending = asyncio.create_task(client.request("model/list", {}))
    await asyncio.sleep(0)
    await transport.incoming.put(CodexProcessExited("exit code 1"))

    with pytest.raises(CodexProcessExited, match="exit code 1"):
        await pending
    await client.close()


def test_json_rpc_error_is_sanitized_and_classified() -> None:
    error = CodexProtocolError.from_error(
        {"code": -32000, "message": "token=secret", "data": {"type": "usageLimitExceeded"}}
    )
    assert "secret" not in str(error)
    assert error.code == -32000
    assert error.kind == "usageLimitExceeded"
