"""Speech to text — rented ears behind one interface.

Every provider takes finished audio and returns text. It does not touch the
microphone, decide when you stopped talking, or know what happens to the words
afterwards — `jarvis/audio.py` owns all of that. That is what makes these
interchangeable: an adapter is about twenty lines, so a user can pick whichever
service they already pay for, and we can add one on request without the brain
noticing.

Adding a provider means writing `transcribe()` and adding a line to
`voice_registry.py`. Nothing else in the codebase changes.
"""

from __future__ import annotations

from typing import Protocol

from .. import audio

_TIMEOUT = 60.0          # generous: a three-minute utterance is a legal turn


class STTProvider(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int, *,
                   hints: str | None = None) -> str | None:
        """Turn s16 mono PCM into text. None means nothing was said.

        `hints` biases recognition toward words it should expect — in practice
        the names of the user's people, drawn from memory. Generic speech models
        mangle proper nouns ("Mridul" comes back as "Em Riddle"), and those are
        exactly the words a chief of staff cannot afford to get wrong. Because
        Mantrin already knows who matters to you, it can tell its own ears what
        to listen for. Providers that cannot take a hint ignore it.
        """
        ...


class LocalWhisper:
    """faster-whisper on the CPU. Free, offline, and the audio never leaves the
    machine — the honest default for someone who has not chosen a provider yet.

    `small` is the default: `base` audibly mishears — "how are you" became "how
    would you", "Aatmik" became "Atomic" — and a chief of staff that mishears
    is worse than one that takes a beat longer. ~460MB one-time download,
    roughly 2x base's transcription time. Set stt_options {"model": "base"}
    to trade accuracy back for speed; a hosted provider is the real jump.
    """

    def __init__(self, model_size: str = "small", compute_type: str = "int8",
                 language: str | None = None):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, compute_type=compute_type)
        # None = auto-detect per utterance. Auto is right for mixed speech
        # (Hinglish), but on short or unclear clips it can wander into the
        # wrong script entirely — pin it via stt_options {"language": "en"}
        # if that keeps happening.
        self._language = language

    def transcribe(self, pcm: bytes, sample_rate: int, *,
                   hints: str | None = None) -> str | None:
        import numpy as np

        if sample_rate != audio.SAMPLE_RATE:        # pragma: no cover
            raise ValueError(f"LocalWhisper expects {audio.SAMPLE_RATE}Hz audio")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples, language=self._language, initial_prompt=hints or None
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text or None


class _HostedSTT:
    """Shared plumbing for services that accept a WAV upload and answer with
    JSON. The differences between them are a URL, a model name and a field."""

    url: str = ""
    model: str = ""
    text_key: str = "text"

    def __init__(self, api_key: str, model: str | None = None):
        if not api_key:
            raise ValueError(f"{type(self).__name__} needs an API key")
        self._key = api_key
        if model:
            self.model = model

    # Field this service uses to bias recognition, if it supports one at all.
    hint_field: str | None = None

    def _fields(self) -> dict[str, str]:
        return {"model": self.model} if self.model else {}

    def transcribe(self, pcm: bytes, sample_rate: int, *,
                   hints: str | None = None) -> str | None:
        import httpx

        fields = self._fields()
        if hints and self.hint_field:
            fields[self.hint_field] = hints
        wav = audio.to_wav(pcm, sample_rate)
        response = httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self._key}"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            data=fields,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        text = (response.json().get(self.text_key) or "").strip()
        return text or None


class OpenAISTT(_HostedSTT):
    """OpenAI transcription — the same ears ChatGPT's dictation uses."""

    url = "https://api.openai.com/v1/audio/transcriptions"
    model = "gpt-4o-transcribe"
    hint_field = "prompt"


class GrokSTT(_HostedSTT):
    """xAI. Cheapest hosted option by a wide margin at the time of writing."""

    url = "https://api.x.ai/v1/stt"
    model = "grok-stt"


class ExternalDictation:
    """For people who already dictate with a desktop app.

    Willow, Wispr Flow's app, superwhisper and the rest own the microphone and
    type into whatever field has focus — there is no API surface to adapt, and
    Willow does not run on Linux at all. So Mantrin stops listening and reads a
    line of text instead: you dictate with your own tool, and still get a spoken
    answer back. One mode covers every such app, present and future, with no
    per-app code.
    """

    reads_text = True

    def transcribe(self, pcm: bytes, sample_rate: int, *,
                   hints: str | None = None) -> str | None:   # pragma: no cover
        raise RuntimeError("ExternalDictation reads typed text; it never sees audio")
