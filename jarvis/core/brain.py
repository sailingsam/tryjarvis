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

Two things keep a turn fast, both invisible to the user:

  * The extract pass runs on a background thread. The user hears the reply the
    moment it exists; deciding what to remember happens after, off the clock.
  * The conversation the model sees is a WINDOW — the last few exchanges
    verbatim. Older turns are archived into memory and come back by meaning
    (the same search facts use) only when what the user just said looks
    related. Without this, week three of an always-on daemon would ship its
    entire life story with every "what's the time".

The system prompt is split static/dynamic so the unchanging part (persona,
rules — and the tool schemas that ride in front of it) is cached by the
provider instead of re-read at full price every turn.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

from ..core.memory import MemoryStore
from ..providers.llm import LLMProvider

# Messages kept verbatim (6 exchanges). Enough that pronouns, running jokes and
# "as I said" still resolve; small enough that turn cost stays flat forever.
_WINDOW = 12

_REPLY_STATIC = """You are Jarvis — the user's personal chief of staff. Not a chatbot: a trusted assistant who knows this one person, remembers what matters, tracks their open loops, and helps get things done.

HOW YOU ACT:
- Warm, concise, direct — like a sharp EA who respects the user's time.
- Use what you know. Never make the user repeat themselves.
- If a relevant commitment is still open, a brief nudge is welcome.
- If asked to draft a message, email, or note, just write it — ready to send.
- You know today's date; resolve "today"/"tomorrow"/"this weekend" against it.
- You can use tools when they help — e.g. search the web for current or
  factual things you're unsure of. Prefer acting over guessing.
- When you retry a tool call, reuse the exact argument values from the earlier
  call (ids, recipients, numbers). Never substitute a placeholder or invented
  value — if you no longer know the real value, look it up again first.
- Sanity-check outward content BEFORE acting, never after. If a message about
  to go out contains something the user probably didn't intend — the wrong
  name, someone else's greeting, a stale date — raise it first and offer the
  fix. Noticing a mistake only after sending is a failure; you saw the exact
  text before it went.
- If a just-sent message needs fixing, prefer editing it (edit_message) over
  sending a correction — that's what a person would do.
- Your words may be spoken aloud. Keep replies plain prose — no markdown
  formatting, no bullet lists, no headings. Short sentences beat long ones.

Just talk to the user naturally. Do not output JSON or any control text —
remembering things happens elsewhere, not in your reply.

What you know about the user, their open commitments, today's date, and any
relevant older conversation follow below."""

_REPLY_CONTEXT = """Today is {today}.

WHAT YOU KNOW ABOUT THE USER:
{facts}

OPEN COMMITMENTS (things that still need to happen):
{commitments}"""

_REPLY_PAST = """

FROM OLDER CONVERSATIONS (recalled because they look relevant — the recent turns are already in the chat):
{past}"""

_EXTRACT_STATIC = """You maintain Jarvis's memory. Read the conversation and decide what changed. Be precise and conservative.

Return ONLY this JSON object, nothing else:
{"remember": [], "new_commitments": [], "completed": []}

- remember: NEW durable facts about the user not already known — a preference,
  a person, a goal, an ongoing project. Short third-person facts, e.g.
  "User is vegetarian", "Mridul and Atharv are the user's friends". Resolve
  relative dates to absolute ones, e.g. "User met Mridul on 2026-07-22" (NOT
  "today"). Skip one-off chit-chat, questions, and anything already known.
- new_commitments: NEW open loops the user still needs to do, e.g.
  "Send Tanay the deck". Skip anything already listed as open or already done.
- completed: ids (from the OPEN COMMITMENTS list below) the user now indicates
  are done. Resolve references like "both" or "that one" to the actual ids.

Today's date, the already-known facts and the open commitments follow below."""

_EXTRACT_CONTEXT = """Today is {today}.

ALREADY KNOWN FACTS (do NOT repeat these):
{facts}

CURRENTLY OPEN COMMITMENTS (id — text):
{commitments}"""

_BRIEF_SYSTEM = """You are Jarvis, the user's chief of staff, giving a short spoken daily brief. Be warm and concise — a few sentences, not a list dump. Lead with what matters, especially open commitments that need attention. If nothing's pressing, say so briefly.

Today is {today}.

WHAT YOU KNOW ABOUT THE USER:
{facts}

OPEN COMMITMENTS:
{commitments}

Give the brief now as plain text (no JSON)."""


def _today() -> str:
    return datetime.now().strftime("%A, %Y-%m-%d")


# Unambiguous confirmation answers (text + common Hinglish) — matched exactly,
# after punctuation. Anything else is real language and goes to the model:
# people rarely say a bare yes, and keyword rules mistake "no, I said yes" for
# a refusal. Rules first, AI when language actually needs understanding
# (philosophy #17) — a confirmation answer is precisely such a case.
_YES = {"yes", "y", "yeah", "yep", "ok", "okay", "sure", "confirm", "do it", "go ahead",
        "haan", "ha", "haa", "kar", "kar do", "krdo", "theek", "thik", "ok kar",
        "yes please", "haan bhej de", "bhej de", "send it"}
_NO = {"no", "n", "nope", "nah", "cancel", "stop", "nahi", "nhi", "mat", "ruko",
       "rehne de", "mat bhej", "don t", "dont"}

_CONSENT_SYSTEM = """A user was asked to confirm an action before their assistant performs it. Decide from their reply whether they are giving permission. Read intent, not keywords — any language or mix, however phrased.

The action may be irreversible, so only answer yes when the reply clearly
addresses the question AND clearly consents. If the reply does not engage with
the question at all — a lone name, a stray word, mis-transcribed speech — that
is unclear, never yes. When torn between yes and unclear, answer unclear: the
assistant just asks again, which costs nothing, while a wrong yes sends
something that cannot be unsent.

People think out loud, especially when speaking. A reply may wander through
no and yes before settling — judge where they END UP, not where they started.

Examples:
- "No, I said yes." -> yes (correcting a mishearing; they want it done)
- "Yes, but change the message first." -> no (not as proposed)
- "Obviously, go for it." -> yes
- "Hmm... theek hai, kar de." -> yes
- "No, wait... no, no. Yeah actually, I'm okay with this. Send it." -> yes
  (they thought out loud and landed on yes)
- "Wait." -> no
- "Saksham." (just a name) -> unclear
- anything unrelated or garbled -> unclear

Answer with exactly one word: yes, no, or unclear."""

_PRIOR_CONSENT_SYSTEM = """An assistant is about to perform an outward action and must not do it without the user's permission. You see the action and the conversation that led to it. Decide whether the user has ALREADY clearly approved this exact action, so asking again would just be annoying.

Answer yes only when BOTH hold:
- the assistant proposed this exact action in the conversation — the user could
  see precisely what would be sent or done, and to whom, before approving
- the user's reply clearly approves it as proposed

Anything less is no: the user asked for the action but was never shown the
exact content; they approved something different; their approval was vague.
When torn, answer no — asking once more costs a few seconds, while acting
without permission breaks trust.

Answer with exactly one word: yes or no."""


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
        self._history: list[dict] = []           # the working window, verbatim
        self._times: list[float] = []            # when each message happened —
        # kept beside the history (an extra key on the dicts would go to the
        # API), so an exchange archived days after it was said keeps its day.
        self._updates: queue.Queue = queue.Queue()
        self._memory_worker = threading.Thread(
            target=self._memory_loop, daemon=True, name="memory"
        )
        self._memory_worker.start()

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
        """Reply naturally (using tools when helpful); memory updates follow in
        the background — the user never waits on bookkeeping."""
        self._remember_turn("user", user_text)
        system = [_REPLY_STATIC, self._context_block(user_text)]
        if self._tools and len(self._tools):
            reply = self._llm.run_tools(
                system, self._history, self._tools.specs(), self._make_executor(io)
            ).strip()
        else:
            reply = self._llm.generate(system, self._history).strip()
        self._remember_turn("assistant", reply)

        self._updates.put(("extract", list(self._history)))
        self._trim_history()
        return reply

    def _remember_turn(self, role: str, content: str) -> None:
        self._history.append({"role": role, "content": content})
        self._times.append(time.time())

    def _context_block(self, query: str) -> str:
        block = _REPLY_CONTEXT.format(
            today=_today(), facts=self._facts_block(query=query),
            commitments=self._commitments_block(),
        )
        past = self._past_block(query)
        return block + (_REPLY_PAST.format(past=past) if past else "")

    def _past_block(self, query: str) -> str:
        turns = self._memory.recall_turns(query, k=3)
        return "\n".join(
            f'- [{t.human_time()}] user: "{_clip(t.user_text)}" — '
            f'you replied: "{_clip(t.reply_text)}"'
            for t in turns
        )

    def _trim_history(self) -> None:
        """Keep the working window; hand what falls off to the archive. The
        actual archiving (it embeds) happens on the memory worker — trimming
        must not add a millisecond to the turn that triggered it."""
        while len(self._history) > _WINDOW:
            (first, second), when = self._history[:2], self._times[0]
            del self._history[:2], self._times[:2]
            if first["role"] == "user" and second["role"] == "assistant":
                self._updates.put(("archive", first["content"], second["content"], when))

    def _memory_loop(self) -> None:
        """The background bookkeeper: extraction passes and archive writes, in
        the order the turns produced them. A failure here loses one update —
        it never touches the conversation."""
        while True:
            item = self._updates.get()
            if item is None:
                return
            try:
                if item[0] == "extract":
                    self._update_memory(item[1])
                else:
                    self._memory.archive_turn(item[1], item[2], created_at=item[3])
            except Exception as e:                          # noqa: BLE001
                print(f"(memory update failed: {e})", flush=True)

    def close(self) -> None:
        """Let queued memory work finish — what was said must not be forgotten
        just because shutdown came seconds after it."""
        self._updates.put(None)
        self._memory_worker.join(timeout=15)

    def _consent(self, question: str, answer: str) -> str:
        """Did the user say yes? — 'yes', 'no' or 'unclear'.

        An exact match on unambiguous words is free; everything else is
        language and goes to the cheap model, because people confirm in
        sentences ("no, I said yes", "obviously, bhej de") and keyword rules
        misread exactly the answers that matter.
        """
        cleaned = " ".join(re.sub(r"[^\w\s]", " ", answer.lower()).split())
        if not cleaned:
            return "no"                     # silence is not consent
        if cleaned in _YES:
            return "yes"
        if cleaned in _NO:
            return "no"
        try:
            raw = self._extractor.generate(
                _CONSENT_SYSTEM,
                [{"role": "user", "content": f'Asked: "{question}"\nReply: "{answer}"'}],
            ).strip().lower()
        except Exception:                   # degraded mode: only exact words count
            return "no"
        for verdict in ("unclear", "yes", "no"):
            if raw.startswith(verdict):
                return verdict
        return "unclear"

    def _already_consented(self, action: str) -> bool:
        """Whether the user has already approved this exact action in the
        conversation — in which case asking again is what a bad assistant does.

        The pattern this exists for: the model proposes "I'll send Aatmik:
        '…' — go ahead?", the user says "yeah, send it", and then the tool
        gate asks the same question again. A human PA asks once.
        """
        recent = [m for m in self._history[-6:] if isinstance(m.get("content"), str)]
        if not recent or recent[-1]["role"] != "user":
            return False
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        try:
            raw = self._extractor.generate(
                _PRIOR_CONSENT_SYSTEM,
                [{"role": "user",
                  "content": f'Action about to run: "{action}"\n\nConversation:\n{transcript}'}],
            ).strip().lower()
        except Exception:
            return False                     # can't check -> ask, never assume
        return raw.startswith("yes")

    def _make_executor(self, io):
        """Runs a tool the model asked for — gating outward/irreversible ones
        behind the user's permission. Returns the tool's result as a string
        (a decline is a normal result, not an error, so the model handles it)."""
        from ..tools.base import CONFIRM_FIELD

        # Per-turn memory of what the user has ruled on, so a retry of the
        # exact same call doesn't re-ask, and — the dangerous direction — a
        # call the user just declined can never sneak through on the strength
        # of consent given before the decline.
        approved: set = set()
        denied: set = set()

        def executor(name: str, tool_input: dict) -> str:
            tool = self._tools.get(name)
            if tool is None:
                return f"(no such tool: {name})"
            # The model phrases the confirmation itself (a required argument on
            # every gated tool) because only it knows the human names involved —
            # the tool's own arguments hold ids a person should never hear.
            tool_input = dict(tool_input)
            question = tool_input.pop(CONFIRM_FIELD, None)
            if os.environ.get("JARVIS_DEBUG"):
                print(f"  [tool] {name}({tool_input})", file=sys.stderr)

            if tool.needs_confirm and io is not None:
                key = (name, json.dumps(tool_input, sort_keys=True, default=str))
                question = question or tool.confirmation(**tool_input)
                if key not in approved:
                    # Consent already given in conversation counts — unless the
                    # user has since declined this very call at the gate.
                    if key not in denied and self._already_consented(question):
                        approved.add(key)
                    else:
                        io.speak(question)
                        verdict = self._consent(question, io.listen() or "")
                        if verdict == "unclear":
                            io.speak("Sorry — was that a yes or a no?")
                            verdict = self._consent(question, io.listen() or "")
                        if verdict != "yes":
                            denied.add(key)
                            return "The user declined; the action was not performed."
                        approved.add(key)
            return tool.execute(**tool_input)
        return executor

    def _update_memory(self, history: list[dict]) -> None:
        """Second pass: a focused, cheap call that maintains the store. Runs
        against the open-commitments list (with ids) so references like 'both'
        resolve to real ids — the failure the single-pass design couldn't do.
        Works on a snapshot of the history: it runs on the memory worker, and
        the live window may already have moved on."""
        extract_context = _EXTRACT_CONTEXT.format(
            today=_today(),
            facts=self._facts_block(query=_recent_user(history)),
            commitments=self._commitments_block(),
        )
        raw = self._extractor.generate([_EXTRACT_STATIC, extract_context], history)
        updates = _parse_updates(raw)

        open_ids = {c.id for c in self._memory.open_commitments()}
        for fact in updates["remember"]:
            if not self._knows_fact(fact):
                self._memory.add(content=fact, source=_recent_user(history))
        for c in updates["new_commitments"]:
            if not self._has_open_commitment(c):
                self._memory.add_commitment(content=c, source=_recent_user(history))
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


def _clip(text: str, limit: int = 400) -> str:
    """Recalled exchanges are context, not payload — a monologue from last week
    earns a summary-length quote, not a full reprint."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
