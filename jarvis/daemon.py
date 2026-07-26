"""The persistent Jarvis daemon.

Why it exists: WhatsApp (Baileys) needs a stable, long-lived connection to stay
reliable and to capture incoming messages while you're not in a session. A CLI
that spawns and kills everything per run can't do that. The daemon holds the
brain + MCP connections alive; the CLI becomes a thin client that talks to it
over a Unix socket.

Protocol (newline-delimited JSON, one client at a time):
  client → {"type":"say","text": ...}
  daemon → {"type":"confirm_prompt","text": ...}   (mid-tool; client answers)
  client → {"type":"input","text": ...}            (the confirmation answer)
  daemon → {"type":"reply","text": ...}            (turn complete)
"""

from __future__ import annotations

import json
import os
import socket
import sys

from . import config
from .core.brain import Brain
from .core.memory import MemoryStore
from .io.remote_io import RemoteIO
from .providers.embeddings import LocalEmbedder
from .providers.llm import ClaudeLLM
from .tools.base import Registry
from .tools.web_search import WebSearch


def _x_tools() -> list:
    """X (Twitter) tools, only if creds are configured in the environment."""
    if not config.x_configured():
        return []
    from .tools.x_tools import x_tools

    return x_tools(config.X_API_KEY, config.X_API_SECRET, config.X_ACCESS_TOKEN, config.X_ACCESS_SECRET)


def _connect_mcp(tools: list) -> list:
    clients = []
    for server in config.load_mcp_servers():
        try:
            from .tools.mcp_client import connect

            client, mcp_tools = connect(
                server["name"], server["command"], server.get("args", []),
                server.get("env"), server.get("cwd"),
            )
            clients.append(client)
            tools.extend(mcp_tools)
            print(f"(MCP '{server['name']}': {len(mcp_tools)} tools)", flush=True)
        except Exception as e:
            print(f"(MCP '{server.get('name', '?')}' failed to start: {e})", flush=True)
    return clients


def run() -> int:
    if is_running():
        print("Jarvis daemon is already running.")
        return 0
    sock_path = config.SOCKET_FILE
    if sock_path.exists():
        sock_path.unlink()          # clear a stale socket from a previous run
    sock_path.parent.mkdir(parents=True, exist_ok=True)

    print("Jarvis daemon starting — loading brain + connections…", flush=True)
    memory = MemoryStore(config.DB_FILE, embedder=LocalEmbedder())
    tools = [WebSearch(), *_x_tools()]
    mcp_clients = _connect_mcp(tools)   # WhatsApp etc. now stay connected here
    brain = Brain(
        llm=ClaudeLLM(model=config.LLM_MODEL),
        memory=memory,
        extractor=ClaudeLLM(model=config.EXTRACT_MODEL),
        tools=Registry(tools),
    )

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    print(f"Jarvis daemon ready. Listening on {sock_path}. (Ctrl+C to stop)", flush=True)

    try:
        while True:
            conn, _ = server.accept()
            _serve_client(conn, brain)
    except KeyboardInterrupt:
        print("\nShutting down…", flush=True)
    finally:
        server.close()
        if sock_path.exists():
            sock_path.unlink()
        for client in mcp_clients:
            client.close()
    return 0


def _serve_client(conn: socket.socket, brain: Brain) -> None:
    """Handle one client connection until it disconnects."""
    f = conn.makefile("rw")
    io = RemoteIO(f)
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "say":
                continue
            reply = brain.think(msg.get("text", ""), io=io)
            f.write(json.dumps({"type": "reply", "text": reply}) + "\n")
            f.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            f.close()
            conn.close()
        except OSError:
            pass


def is_running() -> bool:
    """True if a daemon is accepting connections on the socket."""
    if not config.SOCKET_FILE.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(config.SOCKET_FILE))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(run())
