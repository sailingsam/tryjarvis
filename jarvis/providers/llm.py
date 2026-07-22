"""LLM — rented intelligence, behind a one-method interface.

The brain only ever calls `generate(system, messages)`. Anything that can
turn a system prompt + a chat history into text can implement this: Claude
today, a local model tomorrow, whatever is best later. This is philosophy
#2 (Intelligence is Replaceable) made concrete.
"""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    def generate(self, system: str, messages: list[dict]) -> str:
        """messages: [{"role": "user"|"assistant", "content": str}, ...]"""
        ...


class ClaudeLLM:
    def __init__(self, model: str, max_tokens: int = 1024):
        # Imported here so the rest of Jarvis loads even without the SDK.
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system: str, messages: list[dict]) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
        )
        return "".join(block.text for block in resp.content if block.type == "text")
