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
import re
import time
from typing import Callable

from .. import audio, config, timings, wake


def _mic_paused() -> bool:
    """The tray's hard mute: while this flag file exists, even the wake word
    is ignored. A file rather than a socket message so a different process
    (the tray) can flip it with no protocol, and a crash leaves it readable."""
    return config.MIC_PAUSE_FILE.exists()

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
# How long after playback starts before the *energy* path may interrupt at all.
# Covers player start-up silence plus one onset window, so the own-voice bar has
# heard actual playback before anything is measured against it. The wake word
# is exempt — it works from the first frame. With echo cancellation the mic
# barely hears Mantrin at all, so only the canceller's own convergence moment
# needs covering.
_BARGE_IN_BLIND_MS = 900
_BARGE_IN_BLIND_EC_MS = 300

# How long to wait for the command after the wake word before deciding nobody is
# talking to us. Long enough for "hey jarvis" … *thinks* … "remind me to…", short
# enough that a stray detection does not leave the mic open.
_COMMAND_GRACE_MS = 4_000

# How long a *thinking pause* may last once the words so far sound unfinished.
# "…his name was ummm" followed by two seconds of silence is someone reaching
# for a name, not someone done talking — silence alone cannot tell those apart,
# but the words can. Generous on purpose: this timer only runs when the
# transcript already says the thought is dangling.
_THINKING_MS = 5_000
_MAX_CONTINUATIONS = 3

# Words that essentially never end a finished English/Hinglish thought.
# Deliberately conservative: a false "unfinished" costs a five-second wait
# before Mantrin replies, so everyday sentence-enders ("you", "hai", "was")
# stay out even though they occasionally dangle.
_DANGLING_WORDS = {
    # fillers
    "um", "umm", "ums", "uhm", "uh", "uhh", "hmm", "hm", "er", "err", "ah", "aah",
    "mmm", "mm",
    # conjunctions / connectors that promise more
    "and", "or", "but", "so", "because", "than", "like",
    "aur", "ya", "ki", "kyunki", "matlab", "yaani",
    # articles / possessives / prepositions
    "the", "a", "an", "my", "his", "her", "their", "our", "your",
    "to", "of", "in", "on", "at", "with", "for", "from",
    "ka", "ke", "ko", "se", "wala", "wale", "woh", "wo",
}


def _sounds_unfinished(text: str) -> bool:
    """Does this transcript read like a thought still in flight?"""
    t = text.strip()
    if not t:
        return False
    if t.endswith(("?", "!")):
        return False                    # a question or exclamation is a whole turn
    if t.endswith(("...", "…", ",", "-", "—", ":")):
        return True
    words = re.sub(r"[^\w\s']", " ", t.lower()).split()
    return bool(words) and words[-1] in _DANGLING_WORDS


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
        on_state: Callable[[str], None] | None = None,
    ):
        self._stt = stt
        self._tts = tts
        self._gate = gate or wake.Always()
        self._hints = hints
        self._follow_up = follow_up_ms / 1000
        self._show_timings = show_timings
        # Tells the desktop what the ears are doing ("ready", "hearing",
        # "speaking", "paused") — the tray icon's colour is this callback.
        self._on_state = on_state or (lambda s: None)

        self._stream = stream or audio.FrameStream()
        self._frames = self._stream.frames()
        # A brief seed so the very first thing said is judged against this room
        # rather than a default. Only a seed: the endpointer keeps adjusting from
        # non-speech frames, so this value stops being the operative one within a
        # fraction of a second.
        seed = audio.calibrate_noise_floor(self._frames)
        self._endpointer = audio.Endpointer(min_peak=seed)
        self._listen_until = 0.0        # follow-up window; past = gate is armed
        self.transcribed_seconds = 0.0  # audio actually sent for transcription
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
            # A pause (the tray's hard mute) collapses the follow-up window
            # too: pressing it mid-conversation must take effect now, not
            # after the window happens to expire.
            armed = gated and (_mic_paused() or time.monotonic() > self._listen_until)

            if armed:
                if not self._await_wake():
                    return None
                self._on_state("hearing")
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

            text = self._transcribe(utterance)
            if text:
                text = self._hear_the_rest(utterance, text)
                print(f"you  > {text}")
                return text
            # Nothing intelligible — go back to waiting rather than bothering the
            # brain with an empty turn.
            self._gate.reset()

    def _transcribe(self, pcm: bytes) -> str | None:
        # Running total of audio actually handed to the recogniser — with
        # hosted ears this is exactly what gets billed, and being able to see
        # it is how the user trusts that the gate holds.
        self.transcribed_seconds += len(pcm) / (audio.SAMPLE_RATE * audio.SAMPLE_WIDTH)
        with self.turn.stage("stt"):
            hints = self._hints() if self._hints else None
            return self._stt.transcribe(pcm, audio.SAMPLE_RATE, hints=hints)

    def _hear_the_rest(self, pcm: bytes, text: str) -> str:
        """Wait out thinking pauses instead of cutting the speaker off.

        Silence ends a turn, but "…his name was ummm" followed by silence is
        someone *reaching for a word*, not someone finished. Silence cannot
        tell those apart; the words can. While the transcript ends mid-thought,
        keep the mic open for a generous pause, splice the continuation onto
        the same clip, and transcribe the whole utterance again so the
        recogniser hears one sentence rather than two fragments — the join is
        exactly where the name lands.
        """
        for _ in range(_MAX_CONTINUATIONS):
            if not _sounds_unfinished(text):
                break
            more = self._endpointer.collect_one(
                self._frames, onset_timeout_ms=_THINKING_MS
            )
            if not more:
                break                   # they really were done (or the mic died)
            pcm += more
            text = self._transcribe(pcm) or text
        return text

    def _await_wake(self) -> bool:
        """Consume frames until the wake word fires. False if the mic died.

        The pause flag (the tray's hard mute) releases the microphone DEVICE,
        not just the gate: the recorder process exits and the OS's mic-in-use
        indicator goes out. A mute the OS still reports as "microphone in use"
        asks the user to trust our icon over their system's — they shouldn't
        have to, and they won't.
        """
        paused = _mic_paused()
        if paused:
            self._stream.suspend()
        self._on_state("paused" if paused else "ready")
        frames_seen = 0
        while True:
            if paused:
                time.sleep(0.5)
                if _mic_paused():
                    continue
                paused = False
                self._stream.resume()
                self._on_state("ready")
            frame = next(self._frames, None)
            if frame is None:
                return False                    # the mic actually died
            # Idle is when most of the day's audio goes past, so it is also when
            # the noise floor must keep learning. Otherwise music that started
            # while Mantrin was dormant would meet a stale, quiet-room gate the
            # moment the wake word fires.
            self._endpointer.observe(frame)
            frames_seen += 1
            if frames_seen % 32 == 0 and _mic_paused():   # ~once a second
                paused = True
                self._stream.suspend()
                self._on_state("paused")
                continue
            if self._gate.open(frame):
                self._gate.reset()
                return True

    # ----------------------------------------------------------------- out

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}\n")
        self._on_state("speaking")
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
        self._on_state("hearing")       # the follow-up window: mic is hot
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
        if gated:
            # The wake model still holds the last couple of seconds it heard —
            # which, right after a wake-word turn, is the wake word itself.
            # Fed its first fresh frame during playback it would fire on that
            # stale buffer and stop the reply at the first syllable. Playback
            # is a new acoustic scene; the model starts from silence.
            self._gate.reset()
        onset_needed = max(1, _BARGE_IN_ONSET_MS // audio.FRAME_MS)
        pending: collections.deque[int] = collections.deque(maxlen=onset_needed)
        own_voice = 0
        run = 0
        started = time.monotonic()
        blind_ms = _BARGE_IN_BLIND_EC_MS if audio.echo_cancelled() else _BARGE_IN_BLIND_MS

        for frame in self._frames:
            if playback.stopped or not playback.playing:
                return False
            peak = audio._peak(frame)

            if gated and self._gate.open(frame):
                playback.stop()
                self._gate.reset()
                print("(barge-in: wake word)", flush=True)
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
            # Deaf-to-energy start: the player's first frames are start-up
            # silence, so the own-voice bar is still set against a quiet room
            # exactly when Mantrin's opening word arrives — and the lagged
            # tracking loses that race every time. Until the bar has heard
            # real playback, only the wake word can interrupt.
            if run >= onset_needed and (time.monotonic() - started) * 1000 > blind_ms:
                playback.stop()
                print(f"(barge-in: voice — peak {peak} over bar {threshold}, "
                      f"own voice {own_voice})", flush=True)
                return True
        return False

    # --------------------------------------------------------------- close

    def close(self) -> None:
        if self.transcribed_seconds:
            m, s = divmod(int(self.transcribed_seconds), 60)
            spoken = f"{m}m {s}s" if m else f"{s}s"
            print(f"(speech transcribed this session: {spoken} of audio)", flush=True)
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
