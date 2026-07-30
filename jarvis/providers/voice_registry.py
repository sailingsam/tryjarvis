"""What ears and voices Mantrin can wear, and how to put one on.

Everything swappable in Mantrin is swappable the same way: an interface, a set
of adapters, and one table that names them. Memory works like this, the language
model works like this, and so do speech and voice. The point is that a user runs
their own stack — the service they already pay for, or nothing hosted at all —
and Mantrin does not care.

A spec carries what `mantrin setup` needs to ask an honest question: what this
option is good at, what it will cost you in keys, and what still has to be
installed. Deliberately no prices: published rates move, are quoted in
incompatible units, and a stale number in a setup prompt is worse than no
number. The vendor's own page is one link away.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Spec:
    label: str
    hint: str                                   # one line, qualitative
    factory: Callable[..., object]
    env_keys: tuple[str, ...] = ()              # secrets this needs
    extras: tuple[str, ...] = ()                # importable modules it needs
    docs: str = ""                              # where to get a key
    mode: str = "audio"                         # "text" = owns input, no mic

    @property
    def needs_key(self) -> bool:
        return bool(self.env_keys)


def _missing_modules(spec: Spec) -> list[str]:
    return [m for m in spec.extras if importlib.util.find_spec(m) is None]


def _missing_keys(spec: Spec) -> list[str]:
    return [k for k in spec.env_keys if not os.environ.get(k)]


def requirements(spec: Spec) -> tuple[list[str], list[str]]:
    """(missing python modules, missing environment keys)."""
    return _missing_modules(spec), _missing_keys(spec)


# --------------------------------------------------------------------- STT


def _local_whisper(**kw):
    from .stt import LocalWhisper

    return LocalWhisper(model_size=kw.get("model") or "base",
                        language=kw.get("language"))


def _openai_stt(**kw):
    from .stt import OpenAISTT

    return OpenAISTT(os.environ["OPENAI_API_KEY"], model=kw.get("model"))


def _grok_stt(**kw):
    from .stt import GrokSTT

    return GrokSTT(os.environ["XAI_API_KEY"], model=kw.get("model"))


def _external_dictation(**kw):
    from .stt import ExternalDictation

    return ExternalDictation()


STT: dict[str, Spec] = {
    "whisper-local": Spec(
        label="Whisper (on this machine)",
        hint="free and offline — your voice never leaves the laptop",
        factory=_local_whisper,
        extras=("faster_whisper", "numpy"),
    ),
    "grok": Spec(
        label="Grok (xAI)",
        hint="cheapest hosted option, and quick",
        factory=_grok_stt,
        env_keys=("XAI_API_KEY",),
        docs="https://console.x.ai",
    ),
    "openai": Spec(
        label="OpenAI",
        hint="accurate, and takes a hint about names it should expect",
        factory=_openai_stt,
        env_keys=("OPENAI_API_KEY",),
        docs="https://platform.openai.com/api-keys",
    ),
    "external": Spec(
        label="My own dictation app (Wispr Flow, Willow, superwhisper…)",
        hint="you dictate into the terminal with your app; Mantrin still speaks back",
        factory=_external_dictation,
        mode="text",
    ),
}

# --------------------------------------------------------------------- TTS


def _local_piper(**kw):
    from .tts import LocalPiper

    return LocalPiper(voice=kw.get("voice") or LocalPiper.DEFAULT_VOICE)


def _openai_tts(**kw):
    from .tts import OpenAITTS

    return OpenAITTS(os.environ["OPENAI_API_KEY"], voice=kw.get("voice"),
                     model=kw.get("model"))


def _grok_tts(**kw):
    from .tts import GrokTTS

    return GrokTTS(os.environ["XAI_API_KEY"], voice=kw.get("voice"))


def _silent(**kw):
    from .tts import Silent

    return Silent()


TTS: dict[str, Spec] = {
    "piper-local": Spec(
        label="Piper (on this machine)",
        hint="free, offline, and the fastest to start speaking",
        factory=_local_piper,
        extras=("piper",),
    ),
    "openai": Spec(
        label="OpenAI",
        hint="natural, and streams raw audio so there is no decode delay",
        factory=_openai_tts,
        env_keys=("OPENAI_API_KEY",),
        docs="https://platform.openai.com/api-keys",
    ),
    "grok": Spec(
        label="Grok (xAI)",
        hint="expressive voices, very cheap per character",
        factory=_grok_tts,
        env_keys=("XAI_API_KEY",),
        docs="https://console.x.ai",
    ),
    "none": Spec(
        label="Don't speak — print replies",
        hint="for a machine with no speaker, or when you just want it quiet",
        factory=_silent,
    ),
}

DEFAULT_STT = "whisper-local"
DEFAULT_TTS = "piper-local"


class Unavailable(RuntimeError):
    """A chosen provider cannot run yet, and the message says exactly why."""


def _build(table: dict[str, Spec], name: str, kind: str, options: dict) -> object:
    spec = table.get(name)
    if spec is None:
        raise Unavailable(
            f"Unknown {kind} provider {name!r}. Available: {', '.join(table)}"
        )
    modules, keys = requirements(spec)
    if modules:
        raise Unavailable(
            f"{spec.label} needs {', '.join(modules)} installed. "
            f"Run: pip install -r requirements-voice.txt"
        )
    if keys:
        where = f" Get one at {spec.docs}." if spec.docs else ""
        raise Unavailable(
            f"{spec.label} needs {', '.join(keys)} set. Run `mantrin setup`.{where}"
        )
    return spec.factory(**options)


def build_stt(name: str, **options) -> object:
    return _build(STT, name, "STT", options)


def build_tts(name: str, **options) -> object:
    return _build(TTS, name, "TTS", options)


def spec_for(kind: str, name: str) -> Spec | None:
    return (STT if kind == "stt" else TTS).get(name)
