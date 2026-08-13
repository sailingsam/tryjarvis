"""Jarvis — a personal intelligence system.

v1 scope: prove the core bet — *memory compounds*. You tell Jarvis something,
it remembers, and a later (fresh) session already knows.

Design rules that survive past v1:
  - The brain (memory + reasoning) is the product/moat and lives here.
  - Everything replaceable (LLM, STT, TTS) sits behind a thin interface.
  - Every memory carries its source, so "why does Jarvis know this?" always
    has an answer (the Trust principle).
"""

__version__ = "0.2.0"
