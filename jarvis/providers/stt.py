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

import queue
import threading
import urllib.parse
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
        # vad_filter prunes non-speech before decoding — our endpointer is
        # deliberately loose (better to over-capture than clip a word), and
        # whisper *hallucinates* on audio that holds no speech.
        segments, _ = self._model.transcribe(
            samples, language=self._language, initial_prompt=hints or None,
            vad_filter=True, condition_on_previous_text=False,
        )
        text = " ".join(seg.text for seg in segments).strip()
        if not text:
            return None
        # Whisper's signature failure on unclear audio is to echo its own
        # initial_prompt back — a live session transcribed "Names that may come
        # up." out of a mumble, which is *our hint text*, not the user. Anything
        # that reads as a piece of the prompt was never said.
        if hints and _echoes_prompt(text, hints):
            return None
        return text


def _echoes_prompt(text: str, prompt: str) -> bool:
    def _norm(s: str) -> str:
        return " ".join("".join(c for c in s.lower() if c.isalnum() or c.isspace()).split())

    heard, said = _norm(text), _norm(prompt)
    return bool(heard) and heard in said


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
    """xAI. Cheapest hosted option by a wide margin at the time of writing.

    Also the first provider here with *streaming* ears: audio goes up the
    socket while you are still talking, so by the time you let go of the talk
    key the transcript is already mostly done — the recognition time hides
    inside the speaking time instead of following it.
    """

    url = "https://api.x.ai/v1/stt"
    ws_url = "wss://api.x.ai/v1/stt"
    model = "grok-stt"

    def stream_session(self, sample_rate: int, *, hints: str | None = None):
        """A live session for one utterance, or None if the websocket layer
        isn't available. Falls back to nothing rather than raising — the
        caller always still holds the full audio for a plain transcribe()."""
        try:
            import websockets  # noqa: F401
        except ImportError:
            return None
        return _GrokStream(self._key, self.ws_url, sample_rate, hints)


class _GrokStream:
    """One utterance over xAI's streaming socket.

    The contract with the voice layer is tiny: `send(frame)` while the key is
    held, `finish()` on release (returns the transcript or None), `abort()`
    if the audio turned out to be nothing. All socket work happens on its own
    threads; a connection still being established just queues frames, so the
    first syllable is never lost to a handshake.
    """

    _FINISH_TIMEOUT = 8.0

    def __init__(self, key: str, ws_url: str, sample_rate: int, hints: str | None):
        self._q: "queue.Queue[bytes | None]" = queue.Queue()
        self._text: str | None = None
        self._done = threading.Event()
        self._failed = False
        params = [("sample_rate", str(sample_rate)), ("encoding", "pcm")]
        for term in _keyterms(hints):
            params.append(("keyterm", term))
        self._url = f"{ws_url}?{urllib.parse.urlencode(params)}"
        self._key = key
        threading.Thread(target=self._run, daemon=True, name="stt-stream").start()

    def send(self, frame: bytes) -> None:
        if not self._failed:
            self._q.put(frame)

    def finish(self) -> str | None:
        """Audio over — return the transcript, or None (caller falls back)."""
        self._q.put(None)
        self._done.wait(timeout=self._FINISH_TIMEOUT)
        return None if self._failed else self._text

    def abort(self) -> None:
        """The utterance was noise (an accidental tap) — just hang up."""
        self._failed = True
        self._q.put(None)

    def _run(self) -> None:
        try:
            import json

            from websockets.sync.client import connect

            with connect(self._url,
                         additional_headers={"Authorization": f"Bearer {self._key}"},
                         open_timeout=5) as ws:

                def pump() -> None:
                    while True:
                        item = self._q.get()
                        if item is None:
                            ws.send(json.dumps({"type": "audio.done"}))
                            return
                        ws.send(item)

                threading.Thread(target=pump, daemon=True, name="stt-stream-send").start()
                # The final text arrives in `transcript.partial` events marked
                # is_final — `transcript.done` closes the session with an EMPTY
                # text field (measured, not assumed). Segments are keyed by
                # start time because a finalized segment is re-emitted when
                # speech_final fires, and appending both would stutter.
                segments: dict[float, str] = {}
                for raw in ws:
                    event = json.loads(raw)
                    etype = event.get("type")
                    if etype == "transcript.partial" and event.get("is_final"):
                        text = (event.get("text") or "").strip()
                        if text:
                            segments[float(event.get("start") or 0.0)] = text
                    elif etype == "transcript.done":
                        done = (event.get("text") or "").strip()
                        joined = " ".join(segments[k] for k in sorted(segments))
                        self._text = done or joined.strip() or None
                        return
        except Exception:                   # noqa: BLE001 — fallback handles it
            self._failed = True
        finally:
            self._done.set()


def _keyterms(hints: str | None, limit: int = 20) -> list[str]:
    """The streaming API takes explicit key terms rather than a prompt — pull
    the proper nouns out of our hint sentence ("Names that may come up: …")."""
    if not hints:
        return []
    _, _, tail = hints.partition(":")
    terms = []
    for raw in (tail or hints).replace(".", " ").split(","):
        term = raw.strip()
        if term and len(term) <= 50 and term[:1].isupper():
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


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
