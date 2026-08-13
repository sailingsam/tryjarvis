"""The wake word — a local gate in front of everything else.

Always-on is the whole point of the product, and it is also the thing that makes
an open microphone a problem. Without a gate, every conversation held near the
machine is transcribed: money spent on words meant for someone else, and private
speech leaving the room for no reason.

So the gate runs here, on the machine, over raw frames. Nothing reaches a
transcription service until the wake word fires. This is the one place where
"local models" is the right answer even though Mantrin's brain is deliberately in
the cloud — a gate that phones home is not a gate.

`Always` exists because a gate is wrong while developing: you want to talk to
Mantrin without saying its name forty times an hour.
"""

from __future__ import annotations

from typing import Protocol

from . import audio


class WakeGate(Protocol):
    def open(self, frame: bytes) -> bool:
        """True if this frame completes the wake word."""
        ...

    def reset(self) -> None:
        """Forget partial progress — called after a turn ends."""
        ...


class Always:
    """No gate. Correct for testing, wrong for a microphone left on all day."""

    is_gate = False

    def open(self, frame: bytes) -> bool:
        return True

    def reset(self) -> None:
        pass


class OpenWakeWord:
    """openWakeWord: small ONNX models, running locally, per frame.

    Ships pretrained phrases (`hey_jarvis`, `alexa`, …). A custom phrase such as
    "Mantrin" needs a trained model of its own, which is a separate exercise —
    until then a pretrained phrase is what actually works, so that is the default
    rather than a name we cannot yet detect.
    """

    is_gate = True

    # openWakeWord's feature extractor works in 80ms windows, so frames are
    # gathered up before inference instead of running the model 33 times a second.
    _WINDOW_SAMPLES = 1280

    def __init__(self, phrases: "str | list[str]" = "hey_jarvis", threshold: float = 0.5):
        import warnings

        import openwakeword
        from openwakeword.model import Model

        if audio.SAMPLE_RATE != 16_000:         # pragma: no cover
            raise ValueError("wake word models are trained at 16kHz")

        # openwakeword asks onnxruntime for CUDA and falls back to CPU, which
        # prints a scary-looking UserWarning on every start. The fallback is
        # exactly what we want on a laptop, so the warning is noise.
        warnings.filterwarnings(
            "ignore", message=".*CUDAExecutionProvider.*", category=UserWarning
        )

        if isinstance(phrases, str):
            phrases = [phrases]
        available = available_models()
        missing = [p for p in phrases if p not in available]
        if missing:
            raise ValueError(
                f"no model for {', '.join(missing)}. Available: "
                f"{', '.join(sorted(available))}"
            )
        # Several phrases run in ONE model pass — answering to both "Mantrin"
        # and "Jarvis" costs the same frame loop as answering to one.
        self._model = Model(wakeword_model_paths=[available[p] for p in phrases])
        self._phrase = " / ".join(phrases)
        self._threshold = threshold
        self._pending: bytearray = bytearray()

    def open(self, frame: bytes) -> bool:
        import numpy as np

        self._pending += frame
        fired = False
        need = self._WINDOW_SAMPLES * audio.SAMPLE_WIDTH
        while len(self._pending) >= need:
            window = bytes(self._pending[:need])
            del self._pending[:need]
            scores = self._model.predict(np.frombuffer(window, dtype=np.int16))
            if any(s >= self._threshold for s in scores.values()):
                fired = True
        return fired

    def reset(self) -> None:
        self._pending.clear()
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()


def custom_model_dir():
    """Where user-trained wake models live: drop a `mantrin.onnx` here and
    'mantrin' becomes a phrase Mantrin answers to. See docs/custom-wake-word.md
    for training one (about an hour, free, in a browser)."""
    from pathlib import Path

    from . import config

    return Path(config.CONFIG_DIR) / "wake"


def available_models() -> dict[str, str]:
    """Phrase -> model path: openwakeword's pretrained set, plus anything the
    user dropped into the custom dir. Raises ImportError without openwakeword.
    A custom model wins a name collision — training your own 'hey_jarvis'
    should mean it gets used."""
    import openwakeword

    models = {}
    for path in openwakeword.get_pretrained_model_paths():
        name = path.rsplit("/", 1)[-1].rsplit("_v", 1)[0]
        models[name] = path
    custom = custom_model_dir()
    if custom.is_dir():
        for path in sorted(custom.glob("*.onnx")) + sorted(custom.glob("*.tflite")):
            models[path.stem.lower().replace(" ", "_")] = str(path)
    return models


def available_phrases() -> list[str]:
    """Wake phrases that can actually be detected on this machine."""
    try:
        return sorted(available_models())
    except Exception:                               # noqa: BLE001
        return []


def resolve(phrase: str) -> str | None:
    """Map what a person typed to a phrase a model exists for.

    "jarvis" means "hey_jarvis" to a human; requiring the exact internal model
    name is the kind of thing the philosophy exists to forbid. Exact match
    first, then a containment match either way round.
    """
    norm = phrase.strip().lower().replace(" ", "_")
    if not norm:
        return None
    names = available_phrases()
    if norm in names:
        return norm
    for name in names:
        if norm in name or name in norm:
            return name
    return None


DEFAULT_PHRASE = "hey_jarvis"


def build(phrase: str) -> WakeGate:
    """A gate for this phrase — empty string means deliberately no gate.

    Several phrases may be given comma-separated ("mantrin, jarvis") and the
    gate answers to any of them — how a rename ships without breaking the
    habit of the old name.

    An unknown phrase falls back to the *default gate*, never to an open door:
    with hosted ears, an open microphone ships everything said near the machine
    to a transcription service, on the user's bill. Degrading to a different
    wake word is an inconvenience; degrading to no wake word is a breach.
    """
    if not phrase:
        return Always()
    try:
        wanted = [p for p in (part.strip() for part in phrase.split(",")) if p]
        resolved: list[str] = []
        for p in wanted:
            r = resolve(p)
            if r is None:
                print(
                    f"(no wake-word model for '{p}' — available: "
                    f"{', '.join(available_phrases())}. A custom phrase needs a "
                    f"trained model; see docs/custom-wake-word.md)",
                    flush=True,
                )
            elif r not in resolved:
                if r != p:
                    print(f"(wake word '{p}' -> using the '{r.replace('_', ' ')}' model)",
                          flush=True)
                resolved.append(r)
        if not resolved:
            print(f"(none of '{phrase}' resolved — using '{DEFAULT_PHRASE.replace('_', ' ')}')",
                  flush=True)
            resolved = [DEFAULT_PHRASE]
        return OpenWakeWord(resolved)
    except ImportError:
        print(
            "(openwakeword is not installed — listening without a gate; "
            "everything said near the mic will be transcribed. "
            "pip install -r requirements-voice.txt to fix this.)",
            flush=True,
        )
        return Always()
