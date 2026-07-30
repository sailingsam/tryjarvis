"""The voice skin — how a person actually reaches the brain.

The brain does not know it is being spoken to. It is handed a string and returns
a string, exactly as in text mode, so everything about memory, tools and
confirmation behaves identically whether you typed or talked. Only this file
knows there is a microphone.

Three behaviours here are what separate this from dictation into a box:

**No button, and no time limit.** The endpointer decides you finished by
listening, so a three-second answer and a three-minute thought both work.

**Interruption.** While Mantrin talks, the microphone stays live. Start speaking
and it stops mid-word, the way a person does. The threshold adapts to how loud
Mantrin sounds in the room, so this works on a laptop speaker as well as
headphones.

**A follow-up window.** After Mantrin replies, it keeps listening for a few
seconds without needing the wake word again. Real conversation is a back and
forth; saying "hey jarvis" before every sentence is not.
"""

from __future__ import annotations

import collections
import time
from typing import Callable

from .. import audio, timings, wake

# How much louder than Mantrin's own voice an interruption has to be. Measured
# against the room during playback rather than fixed, because a laptop speaker
# and a pair of headphones differ enormously at the microphone. This path is
# best-effort by nature — without echo cancellation, a voice quieter than
# Mantrin's own echo is physically indistinguishable from it. The wake word is
# the reliable interrupt: it also runs during playback, and Mantrin's own
# speech never contains it.
_BARGE_IN_MARGIN = 1.6
# ...and never lower than this much above the room's noise gate, so a reply that
# is barely audible to the mic doesn't leave the bar at fan level.
_BARGE_IN_GATE_BOOST = 1.5
_BARGE_IN_ONSET_MS = 360        # sustained: a false stop costs the whole reply

# How long to wait for the command after the wake word before deciding nobody is
# talking to us. Long enough for "hey jarvis" … *thinks* … "remind me to…", short
# enough that a stray detection does not leave the mic open.
_COMMAND_GRACE_MS = 4_000


class VoiceIO:
    """Speech in, speech out, with the mic held open for the whole session."""

    def __init__(
        self,
        stt,
        tts,
        *,
        gate: wake.WakeGate | None = None,
        hints: Callable[[], str | None] | None = None,
        follow_up_ms: int = 8_000,
        show_timings: bool = False,
        stream: audio.FrameStream | None = None,
    ):
        self._stt = stt
        self._tts = tts
        self._gate = gate or wake.Always()
        self._hints = hints
        self._follow_up = follow_up_ms / 1000
        self._show_timings = show_timings

        self._stream = stream or audio.FrameStream()
        self._frames = self._stream.frames()
        # A brief seed so the very first thing said is judged against this room
        # rather than a default. Only a seed: the endpointer keeps adjusting from
        # non-speech frames, so this value stops being the operative one within a
        # fraction of a second.
        seed = audio.calibrate_noise_floor(self._frames)
        self._endpointer = audio.Endpointer(min_peak=seed)
        self._listen_until = 0.0        # follow-up window; past = gate is armed
        self.turn = timings.Turn(enabled=show_timings)

        phrase = getattr(self._gate, "_phrase", "")
        gated = getattr(self._gate, "is_gate", False)
        detail = f", say “{phrase.replace('_', ' ')}”" if gated and phrase else ", no wake word"
        print(f"(listening — noise floor {seed}{detail})", flush=True)

    # ------------------------------------------------------------------ in

    def listen(self) -> str | None:
        """Wait for something worth answering and return it as text."""
        gated = getattr(self._gate, "is_gate", False)
        while True:
            self.turn = timings.Turn(enabled=self._show_timings)
            armed = gated and time.monotonic() > self._listen_until

            if armed:
                if not self._await_wake():
                    return None
                # Wait for the command rather than assuming it is already
                # underway. People say the wake word both ways — "hey jarvis,
                # remind me…" in one breath, and "hey jarvis" … pause …
                # "remind me". Requiring an onset handles both, because the
                # onset is only 120ms and the pre-roll keeps the 300ms before
                # it, so nothing is clipped in the run-on case. Assuming
                # speech had begun broke the pause case outright: it collected
                # silence, transcribed nothing, and went back to sleep.
                utterance = self._endpointer.collect_one(
                    self._frames, onset_timeout_ms=_COMMAND_GRACE_MS
                )
            elif gated:
                # Inside the follow-up window. The window has to be enforced
                # *inside* the wait: without a timeout here, one reply followed
                # by silence would leave this blocked in collect_one with the
                # gate down — and anything said near the machine hours later
                # would be transcribed without the wake word ever being spoken.
                # The window would never close, because expiry is only checked
                # between waits.
                remaining_ms = max(1, int((self._listen_until - time.monotonic()) * 1000))
                utterance = self._endpointer.collect_one(
                    self._frames, onset_timeout_ms=remaining_ms
                )
            else:
                utterance = self._endpointer.collect_one(self._frames)

            if utterance is None:
                return None
            if not utterance:
                # Silence: after the wake word, or for the rest of the follow-up
                # window. Re-arm rather than answering nothing — the next pass
                # through the loop finds the window expired and waits for the
                # wake word again.
                self._gate.reset()
                continue
            # What the recogniser is billed for starts at the onset; the wait
            # before it is idle time, not latency. The endpointer's cost per
            # turn is its trailing-silence window — fixed by design, but shown
            # so the total reads honestly.
            self.turn.mark("vad", self._endpointer.silence_ms)

            with self.turn.stage("stt"):
                hints = self._hints() if self._hints else None
                text = self._stt.transcribe(utterance, audio.SAMPLE_RATE, hints=hints)

            if text:
                print(f"you  > {text}")
                return text
            # Nothing intelligible — go back to waiting rather than bothering the
            # brain with an empty turn.
            self._gate.reset()

    def _await_wake(self) -> bool:
        """Consume frames until the wake word fires. False if the mic died."""
        for frame in self._frames:
            # Idle is when most of the day's audio goes past, so it is also when
            # the noise floor must keep learning. Otherwise music that started
            # while Mantrin was dormant would meet a stale, quiet-room gate the
            # moment the wake word fires.
            self._endpointer.observe(frame)
            if self._gate.open(frame):
                self._gate.reset()
                return True
        return False

    # ----------------------------------------------------------------- out

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}\n")
        started = time.monotonic()
        first: list[float] = []
        playback = self._tts.speak(
            text, on_first_audio=lambda: first.append(time.monotonic() - started)
        )
        if playback is None:                    # the Silent voice
            self._after_turn()
            return

        interrupted = self._watch_for_interruption(playback)
        playback.wait(timeout=5)
        if first:
            self.turn.mark("tts", first[0] * 1000)

        if interrupted:
            print("(interrupted)", flush=True)
        self._after_turn()

    def _after_turn(self) -> None:
        # Whatever the mic picked up of Mantrin's own voice is not input.
        self._stream.drain()
        self._gate.reset()
        self._listen_until = time.monotonic() + self._follow_up
        if self._show_timings:
            summary = self.turn.summary()
            if summary:
                print(f"      {summary}\n", flush=True)

    def _watch_for_interruption(self, playback: audio.Playback) -> bool:
        """Listen while Mantrin talks; stop it the moment the user cuts in.

        There is no echo cancellation, so the microphone hears Mantrin too.
        Two ways to cut in:

        **The wake word, which always works.** It keeps running during
        playback, and it cannot be fooled by echo — whatever Mantrin is
        saying, it is not saying "hey jarvis". This is the path to rely on
        when just talking doesn't register (physics: a voice quieter at the
        mic than Mantrin's own echo cannot be told apart from it by energy).

        **Just talking louder**, judged by three tests together:
        - it must be *speech* to the VAD — a fan, a chair, a keyboard never
          counts, however loud
        - it must be markedly louder than Mantrin's own voice as heard back
          through the mic. That level is tracked across the whole reply — an
          earlier version measured only the first half-second, which is
          mostly player start-up latency, so the bar was set against silence
          and Mantrin tripped over its own first loud word — but the tracking
          is *lagged* by one onset window, so the user's opening words never
          raise the bar against themselves
        - it must be sustained, because a false stop costs the rest of the
          reply and a real interrupter keeps talking
        """
        gated = getattr(self._gate, "is_gate", False)
        onset_needed = max(1, _BARGE_IN_ONSET_MS // audio.FRAME_MS)
        pending: collections.deque[int] = collections.deque(maxlen=onset_needed)
        own_voice = 0
        run = 0

        for frame in self._frames:
            if playback.stopped or not playback.playing:
                return False
            peak = audio._peak(frame)

            if gated and self._gate.open(frame):
                playback.stop()
                self._gate.reset()
                return True

            warmed_up = len(pending) == pending.maxlen
            if warmed_up:
                own_voice = max(own_voice, pending[0])   # oldest — one lag behind
            pending.append(peak)
            if not warmed_up:
                continue        # nothing believable to compare against yet

            threshold = max(
                int(self._endpointer.gate * _BARGE_IN_GATE_BOOST),
                int(own_voice * _BARGE_IN_MARGIN),
            )
            cut_in = peak >= threshold and self._endpointer.is_speech_frame(frame)
            run = run + 1 if cut_in else 0
            if run >= onset_needed:
                playback.stop()
                return True
        return False

    # --------------------------------------------------------------- close

    def close(self) -> None:
        self._stream.close()


class DictationIO:
    """For someone who dictates with their own desktop app.

    Willow, Wispr Flow's app and the rest own the microphone and type into
    whichever field has focus, so there is nothing to integrate with — Mantrin
    just reads a line and answers out loud. One mode covers every such app.
    """

    def __init__(self, tts, *, show_timings: bool = False):
        self._tts = tts
        self.turn = timings.Turn(enabled=show_timings)
        print("(dictate into this prompt with your own tool — Mantrin speaks back)",
              flush=True)

    def listen(self) -> str | None:
        try:
            text = input("you  > ").strip()
        except EOFError:
            return None
        return text or None

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}\n")
        playback = self._tts.speak(text)
        if playback is not None:
            playback.wait(timeout=120)

    def close(self) -> None:
        pass
