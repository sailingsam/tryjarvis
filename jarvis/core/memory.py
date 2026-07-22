"""Memory — the part of Jarvis that must NOT be rented.

A memory is a durable fact about the user, each stamped with where it came
from. v1 is deliberately simple: a flat JSON file, and recall just returns
everything (with a handful of facts, loading them all into the prompt beats
any vector database). The shape leaves room to grow — confidence, decay,
contradiction handling — without forcing it now.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Memory:
    content: str                       # the fact itself, in plain language
    source: str                        # why we believe it (the utterance that taught us)
    created_at: float                  # unix timestamp — when we learned it
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def human_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))


class MemoryStore:
    """Owns the raw facts. This interface is the one thing we never outsource;
    a different backend (mem0, a graph DB) would implement the same methods."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._memories: list[Memory] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "[]")
            self._memories = [Memory(**m) for m in raw]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(m) for m in self._memories], indent=2))

    def add(self, content: str, source: str) -> Memory:
        mem = Memory(content=content.strip(), source=source.strip(), created_at=time.time())
        self._memories.append(mem)
        self._save()
        return mem

    def recall(self) -> list[Memory]:
        """v1: return everything. Retrieval gets smarter once volume demands it."""
        return list(self._memories)

    def __len__(self) -> int:
        return len(self._memories)
