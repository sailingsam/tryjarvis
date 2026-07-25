"""Central configuration. Kept tiny on purpose — v1 has few knobs."""

from __future__ import annotations

import os
from pathlib import Path

# Where Jarvis keeps its memory — a SQLite database. In the project dir so it
# is easy to inspect during v1 (transparency: `sqlite3 data/jarvis.db` and you
# can see everything it knows). Upgrades to FTS/vector, then Postgres for the
# multi-device cloud brain, live behind the MemoryStore interface.
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_FILE = DATA_DIR / "jarvis.db"

# Reasoning model — used for the conversational reply.
LLM_MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5")

# Extraction model — a separate, cheaper pass that decides what to remember /
# complete. Cheap-by-design (philosophy #12): extraction is a focused task, so
# a small model does it well. Kept separate so the conversation is never asked
# to also emit control JSON (that mix was unreliable and leaked).
EXTRACT_MODEL = os.environ.get("JARVIS_EXTRACT_MODEL", "claude-haiku-4-5-20251001")
