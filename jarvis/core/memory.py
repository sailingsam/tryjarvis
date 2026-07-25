"""Memory — the part of Jarvis that must NOT be rented.

Two kinds of durable knowledge, both stamped with where they came from:

  - Facts:       stable truths about the user ("User is vegetarian").
  - Commitments: open loops — things that need to happen ("Send Tanay the
                 deck"). These let Jarvis behave like a chief of staff instead
                 of a chatbot: it holds the loop and follows up.

Backed by SQLite (one file, no external service — the stdlib ships it). This
is the same "own our data, one local file" property JSON had, but queryable
and indexed — so when volume grows we add FTS / vector search here without
changing the interface. `recall()` returns everything for now; smart retrieval
lives behind this same method later. The brain never sees SQL.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


def _new_id() -> str:
    return uuid.uuid4().hex[:6]


def _human(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


@dataclass
class Memory:
    content: str                       # the fact itself, in plain language
    source: str                        # why we believe it (the utterance that taught us)
    created_at: float                  # when we learned it
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)


@dataclass
class Commitment:
    content: str                       # "Send Tanay the deck"
    source: str                        # the utterance it came from
    created_at: float
    status: str = "open"               # open | done
    resolved_at: float | None = None
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id         TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS commitments (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    resolved_at REAL
);
"""


class MemoryStore:
    """Owns the raw knowledge. This interface is the one thing we never
    outsource; a Postgres/pgvector backend (for the cloud, multi-device brain)
    would implement these same methods."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # --- facts ---------------------------------------------------------
    def add(self, content: str, source: str) -> Memory:
        mem = Memory(content=content.strip(), source=source.strip(), created_at=time.time())
        self._conn.execute(
            "INSERT INTO facts (id, content, source, created_at) VALUES (?, ?, ?, ?)",
            (mem.id, mem.content, mem.source, mem.created_at),
        )
        self._conn.commit()
        return mem

    def recall(self) -> list[Memory]:
        """v1: return everything. Retrieval gets smarter (FTS/vector) behind
        this same method once volume demands it."""
        rows = self._conn.execute(
            "SELECT id, content, source, created_at FROM facts ORDER BY created_at"
        ).fetchall()
        return [Memory(id=r["id"], content=r["content"], source=r["source"], created_at=r["created_at"]) for r in rows]

    # --- commitments ---------------------------------------------------
    def add_commitment(self, content: str, source: str) -> Commitment:
        c = Commitment(content=content.strip(), source=source.strip(), created_at=time.time())
        self._conn.execute(
            "INSERT INTO commitments (id, content, source, created_at, status, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (c.id, c.content, c.source, c.created_at, c.status, c.resolved_at),
        )
        self._conn.commit()
        return c

    def open_commitments(self) -> list[Commitment]:
        return self._commitments("WHERE status = 'open'")

    def all_commitments(self) -> list[Commitment]:
        return self._commitments("")

    def _commitments(self, where: str) -> list[Commitment]:
        rows = self._conn.execute(
            f"SELECT id, content, source, created_at, status, resolved_at "
            f"FROM commitments {where} ORDER BY created_at"
        ).fetchall()
        return [
            Commitment(
                id=r["id"], content=r["content"], source=r["source"],
                created_at=r["created_at"], status=r["status"], resolved_at=r["resolved_at"],
            )
            for r in rows
        ]

    def complete_commitment(self, cid: str) -> bool:
        cur = self._conn.execute(
            "UPDATE commitments SET status = 'done', resolved_at = ? "
            "WHERE id = ? AND status = 'open'",
            (time.time(), cid),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
