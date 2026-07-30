"""Text to speech — a rented voice behind one interface.

Providers implement `stream()`, yielding raw s16 PCM as it is synthesised. The
base class turns that into `speak()`, which starts playback and hands back a
live handle the caller can cut off mid-word.

Streaming is not a nicety here. Waiting for a whole sentence to synthesise puts
a second of dead air after every reply, and dead air is what makes an assistant
feel like software. Yielding as you go gets first audio out in a few hundred
milliseconds and hides the rest behind speech already playing.

Adding a provider means writing `stream()` and adding a line to
`voice_registry.py`.
"""

from __future__ import annotations

import re
from typing import Iterator, Protocol

from .. import audio

_TIMEOUT = 60.0
_MODEL_DIR_ENV = "MANTRIN_PIPER_DIR"


def speakable(text: str) -> str:
    """Markdown down to prose, because the voice reads what it is given.

    The brain writes for a reader — **bold**, bullets, headers. Piper's
    phonemizer dutifully pronounces the punctuation ("asterisk asterisk"), and
    hosted voices are no better. The printed reply keeps its formatting; only
    what reaches the synthesiser is flattened.
    """
    t = re.sub(r"```.+?```", " ", text, flags=re.S)         # code blocks: unreadable aloud
    t = re.sub(r"`([^`]*)`", r"\1", t)                       # inline code
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)           # [label](url) -> label
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)             # headers
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)           # bullet markers
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t, flags=re.S)    # bold
    t = re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)", r"\1", t)  # emphasis
    t = re.sub(r"^\s*(?:[-*_]\s*){3,}$", "", t, flags=re.M)  # horizontal rules
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


class TTSProvider(Protocol):
    def speak(self, text: str, *, on_first_audio=None) -> audio.Playback | None:
        """Begin speaking and return at once, so the caller can listen for an
        interruption while this plays."""
        ...


class StreamingTTS:
    """Base for anything that can produce audio incrementally."""

    sample_rate: int = 24_000

    def stream(self, text: str) -> Iterator[bytes]:     # pragma: no cover
        raise NotImplementedError

    def speak(self, text: str, *, on_first_audio=None) -> audio.Playback | None:
        return audio.play_stream(
            self.stream(speakable(text)), sample_rate=self.sample_rate,
            on_start=on_first_audio,
        )


class LocalPiper(StreamingTTS):
    """Piper — offline, free, and genuinely quick because it is a small ONNX
    model rather than a hosted service. The default when no key is configured.

    Voice models are downloaded once (~60MB) and cached. Piper ships its own
    espeak-ng data, so unlike pyttsx3 this needs nothing installed by apt.
    """

    DEFAULT_VOICE = "en_US-lessac-medium"

    def __init__(self, voice: str = DEFAULT_VOICE, model_dir: str | None = None):
        import os
        from pathlib import Path

        from piper import PiperVoice
        from piper.download_voices import download_voice

        cache = Path(
            model_dir or os.environ.get(_MODEL_DIR_ENV)
            or Path.home() / ".cache" / "mantrin" / "piper"
        )
        cache.mkdir(parents=True, exist_ok=True)
        model = cache / f"{voice}.onnx"
        if not model.exists():
            # First run only. Printed rather than silent because it is ~60MB and
            # the wait would otherwise look like a hang.
            print(f"(downloading voice '{voice}' once — about 60MB…)", flush=True)
            download_voice(voice, cache)
        self._voice = PiperVoice.load(model)
        self.sample_rate = self._voice.config.sample_rate

    def stream(self, text: str) -> Iterator[bytes]:
        for chunk in self._voice.synthesize(text):
            yield chunk.audio_int16_bytes


class _HostedTTS(StreamingTTS):
    """Shared plumbing for hosted voices: POST some JSON, stream audio back."""

    url: str = ""
    model: str = ""
    voice: str = ""

    def __init__(self, api_key: str, voice: str | None = None, model: str | None = None):
        if not api_key:
            raise ValueError(f"{type(self).__name__} needs an API key")
        self._key = api_key
        if voice:
            self.voice = voice
        if model:
            self.model = model

    def _payload(self, text: str) -> dict:              # pragma: no cover
        raise NotImplementedError

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}"}

    def stream(self, text: str) -> Iterator[bytes]:
        import httpx

        with httpx.stream("POST", self.url, headers=self._headers(),
                          json=self._payload(text), timeout=_TIMEOUT) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if chunk:
                    yield chunk


class OpenAITTS(_HostedTTS):
    """OpenAI speech. Asks for raw PCM rather than MP3, so audio goes straight
    to the speaker with no decode step in the latency path."""

    url = "https://api.openai.com/v1/audio/speech"
    model = "gpt-4o-mini-tts"
    voice = "alloy"
    sample_rate = 24_000        # documented rate for the pcm response format

    def _payload(self, text: str) -> dict:
        return {"model": self.model, "voice": self.voice,
                "input": text, "response_format": "pcm"}


class GrokTTS(_HostedTTS):
    """xAI voices. Notably cheap per character.

    Returns MP3, which the ALSA/PipeWire players cannot take, so this buffers
    the response and decodes it — costing the streaming latency advantage. If a
    raw-PCM response format appears in their API, switch to it and drop the
    decode.
    """

    url = "https://api.x.ai/v1/tts"
    voice = "eve"

    def _payload(self, text: str) -> dict:
        return {"text": text, "voice_id": self.voice, "language": "en"}

    def speak(self, text: str, *, on_first_audio=None) -> audio.Playback | None:
        import httpx

        response = httpx.post(self.url, headers=self._headers(),
                              json=self._payload(speakable(text)), timeout=_TIMEOUT)
        response.raise_for_status()
        pcm, rate = audio.decode_to_pcm(response.content)
        # The rate is only known after decoding, and the player is started with a
        # fixed rate — so the audio must be resolved before playback begins.
        return audio.play_stream(
            iter([pcm]), sample_rate=rate or self.sample_rate, on_start=on_first_audio
        )


class Silent:
    """Prints instead of speaking — for a machine with no speaker, and for text
    mode, so the brain path is identical either way."""

    def speak(self, text: str, *, on_first_audio=None) -> audio.Playback | None:
        if on_first_audio:
            on_first_audio()
        return None
