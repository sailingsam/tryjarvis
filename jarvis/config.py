"""Central configuration. Kept tiny on purpose — v1 has few knobs."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Load a project-root .env (gitignored) into the environment so secrets (X
# tokens, etc.) persist without re-exporting and are picked up by the daemon too.
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

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


# X (Twitter) — OAuth 1.0a user-context creds for the user's own account.
# Set these in the environment to enable the X tools; unset = X disabled.
X_API_KEY = os.environ.get("X_API_KEY")
X_API_SECRET = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")


def x_configured() -> bool:
    return all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET])


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
