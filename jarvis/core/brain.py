"""Brain — where understanding lives. The moat.

Each turn:
  1. Load what Jarvis knows (memory) and put it in front of the model.
  2. Ask the model for a natural reply AND any new durable facts worth keeping.
  3. Persist those facts with their source (the utterance that taught them).

The model is rented; deciding *what to remember* and *how to use it* is ours.
We keep extraction provider-agnostic: the model returns plain JSON, so any
LLMProvider works — no vendor-specific tool schemas.
"""

from __future__ import annotations

import json

from ..core.memory import MemoryStore
from ..providers.llm import LLMProvider

_SYSTEM = """You are Jarvis, a personal AI companion. You are talking with ONE person — your user — and you remember them across conversations.

WHAT YOU ALREADY KNOW ABOUT THE USER:
{memories}

HOW TO REPLY:
- Be warm, concise, and natural — you are a companion, not a chatbot reciting facts.
- Use what you know. Never ask the user to repeat something you already know.
- When the user tells you something durable and worth remembering later
  (a preference, a person in their life, a goal, a project, an ongoing fact),
  capture it as a short third-person fact, e.g. "User is vegetarian",
  "Tanay is the user's co-founder". Do NOT remember one-off chit-chat,
  questions, or things that are only true right now.

OUTPUT FORMAT — return ONLY a JSON object, nothing else:
{{"reply": "<what you say to the user>", "remember": ["<new durable fact>", ...]}}
Use an empty list for "remember" when there is nothing new worth keeping."""


class Brain:
    def __init__(self, llm: LLMProvider, memory: MemoryStore):
        self._llm = llm
        self._memory = memory
        self._history: list[dict] = []  # this session's conversation

    def _system_prompt(self) -> str:
        mems = self._memory.recall()
        if mems:
            known = "\n".join(f"- {m.content} (learned {m.human_time()})" for m in mems)
        else:
            known = "(nothing yet — this is a fresh relationship)"
        return _SYSTEM.format(memories=known)

    def think(self, user_text: str) -> str:
        """Take what the user said, return what Jarvis says. Learns as a side effect."""
        self._history.append({"role": "user", "content": user_text})
        raw = self._llm.generate(self._system_prompt(), self._history)

        reply, new_facts = _parse(raw)
        for fact in new_facts:
            self._memory.add(content=fact, source=user_text)

        self._history.append({"role": "assistant", "content": reply})
        return reply


def _parse(raw: str) -> tuple[str, list[str]]:
    """Pull reply + facts out of the model's JSON. Degrade gracefully: if it
    didn't return clean JSON, treat the whole thing as the reply and remember
    nothing — better a plain answer than a crash."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text
    try:
        data = json.loads(text)
        reply = str(data.get("reply", "")).strip()
        facts = [str(f).strip() for f in data.get("remember", []) if str(f).strip()]
        return (reply or raw.strip()), facts
    except (json.JSONDecodeError, AttributeError):
        return raw.strip(), []
