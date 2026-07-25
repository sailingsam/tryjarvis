"""Brain — where understanding lives. The moat.

Jarvis behaves like a chief of staff, not a chatbot. Each turn runs TWO passes,
deliberately separated:

  1. Reply pass  — a natural, conversational answer. No JSON, no control fields.
                   (Mixing "be conversational" with "emit control JSON" was
                   unreliable: the model would say "done!" in prose while
                   leaving the structured field empty, so nothing persisted.)
  2. Extract pass — a separate, cheap-model call whose only job is to decide
                   what to remember, what new loops to open, and which open
                   loops are now closed. A focused task it does reliably.

The model is rented; deciding *what to keep, track, and follow up on* is ours.
Extraction returns plain JSON, so any LLMProvider works — no vendor tool schemas.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from ..core.memory import MemoryStore
from ..providers.llm import LLMProvider

_REPLY_SYSTEM = """You are Jarvis — the user's personal chief of staff. Not a chatbot: a trusted assistant who knows this one person, remembers what matters, tracks their open loops, and helps get things done.

Today is {today}.

WHAT YOU KNOW ABOUT THE USER:
{facts}

OPEN COMMITMENTS (things that still need to happen):
{commitments}

HOW YOU ACT:
- Warm, concise, direct — like a sharp EA who respects the user's time.
- Use what you know. Never make the user repeat themselves.
- If a relevant commitment is still open, a brief nudge is welcome.
- If asked to draft a message, email, or note, just write it — ready to send.
- You know today's date; resolve "today"/"tomorrow"/"this weekend" against it.
- You can use tools when they help — e.g. search the web for current or
  factual things you're unsure of. Prefer acting over guessing.

Just talk to the user naturally. Do not output JSON or any control text —
remembering things happens elsewhere, not in your reply."""

_EXTRACT_SYSTEM = """You maintain Jarvis's memory. Read the conversation and decide what changed. Be precise and conservative.

Today is {today}.

ALREADY KNOWN FACTS (do NOT repeat these):
{facts}

CURRENTLY OPEN COMMITMENTS (id — text):
{commitments}

Return ONLY this JSON object, nothing else:
{{"remember": [], "new_commitments": [], "completed": []}}

- remember: NEW durable facts about the user not already known — a preference,
  a person, a goal, an ongoing project. Short third-person facts, e.g.
  "User is vegetarian", "Mridul and Atharv are the user's friends". Resolve
  relative dates to absolute ones, e.g. "User met Mridul on 2026-07-22" (NOT
  "today"). Skip one-off chit-chat, questions, and anything already known.
- new_commitments: NEW open loops the user still needs to do, e.g.
  "Send Tanay the deck". Skip anything already listed as open or already done.
- completed: ids (from the OPEN list above) the user now indicates are done.
  Resolve references like "both" or "that one" to the actual ids."""

_BRIEF_SYSTEM = """You are Jarvis, the user's chief of staff, giving a short spoken daily brief. Be warm and concise — a few sentences, not a list dump. Lead with what matters, especially open commitments that need attention. If nothing's pressing, say so briefly.

Today is {today}.

WHAT YOU KNOW ABOUT THE USER:
{facts}

OPEN COMMITMENTS:
{commitments}

Give the brief now as plain text (no JSON)."""


def _today() -> str:
    return datetime.now().strftime("%A, %Y-%m-%d")


# Affirmatives accepted at a confirmation prompt (text + common Hinglish).
_YES = {"yes", "y", "yeah", "yep", "ok", "okay", "sure", "confirm", "do it", "go ahead",
        "haan", "ha", "haa", "kar", "kar do", "krdo", "theek", "thik", "ok kar"}


class Brain:
    def __init__(
        self,
        llm: LLMProvider,
        memory: MemoryStore,
        extractor: LLMProvider | None = None,
        tools=None,
    ):
        self._llm = llm
        self._extractor = extractor or llm      # falls back to the main model
        self._memory = memory
        self._tools = tools                      # a tools.Registry, or None
        self._history: list[dict] = []           # this session's conversation

    def _facts_block(self, query: str | None = None) -> str:
        # query-driven recall: at scale this returns the facts relevant to what
        # the user just said, not the whole store. Small scale → everything.
        mems = self._memory.recall(query=query)
        if not mems:
            return "(nothing yet — this is a fresh relationship)"
        return "\n".join(f"- {m.content} (learned {m.human_time()})" for m in mems)

    def _commitments_block(self) -> str:
        open_c = self._memory.open_commitments()
        if not open_c:
            return "(none open)"
        return "\n".join(f"- {c.id} — {c.content} (since {c.human_time()})" for c in open_c)

    def think(self, user_text: str, io=None) -> str:
        """Reply naturally (using tools when helpful), then update memory."""
        self._history.append({"role": "user", "content": user_text})
        reply_system = _REPLY_SYSTEM.format(
            today=_today(), facts=self._facts_block(query=user_text), commitments=self._commitments_block()
        )
        if self._tools and len(self._tools):
            reply = self._llm.run_tools(
                reply_system, self._history, self._tools.specs(), self._make_executor(io)
            ).strip()
        else:
            reply = self._llm.generate(reply_system, self._history).strip()
        self._history.append({"role": "assistant", "content": reply})

        self._update_memory()
        return reply

    def _make_executor(self, io):
        """Runs a tool the model asked for — gating outward/irreversible ones
        behind an IO confirmation first. Returns the tool's result as a string
        (a decline is a normal result, not an error, so the model handles it)."""
        def executor(name: str, tool_input: dict) -> str:
            tool = self._tools.get(name)
            if tool is None:
                return f"(no such tool: {name})"
            if os.environ.get("JARVIS_DEBUG"):
                print(f"  [tool] {name}({tool_input})", file=sys.stderr)
            if tool.needs_confirm and io is not None:
                io.speak(tool.confirmation(**tool_input))
                answer = (io.listen() or "").strip().lower()
                if answer not in _YES:
                    return "The user declined; the action was not performed."
            return tool.execute(**tool_input)
        return executor

    def _update_memory(self) -> None:
        """Second pass: a focused, cheap call that maintains the store. Runs
        against the open-commitments list (with ids) so references like 'both'
        resolve to real ids — the failure the single-pass design couldn't do."""
        extract_system = _EXTRACT_SYSTEM.format(
            today=_today(),
            facts=self._facts_block(query=_recent_user(self._history)),
            commitments=self._commitments_block(),
        )
        raw = self._extractor.generate(extract_system, self._history)
        updates = _parse_updates(raw)

        open_ids = {c.id for c in self._memory.open_commitments()}
        for fact in updates["remember"]:
            if not self._knows_fact(fact):
                self._memory.add(content=fact, source=_recent_user(self._history))
        for c in updates["new_commitments"]:
            if not self._has_open_commitment(c):
                self._memory.add_commitment(content=c, source=_recent_user(self._history))
        for cid in updates["completed"]:
            if cid in open_ids:
                self._memory.complete_commitment(cid)

    def _knows_fact(self, content: str) -> bool:
        c = content.strip().lower()
        return any(m.content.strip().lower() == c for m in self._memory.recall())

    def _has_open_commitment(self, content: str) -> bool:
        c = content.strip().lower()
        return any(x.content.strip().lower() == c for x in self._memory.open_commitments())

    def brief(self) -> str:
        """A proactive daily brief from memory + open commitments. One-shot."""
        system = _BRIEF_SYSTEM.format(
            today=_today(), facts=self._facts_block(), commitments=self._commitments_block()
        )
        return self._llm.generate(system, [{"role": "user", "content": "Give me my brief."}])


def _recent_user(history: list[dict]) -> str:
    for msg in reversed(history):
        if msg["role"] == "user":
            return msg["content"]
    return ""


def _parse_updates(raw: str) -> dict:
    """Pull the three update lists out of the extractor's JSON. On any malformed
    output, change nothing — never guess at a mutation."""
    empty = {"remember": [], "new_commitments": [], "completed": []}
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text
    # tolerate stray prose around the object
    if "{" in text and "}" in text:
        text = text[text.find("{") : text.rfind("}") + 1]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return empty

    def _strlist(key: str) -> list[str]:
        return [str(x).strip() for x in data.get(key, []) if str(x).strip()]

    return {
        "remember": _strlist("remember"),
        "new_commitments": _strlist("new_commitments"),
        "completed": _strlist("completed"),
    }
