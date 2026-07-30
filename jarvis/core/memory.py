"""Memory — the part of Jarvis that must NOT be rented.

Two kinds of durable knowledge, both stamped with where they came from:

  - Facts:       stable truths about the user ("User is vegetarian").
  - Commitments: open loops — things that need to happen ("Send Tanay the
                 deck"). These let Jarvis behave like a chief of staff.

Backed by SQLite (one file, stdlib — no external service). Facts are searchable
two ways so recall scales past "stuff everything in the prompt":
  - keyword, via SQLite FTS5 (BM25)
  - meaning, via embeddings + cosine
fused with Reciprocal Rank Fusion. Below `k` facts, recall just returns
everything (identical to before) — retrieval only kicks in once there's volume.
A Postgres/pgvector backend for the cloud, multi-device brain would implement
these same methods; the brain never sees SQL.
"""

from __future__ import annotations

import sqlite3
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..providers.embeddings import EmbeddingProvider


def _new_id() -> str:
    return uuid.uuid4().hex[:6]


def _human(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


@dataclass
class Memory:
    content: str
    source: str
    created_at: float
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)


@dataclass
class Commitment:
    content: str
    source: str
    created_at: float
    status: str = "open"
    resolved_at: float | None = None
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id         TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,
    created_at REAL NOT NULL,
    embedding  BLOB
);
CREATE TABLE IF NOT EXISTS commitments (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    resolved_at REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, content);
"""

_RRF_K = 60          # reciprocal-rank-fusion constant (standard default)
_CANDIDATES = 25     # how many to pull from each ranker before fusing


class MemoryStore:
    """Owns the raw knowledge and how it's searched. The one thing we never
    outsource. `embedder` is optional — without it, recall falls back to
    keyword-only (still works, just no semantic matching)."""

    def __init__(self, path: Path, embedder: EmbeddingProvider | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        # The daemon reaches memory from more than one thread — a voice turn and
        # a socket turn arrive on different ones — but never at the same time:
        # every turn is funnelled through one worker (see daemon._Turns). So the
        # same-thread check is relaxed while the serialisation it protects is
        # still guaranteed, one level up.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # --- facts ---------------------------------------------------------
    def add(self, content: str, source: str) -> Memory:
        mem = Memory(content=content.strip(), source=source.strip(), created_at=time.time())
        emb = _pack(self._embedder.embed([mem.content])[0]) if self._embedder else None
        self._conn.execute(
            "INSERT INTO facts (id, content, source, created_at, embedding) VALUES (?, ?, ?, ?, ?)",
            (mem.id, mem.content, mem.source, mem.created_at, emb),
        )
        self._conn.execute("INSERT INTO facts_fts (id, content) VALUES (?, ?)", (mem.id, mem.content))
        self._conn.commit()
        return mem

    def recall(self, query: str | None = None, k: int = 12) -> list[Memory]:
        """No query (or few facts) → everything, ordered oldest-first. With a
        query and enough volume → the top-k most relevant, keyword + meaning
        fused. Retrieval lives here so the brain calls one method either way."""
        rows = self._conn.execute(
            "SELECT id, content, source, created_at, embedding FROM facts ORDER BY created_at"
        ).fetchall()
        facts = {
            r["id"]: Memory(id=r["id"], content=r["content"], source=r["source"], created_at=r["created_at"])
            for r in rows
        }
        if not query or len(rows) <= k:
            return list(facts.values())

        ranked = self._fused_ranking(query, rows)
        top = ranked[:k]
        # keep chronological order among the winners — reads more naturally
        return sorted((facts[i] for i in top), key=lambda m: m.created_at)

    def _fused_ranking(self, query: str, rows: list[sqlite3.Row]) -> list[str]:
        fts = self._keyword_ids(query)
        vec = self._semantic_ids(query, rows)
        scores: dict[str, float] = {}
        for ranking in (fts, vec):
            for rank, fid in enumerate(ranking):
                scores[fid] = scores.get(fid, 0.0) + 1.0 / (_RRF_K + rank)
        return sorted(scores, key=lambda i: scores[i], reverse=True)

    def _keyword_ids(self, query: str) -> list[str]:
        # FTS5 MATCH; OR-join the terms so partial overlaps still rank.
        terms = " OR ".join(t for t in _tokens(query)) or query
        try:
            rows = self._conn.execute(
                "SELECT id FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
                (terms, _CANDIDATES),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [r["id"] for r in rows]

    def _semantic_ids(self, query: str, rows: list[sqlite3.Row]) -> list[str]:
        if not self._embedder:
            return []
        qv = self._embedder.embed([query])[0]
        sims: list[tuple[str, float]] = []
        for r in rows:
            if r["embedding"] is None:
                continue
            sims.append((r["id"], _cosine(qv, _unpack(r["embedding"]))))
        sims.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in sims[:_CANDIDATES]]

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
            "UPDATE commitments SET status = 'done', resolved_at = ? WHERE id = ? AND status = 'open'",
            (time.time(), cid),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]


def _tokens(text: str) -> list[str]:
    return ["".join(ch for ch in w if ch.isalnum()) for w in text.lower().split() if len(w) > 2]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
