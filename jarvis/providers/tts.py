"""TTS — rented voice, behind an interface. Local-first (pyttsx3) for v1:
offline, no key. Swap to a natural hosted voice (ElevenLabs/Cartesia) later
without touching the brain.
"""

from __future__ import annotations

from typing import Protocol


class TTSProvider(Protocol):
    def say(self, text: str) -> None:
        ...


class Pyttsx3TTS:
    def __init__(self):
        import pyttsx3

        self._engine = pyttsx3.init()

    def say(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()
