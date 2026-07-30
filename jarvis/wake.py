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

    def __init__(self, phrase: str = "hey_jarvis", threshold: float = 0.5):
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

        available = {}
        for path in openwakeword.get_pretrained_model_paths():
            name = path.rsplit("/", 1)[-1].rsplit("_v", 1)[0]
            available[name] = path
        if phrase not in available:
            raise ValueError(
                f"no pretrained model for {phrase!r}. Available: "
                f"{', '.join(sorted(available))}"
            )
        self._model = Model(wakeword_model_paths=[available[phrase]])
        self._phrase = phrase
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


def build(phrase: str) -> WakeGate:
    """A gate for this phrase, or an open door if it is empty.

    Falls back to always-listening with a printed warning rather than refusing to
    start: a missing wake-word model should degrade the product, not break it.
    """
    if not phrase:
        return Always()
    try:
        return OpenWakeWord(phrase)
    except Exception as e:                          # noqa: BLE001
        print(
            f"(wake word '{phrase}' unavailable: {e}\n"
            f" listening without a gate — everything you say near the mic will be "
            f"transcribed. `pip install openwakeword` to enable it.)",
            flush=True,
        )
        return Always()
