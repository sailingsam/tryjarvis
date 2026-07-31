"""Central configuration. Kept tiny on purpose.

Settings live in two places, and which is which matters once this is something
people install rather than clone:

* `~/.config/mantrin/config.json` — provider choices and API keys, written by
  `mantrin setup`. Under XDG rather than the project directory, because a
  `pip install`ed Mantrin has no project directory. Mode 0600; it holds secrets.
* the environment — always wins over the file, so a shell export or a CI secret
  can override a saved key without editing anything.

A project-root `.env` is still read when present, for working in a clone.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("MANTRIN_CONFIG_DIR")
    or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "mantrin"
)
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_dotenv() -> None:
    """A project-root .env (gitignored), for running from a clone."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_settings() -> dict:
    """Saved settings, or an empty dict on a machine that has never run setup."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def save_settings(settings: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2) + "\n")
    CONFIG_FILE.chmod(0o600)          # it holds API keys
    return CONFIG_FILE


def _load_saved_keys() -> None:
    """Put saved keys into the environment — without overriding a real one, so
    the shell always beats the file."""
    for key, value in (load_settings().get("keys") or {}).items():
        if value:
            os.environ.setdefault(key, str(value))


_load_dotenv()
_load_saved_keys()

SETTINGS = load_settings()

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

# Voice — which ears and which voice. Resolution order is environment, then the
# saved setting, then the free local default, so Mantrin can always speak even
# on a machine that has never been configured.
STT_PROVIDER = os.environ.get("MANTRIN_STT") or SETTINGS.get("stt") or "whisper-local"
TTS_PROVIDER = os.environ.get("MANTRIN_TTS") or SETTINGS.get("tts") or "piper-local"

# Wake word. Always-on means the microphone is live all day, and without a gate
# every word spoken near the laptop would be shipped to a transcription service.
# The gate runs locally, so only speech that follows the wake word leaves the
# machine. Empty string disables it (fine while testing, wrong for always-on).
WAKE_WORD = os.environ.get("MANTRIN_WAKE_WORD", SETTINGS.get("wake_word", "hey_jarvis"))

# Voice model options, e.g. {"voice": "en_GB-alba-medium"} or {"model": "small"}.
STT_OPTIONS: dict = SETTINGS.get("stt_options") or {}
TTS_OPTIONS: dict = SETTINGS.get("tts_options") or {}


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


# Whether the daemon holds the microphone. On by default — being there without
# being started is the product. Turned off for a headless box, or while working
# on the brain and text is quicker.
VOICE_ENABLED = _flag("MANTRIN_VOICE", SETTINGS.get("voice", True))

# Per-stage timings after each spoken turn. A slow reply has four possible causes
# and they are indistinguishable from the outside; this says which one it was.
SHOW_TIMINGS = _flag("MANTRIN_TIMINGS", SETTINGS.get("timings", False))


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
    servers = []
    for server in data.get("servers", []):
        env = server.get("env")
        if isinstance(env, dict):
            # Expand ${VAR} in env values so secrets (tokens) can live in the
            # environment instead of on disk in mcp.json.
            env = {k: os.path.expandvars(str(v)) for k, v in env.items()}
            # A ${VAR} that survived expansion means the secret isn't set yet.
            # Skip the server rather than start it with a literal "${TOKEN}" —
            # so every integration can sit in mcp.json ahead of its keys and
            # simply light up the day they appear in the environment.
            missing = sorted({m for v in env.values() for m in re.findall(r"\$\{(\w+)\}", v)})
            if missing:
                print(f"(MCP '{server.get('name', '?')}' off — set {', '.join(missing)} to enable)", flush=True)
                continue
            server["env"] = env
        servers.append(server)
    return servers
