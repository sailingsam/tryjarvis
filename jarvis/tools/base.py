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


class Tool:
    name: str = ""
    description: str = ""
    input_schema: dict = {"type": "object", "properties": {}}
    needs_confirm: bool = False

    def execute(self, **kwargs) -> str:
        raise NotImplementedError

    def confirmation(self, **kwargs) -> str:
        """The question to ask before running, when needs_confirm is set."""
        return f"Go ahead with {self.name}?"

    def spec(self) -> dict:
        """The shape the model sees when deciding whether to call this tool."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


class Registry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {t.name: t for t in (tools or [])}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        return [t.spec() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
