"""A stopwatch for one voice turn.

A slow reply has four possible causes — endpointing, transcription, the brain,
or speech synthesis — and they are indistinguishable from the outside. Guessing
wrong means swapping a provider that was never the problem. So every turn can
report where its time actually went:

    you  > kal Mridul ko message bhejna hai
          vad 420ms · stt 380ms · brain 1240ms · tts 190ms  = 2.2s

This is what makes the provider menu meaningful: with numbers you can tell
whether a faster STT is worth a key, or whether the brain is the whole cost and
no provider change will help.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

# The user-visible order of stages, so a turn always reads the same way.
STAGES = ("vad", "stt", "brain", "tts")


class Turn:
    """Elapsed milliseconds per stage for a single exchange."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        if not self.enabled:
            yield
            return
        start = time.monotonic()
        try:
            yield
        finally:
            self._ms[name] = self._ms.get(name, 0.0) + (time.monotonic() - start) * 1000

    def mark(self, name: str, ms: float) -> None:
        """Record a stage measured elsewhere — e.g. time-to-first-audio, which
        only the playback callback knows."""
        if self.enabled:
            self._ms[name] = ms

    def summary(self) -> str:
        if not self.enabled or not self._ms:
            return ""
        known = [s for s in STAGES if s in self._ms]
        extra = sorted(k for k in self._ms if k not in STAGES)
        parts = [f"{s} {self._ms[s]:.0f}ms" for s in known + extra]
        total = sum(self._ms.values()) / 1000
        return f"{' · '.join(parts)}  = {total:.1f}s"
