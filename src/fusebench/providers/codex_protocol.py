"""Newline-delimited JSON-RPC client for Codex App Server."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class CodexProtocolError(RuntimeError):
    """Sanitized App Server protocol or request failure."""

    def __init__(self, message: str, *, code: int | None = None, kind: str | None = None):
        super().__init__(message)
        self.code = code
        self.kind = kind

    @classmethod
    def from_error(cls, error: Mapping[str, Any]) -> CodexProtocolError:
        code = error.get("code")
        data = error.get("data")
        kind: str | None = None
        if isinstance(data, Mapping):
            candidate = data.get("type") or data.get("codexErrorInfo")
            if isinstance(candidate, str):
                kind = candidate
        suffix = f", kind={kind}" if kind else ""
        return cls(f"Codex App Server error (code={code}{suffix})", code=code, kind=kind)


class CodexProcessExited(CodexProtocolError):
    """The App Server transport ended while requests were pending."""


class CodexRequestTimeout(CodexProtocolError):
    """An App Server request or turn exceeded its harness timeout."""


def parse_json_line(line: bytes | str) -> dict[str, Any]:
    """Parse exactly one App Server JSONL message without echoing unsafe content."""

    try:
        value = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CodexProtocolError("App Server emitted invalid JSON") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("App Server message must be a JSON object")
    return value


class JsonRpcTransport(Protocol):
    async def send(self, message: Mapping[str, Any]) -> None: ...

    async def receive(self) -> Mapping[str, Any]: ...

    async def close(self) -> None: ...


class StdioJsonRpcTransport:
    """Own a single Codex App Server subprocess over JSONL stdio."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def start(
        cls,
        command: Sequence[str] = ("codex", "app-server", "--stdio"),
    ) -> StdioJsonRpcTransport:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process)

    async def send(self, message: Mapping[str, Any]) -> None:
        if self.process.stdin is None or self.process.returncode is not None:
            raise CodexProcessExited("Codex App Server is not running")
        payload = json.dumps(message, sort_keys=True, allow_nan=False, separators=(",", ":"))
        self.process.stdin.write(payload.encode("utf-8") + b"\n")
        try:
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise CodexProcessExited("Codex App Server stdin closed") from exc

    async def receive(self) -> Mapping[str, Any]:
        if self.process.stdout is None:
            raise CodexProcessExited("Codex App Server stdout is unavailable")
        line = await self.process.stdout.readline()
        if line:
            return parse_json_line(line)
        return_code = await self.process.wait()
        raise CodexProcessExited(f"Codex App Server exited with code {return_code}")

    async def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()
        self._stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._stderr_task

    async def _drain_stderr(self) -> None:
        if self.process.stderr is None:
            return
        while line := await self.process.stderr.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())


class CodexProtocolClient:
    """Route App Server responses and turn notifications without semantic retries."""

    def __init__(
        self,
        transport: JsonRpcTransport,
        *,
        request_timeout_seconds: float = 120.0,
        experimental_api: bool = False,
    ) -> None:
        self.transport = transport
        self.request_timeout_seconds = request_timeout_seconds
        self.experimental_api = experimental_api
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Mapping[str, Any]]] = {}
        self._turn_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._server_requests: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._fatal_error: BaseException | None = None

    async def initialize(self) -> Mapping[str, Any]:
        if self._reader_task is not None:
            raise CodexProtocolError("Codex protocol client is already initialized")
        self._reader_task = asyncio.create_task(self._reader_loop())
        params: dict[str, Any] = {
            "clientInfo": {
                "name": "fusebench",
                "title": "FuseBench",
                "version": "1.0.1",
            }
        }
        if self.experimental_api:
            params["capabilities"] = {"experimentalApi": True}
        result = await self.request("initialize", params)
        await self.notify("initialized", {})
        return result

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        if self._fatal_error is not None:
            raise self._fatal_error
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Mapping[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.transport.send({"id": request_id, "method": method, "params": dict(params)})
            timeout = timeout_seconds or self.request_timeout_seconds
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError as exc:
                raise CodexRequestTimeout(f"Codex request timed out: {method}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: Mapping[str, Any]) -> None:
        await self.transport.send({"method": method, "params": dict(params)})

    async def next_server_request(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Return the next App Server initiated request."""

        timeout = timeout_seconds or self.request_timeout_seconds
        try:
            return await asyncio.wait_for(self._server_requests.get(), timeout=timeout)
        except TimeoutError as exc:
            raise CodexRequestTimeout("Codex server request timed out") from exc

    async def respond(self, request_id: int, result: Mapping[str, Any]) -> None:
        """Answer an App Server initiated request."""

        await self.transport.send({"id": request_id, "result": dict(result)})

    async def wait_for_turn(
        self,
        turn_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        queue = self._turn_queues.setdefault(turn_id, asyncio.Queue())
        events: list[dict[str, Any]] = []
        timeout = timeout_seconds or self.request_timeout_seconds

        async def collect() -> list[dict[str, Any]]:
            while True:
                if self._fatal_error is not None:
                    raise self._fatal_error
                event = await queue.get()
                events.append(event)
                if event.get("method") == "turn/completed":
                    return events

        try:
            return await asyncio.wait_for(collect(), timeout=timeout)
        except TimeoutError as exc:
            raise CodexRequestTimeout(f"Codex turn timed out: {turn_id}") from exc
        finally:
            self._turn_queues.pop(turn_id, None)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        await self.transport.close()

    async def _reader_loop(self) -> None:
        try:
            while True:
                message = dict(await self.transport.receive())
                if "id" in message and "method" in message:
                    self._server_requests.put_nowait(message)
                elif "id" in message:
                    self._handle_response(message)
                elif "method" in message:
                    self._handle_notification(message)
                else:
                    raise CodexProtocolError("App Server message has no id or method")
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._fatal_error = exc
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(exc)

    def _handle_response(self, message: Mapping[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            raise CodexProtocolError("App Server response id must be an integer")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        error = message.get("error")
        if isinstance(error, Mapping):
            future.set_exception(CodexProtocolError.from_error(error))
            return
        result = message.get("result")
        if not isinstance(result, Mapping):
            future.set_exception(CodexProtocolError("App Server response omitted result"))
            return
        future.set_result(result)

    def _handle_notification(self, message: Mapping[str, Any]) -> None:
        turn_id = _notification_turn_id(message)
        if turn_id is None:
            return
        queue = self._turn_queues.setdefault(turn_id, asyncio.Queue())
        queue.put_nowait(dict(message))


def _notification_turn_id(message: Mapping[str, Any]) -> str | None:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return None
    direct = params.get("turnId")
    if isinstance(direct, str):
        return direct
    turn = params.get("turn")
    if isinstance(turn, Mapping) and isinstance(turn.get("id"), str):
        return turn["id"]
    return None
