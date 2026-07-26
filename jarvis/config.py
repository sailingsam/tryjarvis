"""Central configuration. Kept tiny on purpose — v1 has few knobs."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Where Jarvis keeps its memory — a SQLite database. In the project dir so it
# is easy to inspect during v1 (transparency: `sqlite3 data/jarvis.db` and you
# can see everything it knows). Upgrades to FTS/vector, then Postgres for the
# multi-device cloud brain, live behind the MemoryStore interface.
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_FILE = DATA_DIR / "jarvis.db"

# Unix socket for the persistent daemon. When it's up, the CLI is a thin client
# that talks to it (so WhatsApp etc. stay connected and capture messages).
SOCKET_FILE = DATA_DIR / "jarvis.sock"

# Reasoning model — used for the conversational reply.
LLM_MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5")

# Extraction model — a separate, cheaper pass that decides what to remember /
# complete. Cheap-by-design (philosophy #12): extraction is a focused task, so
# a small model does it well. Kept separate so the conversation is never asked
# to also emit control JSON (that mix was unreliable and leaked).
EXTRACT_MODEL = os.environ.get("JARVIS_EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# MCP servers to connect on startup — optional. Each entry:
#   {"name": "gcal", "command": "npx", "args": ["-y", "..."], "env": {...}}
# Their tools appear in the same tool-use loop as built-in tools.
MCP_CONFIG_FILE = DATA_DIR / "mcp.json"


def load_mcp_servers() -> list[dict]:
    if not MCP_CONFIG_FILE.exists():
        return []
    data = json.loads(MCP_CONFIG_FILE.read_text() or "{}")
    servers = data.get("servers", [])
    # Expand ${VAR} in env values so secrets (tokens) can live in the
    # environment instead of on disk in mcp.json.
    for server in servers:
        env = server.get("env")
        if isinstance(env, dict):
            server["env"] = {k: os.path.expandvars(str(v)) for k, v in env.items()}
    return servers
