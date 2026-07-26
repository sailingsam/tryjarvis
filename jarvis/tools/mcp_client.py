"""MCP adapter — plug external tool servers into our tool-use loop.

MCP (Model Context Protocol) is the standard way apps expose tools. Instead of
writing a Calendar/Gmail/Slack integration by hand, we run their MCP server and
its tools show up here as ordinary `Tool` objects in the same registry the
brain already uses. This is the multiplier: one adapter, many integrations.

The MCP SDK is async; our app is sync. So each server runs in a background
thread that owns an asyncio loop and keeps the session open; sync calls are
marshalled onto that loop. Safety: we honour the tool's `readOnlyHint` — a
read-only tool runs freely, anything else is gated behind confirmation.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time

from .base import Tool

# Transient connection hiccups (a cold Baileys socket, mid-reconnect). Baileys
# recovers on its own, so one retry after a short pause turns these into success.
_TRANSIENT = ("connection closed", "timed out", "time-out", "not active", "not connected")


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]


def _result_text(result) -> str:
    """Flatten an MCP CallToolResult's content blocks into plain text."""
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    out = "\n".join(parts).strip()
    if getattr(result, "isError", False):
        return f"(tool error) {out}"
    return out or "(no output)"


class MCPClient:
    """A persistent connection to one MCP server, usable from sync code."""

    def __init__(self, name: str, command: str, args: list[str], env: dict | None = None,
                 cwd: str | None = None):
        self.name = name
        self._command = command
        self._args = args
        self._env = env
        self._cwd = cwd
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        self.tools: list = []       # raw MCP tool metadata

    def start(self, timeout: float = 30.0) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError(f"MCP server '{self.name}' did not start in time")
        if self._error:
            raise self._error

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop = asyncio.Event()
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:            # startup/transport failure
            self._error = e
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command, args=self._args, env=self._env, cwd=self._cwd
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.tools = (await session.list_tools()).tools
                self._session = session
                self._ready.set()
                await self._stop.wait()   # keep the session open until close()

    def call(self, remote_name: str, arguments: dict, timeout: float = 120.0) -> str:
        fut = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(remote_name, arguments), self._loop
        )
        return _result_text(fut.result(timeout=timeout))

    def close(self) -> None:
        if self._loop and self._stop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout=5)


class MCPTool(Tool):
    """Wraps one MCP server tool as a Jarvis Tool."""

    def __init__(self, client: MCPClient, meta):
        self._client = client
        self._remote_name = meta.name
        self.name = f"{_sanitize(client.name)}_{_sanitize(meta.name)}"[:64]
        self.description = getattr(meta, "description", "") or ""
        self.input_schema = getattr(meta, "inputSchema", None) or {"type": "object", "properties": {}}
        self.needs_confirm = _infer_confirm(meta)

    def execute(self, **kwargs) -> str:
        result = self._safe_call(kwargs)
        if any(t in result.lower() for t in _TRANSIENT):
            time.sleep(3)                      # let the socket finish connecting
            result = self._safe_call(kwargs)
        return result

    def _safe_call(self, kwargs: dict) -> str:
        try:
            return self._client.call(self._remote_name, kwargs)
        except Exception as e:                 # surface as text so the retry logic can see it
            return f"(tool error) {e}"

    def confirmation(self, **kwargs) -> str:
        return f"Run {self.name} with {kwargs}? (yes/no)"


# Verbs that imply a tool changes the world → confirm before running.
_MUTATION_VERBS = (
    "send", "post", "create", "delete", "remove", "update", "reply", "write",
    "add", "set", "mark", "revoke", "edit", "archive", "mute", "block", "leave",
)


def _infer_confirm(meta) -> bool:
    """Decide if a tool needs confirmation. Honour the server's readOnlyHint if
    present; otherwise guess from the tool name — mutation verbs → confirm,
    everything else (list/get/search/read) runs freely."""
    ann = getattr(meta, "annotations", None)
    if ann is not None and getattr(ann, "readOnlyHint", None) is not None:
        return not bool(ann.readOnlyHint)
    name = (getattr(meta, "name", "") or "").lower()
    return any(v in name for v in _MUTATION_VERBS)


def connect(name: str, command: str, args: list[str], env: dict | None = None,
            cwd: str | None = None):
    """Start a server and return (client, [MCPTool, ...])."""
    client = MCPClient(name, command, args, env, cwd)
    client.start()
    return client, [MCPTool(client, m) for m in client.tools]
