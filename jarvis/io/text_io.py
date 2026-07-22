"""Text skin. Runs anywhere, needs nothing. This is how we prove
'memory compounds' without a microphone in the loop."""

from __future__ import annotations

_EXIT = {"exit", "quit", "bye", "q"}


class TextIO:
    def listen(self) -> str | None:
        try:
            text = input("you  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not text or text.lower() in _EXIT:
            return None
        return text

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}\n")
