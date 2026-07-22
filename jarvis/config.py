"""Central configuration. Kept tiny on purpose — v1 has few knobs."""

from __future__ import annotations

import os
from pathlib import Path

# Where Jarvis keeps its memory. In the project dir so it is easy to inspect
# during v1 (transparency: you can open the file and see everything it knows).
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
MEMORY_FILE = DATA_DIR / "memory.json"

# Reasoning model. Cheap-by-design (philosophy #12): default to a mid model,
# override with JARVIS_MODEL. Swap freely — the brain only talks to the
# LLMProvider interface, never to a specific vendor.
LLM_MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5")
