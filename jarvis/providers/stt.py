"""STT — rented ears, behind an interface. Local-first (Whisper) for v1:
free, private (audio never leaves the machine), swap to hosted later.

Deps are heavy and optional, so they import lazily — the text skin works
without any of this installed. See requirements-voice.txt.
"""

from __future__ import annotations

from typing import Protocol


class STTProvider(Protocol):
    def transcribe_once(self) -> str | None:
        """Record one utterance from the mic and return its text (None = silence/stop)."""
        ...


class WhisperSTT:
    """Records from the mic until a pause, then transcribes locally with
    faster-whisper. A thin, replaceable adapter — nothing product-defining here."""

    def __init__(self, model_size: str = "base", sample_rate: int = 16000):
        import numpy  # noqa: F401  (ensure available early)
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, compute_type="int8")
        self._sr = sample_rate

    def transcribe_once(self) -> str | None:
        import numpy as np
        import sounddevice as sd

        # Simple push-to-talk-ish capture: record a fixed window. A later
        # version does proper voice-activity detection; this is the v1 shell.
        seconds = 6
        print("(listening…)")
        audio = sd.rec(int(seconds * self._sr), samplerate=self._sr, channels=1, dtype="float32")
        sd.wait()
        samples = audio.flatten().astype(np.float32)
        segments, _ = self._model.transcribe(samples, language=None)
        text = " ".join(seg.text for seg in segments).strip()
        return text or None
