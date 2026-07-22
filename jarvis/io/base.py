"""IO — how the user reaches the brain. A swappable skin.

The brain is I/O-agnostic. Text today (runs anywhere, proves the memory bet),
voice next (the real experience), a phone later. Same brain, different skin.
`listen()` returns None to signal the user wants to stop.
"""

from __future__ import annotations

from typing import Protocol


class IOChannel(Protocol):
    def listen(self) -> str | None:
        ...

    def speak(self, text: str) -> None:
        ...
