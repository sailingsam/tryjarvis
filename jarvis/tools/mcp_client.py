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
from concurrent.futures import TimeoutError as FuturesTimeout

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
    """A persistent connection to one MCP server, usable from sync code.

    Two kinds of server, one client. A *local* server is a process we spawn
    and speak to over stdio — it lives on this machine, sees this machine's
    files, and costs this machine's RAM. A *remote* server is a URL — the
    company runs it, maintains it, updates it; we bring HTTPS and (usually)
    an OAuth token. Which kind is entirely the block's business: `command`
    makes it local, `url` makes it remote, and nothing downstream can tell
    the difference.
    """

    def __init__(self, name: str, command: str | None = None, args: list[str] | None = None,
                 env: dict | None = None, cwd: str | None = None,
                 errlog_path: str | None = None, *, url: str | None = None,
                 headers: dict | None = None, auth=None):
        self.name = name
        self._command = command
        self._args = args or []
        self._env = env
        self._cwd = cwd
        self._errlog_path = errlog_path
        self._url = url
        self._headers = headers
        self._auth = auth               # httpx auth (an OAuth provider), or None
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
        finally:
            # Drain whatever the transport left mid-flight, or the loop's
            # destructor complains about it at some later garbage collection.
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()

    async def _serve(self) -> None:
        if self._url:
            await self._serve_remote()
        else:
            await self._serve_local()

    async def _serve_local(self) -> None:
        import sys

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command, args=self._args, env=self._env, cwd=self._cwd
        )
        # A server's stderr can be *chatty* — Baileys' signal library narrates
        # every session re-key. Interleaved with the daemon's own console it
        # drowns the conversation, so it goes to a per-server file instead,
        # where it is still there the day something actually breaks.
        errlog = open(self._errlog_path, "a") if self._errlog_path else sys.stderr
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                await self._session_loop(read, write)
        finally:
            if errlog is not sys.stderr:
                errlog.close()

    async def _serve_remote(self) -> None:
        import httpx2
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        # The SDK's own client factory, not plain httpx: the SDK runs on a
        # bundled fork (httpx2), and its OAuth provider is an httpx2.Auth —
        # a stock httpx.AsyncClient rejects it outright. Generous read
        # timeout because a streamable-HTTP server holds the response open
        # on purpose. The auth object (when present) transparently attaches
        # tokens and refreshes them through its own storage.
        client = create_mcp_http_client(
            headers=self._headers or None, auth=self._auth,
            timeout=httpx2.Timeout(30.0, read=300.0),
        )
        async with client:
            async with streamable_http_client(self._url, http_client=client) as (read, write):
                await self._session_loop(read, write)

    async def _session_loop(self, read, write) -> None:
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()
            self.tools = (await session.list_tools()).tools
            self._session = session
            self._ready.set()
            await self._stop.wait()       # keep the session open until close()

    def call(self, remote_name: str, arguments: dict, timeout: float = 45.0) -> str:
        """45s, not forever: a tool that hangs (a server silently waiting for
        an OAuth browser that can never open inside a daemon) must not freeze
        the whole brain — a spoken conversation died at exactly this spot
        once, tray stuck on blue. Better a clear failure the model can relay
        than a perfect answer that never comes."""
        fut = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(remote_name, arguments), self._loop
        )
        try:
            return _result_text(fut.result(timeout=timeout))
        except FuturesTimeout:
            fut.cancel()
            return (f"(tool error) {self.name}'s {remote_name} didn't answer within "
                    f"{int(timeout)} seconds. The server may need one-time setup — "
                    f"suggest running `mantrin connect {self.name}` in a terminal.")

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
        # The SDK renamed the field: modern versions expose `input_schema`,
        # older ones `inputSchema`. Falling through to an empty schema here
        # once left EVERY MCP tool parameter invisible to the model — it
        # guessed argument names from prose, loose servers swallowed the
        # wrong ones silently, and the wrong song played with full success.
        self.input_schema = (getattr(meta, "input_schema", None)
                             or getattr(meta, "inputSchema", None)
                             or {"type": "object", "properties": {}})
        self.needs_confirm = _infer_confirm(meta)

    def execute(self, **kwargs) -> str:
        # Check the argument names against the schema BEFORE calling. Loose
        # servers ignore unknown keys instead of erroring — a playback tool
        # sent `uri` instead of `spotify_uri` silently resumed whatever was
        # already playing and reported success, so the model cheerfully told
        # the user the wrong song was the right one. A corrective error here
        # is something the model fixes on its next attempt; a silent ignore
        # it can never see.
        known = set((self.input_schema.get("properties") or {}).keys())
        unknown = set(kwargs) - known
        if known and unknown:
            return (f"(tool error) unknown argument(s): {', '.join(sorted(unknown))}. "
                    f"This tool only accepts: {', '.join(sorted(known))}. "
                    f"Retry with the correct names.")
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
        # This line gets read ALOUD in voice mode. A repr of the arguments —
        # braces, quotes, underscores — turns into "curly brace quote recipient
        # quote", which tells the user nothing and takes ten seconds to say.
        action = self._remote_name.replace("_", " ").replace("-", " ")
        if not kwargs:
            return f"Should I {action}? Yes or no?"
        details = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in kwargs.items())
        return f"Should I {action}? {details}. Yes or no?"


# Outward or consequential actions must be explicitly approved. A tool name is
# only a fallback — good MCP servers also declare their intent in annotations —
# but it keeps the human-in-control promise intact for the many servers that
# publish no annotations at all.
_CRITICAL_ACTION_TERMS = (
    "send", "email", "message", "post", "reply",
    "pay", "transfer", "purchase", "order",
    "delete", "remove", "cancel", "book", "schedule",
    "invite", "share", "grant", "revoke", "password",
    "create", "update", "write", "add", "set", "mark", "edit",
    "archive", "mute", "block", "leave",
)

# Everyday controls are reversible and expected to be immediate: asking before
# pausing music or turning off a light makes the assistant feel less useful,
# not more safe. Keep this deliberately narrow; new integrations should use
# MCP annotations instead of casually expanding it.
_HARMLESS_ACTION_TERMS = (
    "play", "pause", "skip", "volume",
    "turn_on", "turn_off", "toggle", "dim",
    "search", "read", "list", "get", "status",
)


def _infer_confirm(meta) -> bool:
    """Whether an external action needs the user's approval.

    Read-only MCP metadata always runs freely. Critical names still override a
    server that incorrectly labels an outward action non-destructive; harmless
    local controls remain immediate. Everything unknown is confirmed — a new
    third-party tool must earn the right to act silently, not the reverse.
    """
    ann = getattr(meta, "annotations", None)
    raw_name = getattr(meta, "name", "") or ""
    # Match action *words*, not arbitrary substrings: ``forget_note`` must not
    # become harmless merely because it happens to contain ``get``.
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw_name).lower()
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")

    def has_term(term: str) -> bool:
        return f"_{term}_" in f"_{name}_"

    read_only = getattr(ann, "readOnlyHint", None) if ann is not None else None
    destructive = getattr(ann, "destructiveHint", None) if ann is not None else None

    if read_only is True:
        return False
    if any(has_term(term) for term in _CRITICAL_ACTION_TERMS):
        return True
    if destructive is True:
        return True
    if any(has_term(term) for term in _HARMLESS_ACTION_TERMS):
        return False
    return True


def connect(name: str, command: str | None = None, args: list[str] | None = None,
            env: dict | None = None, cwd: str | None = None,
            errlog_path: str | None = None, *, url: str | None = None,
            headers: dict | None = None, auth=None):
    """Start (or reach) a server and return (client, [MCPTool, ...])."""
    client = MCPClient(name, command, args, env, cwd, errlog_path,
                       url=url, headers=headers, auth=auth)
    client.start()
    return client, [MCPTool(client, m) for m in client.tools]
