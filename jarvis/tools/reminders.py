"""Reminders — how Jarvis promises to speak up later, and keeps the promise.

The commitment store already existed (the extract pass fills it silently);
what it lacked was a TIME. This tool is the explicit, audible version: the
user says "remind me at five" mid-conversation, the model calls set_reminder,
and — because a tool call produces a result the model answers about — the
acknowledgement comes back out loud: "Noted, I'll speak up at five." The user
hears that Jarvis heard.

Deliberately not gated behind confirmation: writing a note in your own book
is not an outward action. The scheduler side (actually speaking when the
moment comes) lives in the daemon's voice loop, not here.
"""

from __future__ import annotations

import time
from datetime import datetime

from .base import Tool

# What the model writes into `when`. One unambiguous shape beats a parser
# that guesses: the model already knows today's date and the current time
# from its context, so resolving "kal shaam 5 baje" is its job, not ours.
_WHEN_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")


class SetReminder(Tool):
    name = "set_reminder"
    description = (
        "Track something the user wants to be reminded of or has committed to do. "
        "If they gave a time, pass `when` — Jarvis will speak up at that moment. "
        "Without `when` the item is simply tracked and raised the next time you talk. "
        "After calling this, always tell the user what you noted and when you'll "
        "bring it up, so they know it registered."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "what": {
                "type": "string",
                "description": "The thing to remind about, phrased as a short task "
                               "the user will recognise later, e.g. \"Call the electrician\".",
            },
            "when": {
                "type": "string",
                "description": "When to speak up, as local time \"YYYY-MM-DD HH:MM\" "
                               "(24h). Resolve relative times (\"in 20 minutes\", "
                               "\"tomorrow evening\") against today's date and the "
                               "current time from your context. Omit if no time was given.",
            },
        },
        "required": ["what"],
    }

    def __init__(self, memory):
        self._memory = memory

    def execute(self, what: str = "", when: str = "") -> str:
        what = what.strip()
        if not what:
            return "Nothing to remember — `what` was empty."
        if not when:
            c = self._memory.add_commitment(what, source="set_reminder")
            return f"Tracked ({c.id}): \"{what}\". It will be raised next conversation."

        due = _parse_when(when.strip())
        if due is None:
            return (f"Could not read the time {when!r} — pass local time as "
                    f"\"YYYY-MM-DD HH:MM\", e.g. \"2026-08-19 17:00\".")
        # A minute of slack covers "right now"-ish times; anything clearly
        # earlier is a resolution mistake worth surfacing, not scheduling.
        if due < time.time() - 60:
            return (f"{when} is already in the past — re-check the date/time "
                    f"against the current time in your context, or ask the user.")
        c = self._memory.add_commitment(what, source="set_reminder", due=due)
        return f"Reminder set ({c.id}): \"{what}\" — Jarvis will speak up at {c.human_due()}."


def _parse_when(when: str) -> float | None:
    for fmt in _WHEN_FORMATS:
        try:
            return datetime.strptime(when, fmt).timestamp()
        except ValueError:
            continue
    return None
