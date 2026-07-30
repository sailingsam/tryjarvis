"""Tools — how Jarvis acts on the world (not just talks about it).

A Tool is a capability Claude can choose to invoke: search the web, later read
a calendar, send a message. The tool-use loop lives in the LLM provider; this
module just defines what a tool *is* and keeps a registry of them.

Two safety tiers (Humans-stay-in-control):
  - safe          → run without asking (read-only: search, read calendar)
  - needs_confirm → ask the user first (outward/irreversible: send, post, delete)

The confirmation itself is enforced in the brain's executor, through the IO
channel — so text and voice can confirm differently. MCP tools will later plug
in as Tools too, into this same registry.
"""

from __future__ import annotations

import json

# Injected into every gated tool's schema. The model fills it with the question
# a person would ask — "Send 'happy birthday' to Aatmik on WhatsApp?" — because
# only the model knows the human names behind the ids in the real arguments.
# A template built from the arguments can only ever read the ids aloud, and a
# human PA never says a 14-digit number to ask permission (philosophy #19).
# The brain's executor speaks this field and strips it before the tool runs.
CONFIRM_FIELD = "say_to_confirm"

_CONFIRM_SPEC = {
    "type": "string",
    "description": (
        "REQUIRED. One short spoken question asking the user to confirm this "
        "exact action, phrased the way a person would ask — name people and "
        "things by their human names and quote the content being sent. Never "
        "include ids, phone numbers, JSON or field names. "
        "Example: \"Send 'running late, be there in 10' to Mridul on WhatsApp?\""
    ),
}


class Tool:
    name: str = ""
    description: str = ""
    input_schema: dict = {"type": "object", "properties": {}}
    needs_confirm: bool = False

    def execute(self, **kwargs) -> str:
        raise NotImplementedError

    def confirmation(self, **kwargs) -> str:
        """Fallback question if the model didn't provide one, when needs_confirm."""
        return f"Go ahead with {self.name}?"

    def spec(self) -> dict:
        """The shape the model sees when deciding whether to call this tool."""
        schema = self.input_schema
        if self.needs_confirm:
            schema = json.loads(json.dumps(schema))     # deep copy, leave the original alone
            schema.setdefault("properties", {})[CONFIRM_FIELD] = _CONFIRM_SPEC
            required = schema.setdefault("required", [])
            if CONFIRM_FIELD not in required:
                required.append(CONFIRM_FIELD)
        return {"name": self.name, "description": self.description, "input_schema": schema}


class Registry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {t.name: t for t in (tools or [])}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        return [t.spec() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
