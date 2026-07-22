"""Voice skin — STT in front of the brain, TTS behind it. The brain never
knows it's being spoken to; it's the same brain the text skin uses."""

from __future__ import annotations

from ..providers.stt import STTProvider
from ..providers.tts import TTSProvider


class VoiceIO:
    def __init__(self, stt: STTProvider, tts: TTSProvider):
        self._stt = stt
        self._tts = tts

    def listen(self) -> str | None:
        text = self._stt.transcribe_once()
        if text:
            print(f"you  > {text}")
        return text

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}\n")
        self._tts.say(text)
