"""Memory — the part of Jarvis that must NOT be rented.

Four kinds of durable knowledge, each stamped with where it came from:

  - Facts:       stable truths about the user ("User is vegetarian").
  - Directives:  standing instructions the user gave the assistant itself
                 ("keep replies short", "call me boss"). Injected on every
                 turn — how you were told to behave is never query-dependent.
  - Commitments: open loops — things that need to happen ("Send Tanay the
                 deck"). These let Jarvis behave like a chief of staff.
  - Exchanges:   the conversation itself, archived once it leaves the brain's
                 working window. Recalled by meaning when the user refers back
                 to it — instead of every turn dragging the full transcript.

Facts and directives don't just accumulate — they can be *superseded*. When
new conversation contradicts or replaces an entry ("actually I eat fish now",
"stop calling me boss"), the old row is retired: out of recall, kept on disk
with its provenance. An append-only store slowly fills with stale truths and
the assistant starts contradicting the person it exists to know.

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
import threading
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
    kind: str = "fact"                  # "fact" | "directive"
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
    # When Jarvis promised to speak up about this, if a time was given at all.
    # `notified` records that the promise was kept — spoken once, not nagged.
    due: float | None = None
    notified: float | None = None
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)

    def human_due(self) -> str:
        return _human(self.due) if self.due else ""


@dataclass
class Exchange:
    """One archived conversational exchange — what the user said and what
    Jarvis answered. The working history only keeps a recent window; everything
    older lands here, searchable, so 'that restaurant you mentioned last week'
    still has somewhere to be found."""
    user_text: str
    reply_text: str
    created_at: float
    id: str = field(default_factory=_new_id)

    def human_time(self) -> str:
        return _human(self.created_at)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL,
    source        TEXT NOT NULL,
    created_at    REAL NOT NULL,
    embedding     BLOB,
    kind          TEXT NOT NULL DEFAULT 'fact',
    status        TEXT NOT NULL DEFAULT 'active',
    superseded_at REAL
);
CREATE TABLE IF NOT EXISTS commitments (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    resolved_at REAL,
    due         REAL,
    notified    REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, content);
CREATE TABLE IF NOT EXISTS exchanges (
    id         TEXT PRIMARY KEY,
    user_text  TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    created_at REAL NOT NULL,
    embedding  BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS exchanges_fts USING fts5(id UNINDEXED, content);
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
        # Turns funnel through one worker (daemon._Turns), but memory updates
        # run on their own background thread so the user never waits on them —
        # a write from there can land while a turn is mid-recall. One lock
        # around every touch of the connection keeps SQLite honest.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Bring a database from before kind/status up to the current shape.
        ADD COLUMN backfills existing rows with the default — every old fact
        wakes up as an active fact, which is exactly what it was."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(facts)")}
        if "kind" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN kind TEXT NOT NULL DEFAULT 'fact'")
        if "status" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "superseded_at" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN superseded_at REAL")
        ccols = {r["name"] for r in self._conn.execute("PRAGMA table_info(commitments)")}
        if "due" not in ccols:
            self._conn.execute("ALTER TABLE commitments ADD COLUMN due REAL")
        if "notified" not in ccols:
            self._conn.execute("ALTER TABLE commitments ADD COLUMN notified REAL")

    # --- facts & directives ---------------------------------------------
    def add(self, content: str, source: str, kind: str = "fact") -> Memory:
        mem = Memory(content=content.strip(), source=source.strip(),
                     created_at=time.time(), kind=kind)
        emb = _pack(self._embedder.embed([mem.content])[0]) if self._embedder else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (id, content, source, created_at, embedding, kind) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mem.id, mem.content, mem.source, mem.created_at, emb, mem.kind),
            )
            self._conn.execute("INSERT INTO facts_fts (id, content) VALUES (?, ?)", (mem.id, mem.content))
            self._conn.commit()
        return mem

    def recall(self, query: str | None = None, k: int = 12) -> list[Memory]:
        """Active facts. No query (or few facts) → everything, oldest-first.
        With a query and enough volume → the top-k most relevant, keyword +
        meaning fused. Retrieval lives here so the brain calls one method
        either way. Directives never ride along — they have their own door."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, source, created_at, embedding FROM facts "
                "WHERE status = 'active' AND kind = 'fact' ORDER BY created_at"
            ).fetchall()
        facts = {
            r["id"]: Memory(id=r["id"], content=r["content"], source=r["source"], created_at=r["created_at"])
            for r in rows
        }
        if not query or len(rows) <= k:
            return list(facts.values())

        ranked = self._fused_ranking(query, rows, "facts_fts")
        # the FTS index still knows retired ids — keep only live winners
        top = [i for i in ranked if i in facts][:k]
        # keep chronological order among the winners — reads more naturally
        return sorted((facts[i] for i in top), key=lambda m: m.created_at)

    def directives(self) -> list[Memory]:
        """Every active standing instruction, oldest-first. All of them, every
        time — 'reply in Hindi' has to hold whether or not the current turn
        mentions Hindi, so directives are never query-filtered."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, source, created_at FROM facts "
                "WHERE status = 'active' AND kind = 'directive' ORDER BY created_at"
            ).fetchall()
        return [
            Memory(id=r["id"], content=r["content"], source=r["source"],
                   created_at=r["created_at"], kind="directive")
            for r in rows
        ]

    def retire(self, fact_id: str) -> bool:
        """Supersede a fact or directive: out of recall, kept on disk with its
        provenance. Memory that can only grow eventually contradicts the user
        it describes — this is the correction path."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET status = 'superseded', superseded_at = ? "
                "WHERE id = ? AND status = 'active'",
                (time.time(), fact_id),
            )
            if cur.rowcount:
                self._conn.execute("DELETE FROM facts_fts WHERE id = ?", (fact_id,))
            self._conn.commit()
        return cur.rowcount > 0

    # --- archived conversation -----------------------------------------
    def archive_turn(self, user_text: str, reply_text: str, created_at: float | None = None) -> Exchange:
        """File one exchange that just left the working window. Indexed the
        same two ways facts are, so it can be found by meaning later."""
        ex = Exchange(
            user_text=user_text.strip(), reply_text=reply_text.strip(),
            created_at=created_at if created_at is not None else time.time(),
        )
        searchable = f"{ex.user_text}\n{ex.reply_text}"
        emb = _pack(self._embedder.embed([searchable])[0]) if self._embedder else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO exchanges (id, user_text, reply_text, created_at, embedding) "
                "VALUES (?, ?, ?, ?, ?)",
                (ex.id, ex.user_text, ex.reply_text, ex.created_at, emb),
            )
            self._conn.execute(
                "INSERT INTO exchanges_fts (id, content) VALUES (?, ?)", (ex.id, searchable)
            )
            self._conn.commit()
        return ex

    def recall_turns(self, query: str, k: int = 3) -> list[Exchange]:
        """The archived exchanges most relevant to what the user just said —
        how 'that thing we discussed last week' comes back without the whole
        transcript riding along on every turn."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, user_text, reply_text, created_at, embedding FROM exchanges "
                "ORDER BY created_at"
            ).fetchall()
        if not rows:
            return []
        turns = {
            r["id"]: Exchange(id=r["id"], user_text=r["user_text"],
                              reply_text=r["reply_text"], created_at=r["created_at"])
            for r in rows
        }
        ranked = self._fused_ranking(query, rows, "exchanges_fts")
        return sorted((turns[i] for i in ranked[:k]), key=lambda e: e.created_at)

    def _fused_ranking(self, query: str, rows: list[sqlite3.Row], fts_table: str) -> list[str]:
        fts = self._keyword_ids(query, fts_table)
        vec = self._semantic_ids(query, rows)
        scores: dict[str, float] = {}
        for ranking in (fts, vec):
            for rank, fid in enumerate(ranking):
                scores[fid] = scores.get(fid, 0.0) + 1.0 / (_RRF_K + rank)
        return sorted(scores, key=lambda i: scores[i], reverse=True)

    def _keyword_ids(self, query: str, fts_table: str) -> list[str]:
        # FTS5 MATCH; OR-join the terms so partial overlaps still rank.
        terms = " OR ".join(t for t in _tokens(query)) or query
        try:
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT id FROM {fts_table} WHERE {fts_table} MATCH ? ORDER BY rank LIMIT ?",
                    (terms, _CANDIDATES),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [r["id"] for r in rows]

    def _semantic_ids(self, query: str, rows: list[sqlite3.Row]) -> list[str]:
        if not self._embedder:
            return []
        qv = self._embedder.embed([query])[0]
        ids = [r["id"] for r in rows if r["embedding"] is not None]
        vecs = [_unpack(r["embedding"]) for r in rows if r["embedding"] is not None]
        if not ids:
            return []
        try:
            # numpy rides in with the embedder; one matrix product beats a
            # Python loop by ~100x, which matters once an always-on daemon has
            # archived months of conversation.
            import numpy as np

            m = np.asarray(vecs, dtype=np.float32)
            q = np.asarray(qv, dtype=np.float32)
            sims = (m @ q) / ((np.linalg.norm(m, axis=1) * np.linalg.norm(q)) + 1e-9)
            order = np.argsort(-sims)[:_CANDIDATES]
            return [ids[i] for i in order]
        except ImportError:
            scored = sorted(
                ((i, _cosine(qv, v)) for i, v in zip(ids, vecs)),
                key=lambda x: x[1], reverse=True,
            )
            return [i for i, _ in scored[:_CANDIDATES]]

    # --- commitments ---------------------------------------------------
    def add_commitment(self, content: str, source: str, due: float | None = None) -> Commitment:
        c = Commitment(content=content.strip(), source=source.strip(),
                       created_at=time.time(), due=due)
        with self._lock:
            self._conn.execute(
                "INSERT INTO commitments (id, content, source, created_at, status, resolved_at, due) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c.id, c.content, c.source, c.created_at, c.status, c.resolved_at, c.due),
            )
            self._conn.commit()
        return c

    def open_commitments(self) -> list[Commitment]:
        return self._commitments("WHERE status = 'open'")

    def all_commitments(self) -> list[Commitment]:
        return self._commitments("")

    def due_commitments(self, now: float | None = None) -> list[Commitment]:
        """Open items whose promised time has arrived and that have not been
        spoken about yet — what the scheduler should announce right now.
        Unspoken they stay 'due' forever (a daemon restart doesn't lose them);
        once announced they are only nudged, never re-announced."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, source, created_at, status, resolved_at, due, notified "
                "FROM commitments WHERE status = 'open' AND notified IS NULL "
                "AND due IS NOT NULL AND due <= ? ORDER BY due",
                (now if now is not None else time.time(),),
            ).fetchall()
        return [self._row_to_commitment(r) for r in rows]

    def mark_notified(self, cid: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE commitments SET notified = ? WHERE id = ?", (time.time(), cid)
            )
            self._conn.commit()

    def _commitments(self, where: str) -> list[Commitment]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, content, source, created_at, status, resolved_at, due, notified "
                f"FROM commitments {where} ORDER BY created_at"
            ).fetchall()
        return [self._row_to_commitment(r) for r in rows]

    @staticmethod
    def _row_to_commitment(r: sqlite3.Row) -> Commitment:
        return Commitment(
            id=r["id"], content=r["content"], source=r["source"],
            created_at=r["created_at"], status=r["status"], resolved_at=r["resolved_at"],
            due=r["due"], notified=r["notified"],
        )

    def complete_commitment(self, cid: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE commitments SET status = 'done', resolved_at = ? WHERE id = ? AND status = 'open'",
                (time.time(), cid),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM facts WHERE status = 'active'"
            ).fetchone()[0]


def _tokens(text: str) -> list[str]:
    return ["".join(ch for ch in w if ch.isalnum()) for w in text.lower().split() if len(w) > 2]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
