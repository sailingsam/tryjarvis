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

    def run_tools(self, system: str, messages: list[dict], tools: list[dict], executor) -> str:
        """Agentic reply: let the model call tools, execute them (via `executor`,
        which handles confirmation), feed results back, loop until it answers.

        All Anthropic-specific block handling is contained here — the brain
        passes plain-string history + a plain executor and gets plain text back.
        `executor(name, input) -> str` runs the tool and returns its result.
        """
        if not tools:
            return self.generate(system, messages)

        # Local working copy — never mutate the brain's history with tool blocks.
        convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
        while True:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=convo,
                tools=tools,
            )
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text")

            convo.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    output = executor(block.name, dict(block.input))
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": output}
                    )
            convo.append({"role": "user", "content": results})
