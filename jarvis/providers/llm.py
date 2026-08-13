"""LLM — rented intelligence, behind a one-method interface.

The brain only ever calls `generate(system, messages)`. Anything that can
turn a system prompt + a chat history into text can implement this: Claude
today, a local model tomorrow, whatever is best later. This is philosophy
#2 (Intelligence is Replaceable) made concrete.

`system` may be one string, or a list of strings where every part except the
last is stable across turns. That split exists for caching: what never changes
(persona, rules, tool schemas riding in front of it) gets processed once and
reused, instead of being re-read at full price on every single turn. How the
reuse happens is each provider's business — Anthropic's cache_control lives
here, not in the brain.
"""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    def generate(self, system: str | list[str], messages: list[dict]) -> str:
        """messages: [{"role": "user"|"assistant", "content": str}, ...]"""
        ...


def _system_blocks(system: str | list[str]) -> str | list[dict]:
    """One string passes through untouched. A list becomes text blocks with a
    cache breakpoint after the stable parts (everything but the last) — the
    prefix that includes any tools ahead of it is then served from cache."""
    if isinstance(system, str):
        return system
    blocks = [{"type": "text", "text": part} for part in system]
    for block in blocks[:-1]:
        # 1h TTL, not the default 5 minutes: an always-on assistant is used in
        # bursts through a day. With 5m, every return after a pause re-reads
        # the whole static prompt at full price and full latency; 1h keeps it
        # warm across the gaps. Costs 2x to write instead of 1.25x — three
        # turns inside the hour and it has paid for itself.
        block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return blocks


def _mark_last_message(messages: list[dict]) -> list[dict]:
    """A copy of `messages` with a cache breakpoint on the final content block.

    Inside one turn's tool loop the conversation only ever grows, so each round
    trip re-sends everything the previous one sent — schemas, history, tool
    results. Moving a breakpoint to the current tail makes every round trip
    after the first a cache read instead of a full re-read. The copy matters:
    the stored conversation stays clean of vendor markers.
    """
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    elif isinstance(content, list) and content and isinstance(content[-1], dict):
        content = content[:-1] + [{**content[-1], "cache_control": {"type": "ephemeral"}}]
    else:
        return messages          # SDK blocks mid-loop — skip rather than fight them
    return messages[:-1] + [{**last, "content": content}]


def _execute_calls(calls: list, executor) -> list[str]:
    """Run one round's tool calls — concurrently when there are several.

    When the model asks for WhatsApp and the calendar in the same breath,
    running them one after another doubles the wait for no reason: each call
    is network-bound, not CPU-bound. Anything needing the user's consent
    still serializes — the brain's consent gate holds a lock, because two
    confirmation questions spoken over each other answer neither.
    """
    if len(calls) <= 1:
        return [executor(b.name, dict(b.input)) for b in calls]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as pool:
        return list(pool.map(lambda b: executor(b.name, dict(b.input)), calls))


class ClaudeLLM:
    def __init__(self, model: str, max_tokens: int = 1024):
        # Imported here so the rest of Jarvis loads even without the SDK.
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def _request(self, on_text, **kwargs):
        """One API round trip. With `on_text`, the response is streamed and
        every text delta is handed over as it arrives — that callback is how
        the voice starts speaking the first sentence while the rest of the
        reply is still being generated. Caching works identically either way."""
        if on_text is None:
            return self._client.messages.create(**kwargs)
        with self._client.messages.stream(**kwargs) as stream:
            for delta in stream.text_stream:
                on_text(delta)
            return stream.get_final_message()

    def generate(self, system: str | list[str], messages: list[dict], on_text=None) -> str:
        resp = self._request(
            on_text,
            model=self._model,
            max_tokens=self._max_tokens,
            system=_system_blocks(system),
            messages=messages,
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    def run_tools(self, system: str | list[str], messages: list[dict], tools: list[dict],
                  executor, on_text=None) -> str:
        """Agentic reply: let the model call tools, execute them (via `executor`,
        which handles confirmation), feed results back, loop until it answers.

        All Anthropic-specific block handling is contained here — the brain
        passes plain-string history + a plain executor and gets plain text back.
        `executor(name, input) -> str` runs the tool and returns its result.

        With `on_text`, text streams out of every round — including the
        natural preamble before a tool call ("let me check…"), which is
        exactly what a person would say out loud while reaching for a tool.
        """
        if not tools:
            return self.generate(system, messages, on_text=on_text)

        # Local working copy — never mutate the brain's history with tool blocks.
        convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
        while True:
            resp = self._request(
                on_text,
                model=self._model,
                max_tokens=self._max_tokens,
                system=_system_blocks(system),
                messages=_mark_last_message(convo),
                tools=tools,
            )
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text")

            convo.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            outputs = _execute_calls(calls, executor)
            results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": out}
                for b, out in zip(calls, outputs)
            ]
            convo.append({"role": "user", "content": results})
