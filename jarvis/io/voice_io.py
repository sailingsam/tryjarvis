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

**The talk key (push-to-talk).** Hold the key and Mantrin listens; the release
IS the endpoint — no voice-activity guessing, no trailing-silence wait, and a
press always interrupts playback. In key-only trigger mode the microphone
device is fully released between presses, so the OS mic light burning is
exactly the time Mantrin could hear anything.
"""

from __future__ import annotations

import collections
import queue
import re
import threading
import time
from typing import Callable

from .. import audio, config, timings, wake
from ..providers.tts import speakable


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

# A talk-key utterance shorter than this is an accidental tap, not speech —
# transcribing 60ms of key-clack would answer noise.
_MIN_PTT_MS = 250

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


# A sentence boundary worth speaking at: end punctuation + whitespace, or a
# paragraph break. Short fragments wait for more text — "Ok." alone isn't
# worth spinning the synthesiser for, and it smooths the prosody.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_MIN_SENTENCE_CHARS = 24


class _StreamSpeaker:
    """Speaks a reply while it is still being generated.

    The whole latency trick in one object: the brain streams text deltas in
    via `feed()`, complete sentences go to the synthesiser one at a time,
    and their audio feeds ONE continuous playback — so Mantrin starts
    talking after the first sentence exists, typically while the model is
    still writing the third. Barge-in watches the same playback from its
    own thread; a stop drops every sentence still queued.
    """

    def __init__(self, io: "VoiceIO"):
        self._io = io
        self._tts = io._tts
        self._buf = ""
        self._q: queue.Queue | None = None
        self._playback: audio.Playback | None = None
        self._watcher: threading.Thread | None = None
        self._started = time.monotonic()
        self.spoke = False              # any audio at all this turn?
        self.interrupted = False
        self.first_audio_ms: float | None = None

    # Called from the brain's thread, delta by delta.
    def feed(self, delta: str) -> None:
        if self.interrupted or not delta:
            return
        self._buf += delta
        while True:
            cut = None
            for m in _SENTENCE_END.finditer(self._buf):
                if m.start() >= _MIN_SENTENCE_CHARS:
                    cut = m
                    break
            if cut is None:
                return
            sentence, self._buf = self._buf[:cut.start()], self._buf[cut.end():]
            self._say(sentence)

    def _say(self, sentence: str) -> None:
        text = speakable(sentence)
        if not text:
            return
        if self._playback is None:
            self._q = queue.Queue()
            self._io._on_state("speaking")
            self._playback = audio.play_stream(
                self._pcm(self._q), sample_rate=self._tts.sample_rate,
                on_start=self._mark_first_audio,
            )
            self._watcher = threading.Thread(target=self._watch, daemon=True,
                                             name="stream-barge-in")
            self._watcher.start()
        self.spoke = True
        self._q.put(text)

    def _pcm(self, q: queue.Queue):
        while True:
            sentence = q.get()
            if sentence is None:
                return
            yield from self._tts.stream(sentence)

    def _mark_first_audio(self) -> None:
        if self.first_audio_ms is None:
            self.first_audio_ms = (time.monotonic() - self._started) * 1000

    def _watch(self) -> None:
        if self._io._watch_for_interruption(self._playback):
            self.interrupted = True
            self._buf = ""
            if self._q is not None:
                self._q.put(None)       # unblock the synth generator

    # ------------------------------------------------------------- winding up

    def close(self) -> None:
        """Flush the tail, let the playback drain, join the watcher."""
        if self._buf.strip() and not self.interrupted:
            self._say(self._buf)
        self._buf = ""
        if self._q is not None:
            self._q.put(None)
        if self._playback is not None:
            self._playback.wait(timeout=120)
            if self._watcher is not None:
                self._watcher.join(timeout=2)
            self._playback = None

    def abandon(self) -> None:
        """The turn died (an exception mid-think): stop making sound now."""
        self.interrupted = True
        if self._playback is not None:
            self._playback.stop()
            self._playback = None
        if self._q is not None:
            self._q.put(None)


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
        ptt=None,
        trigger: str = "wake",
    ):
        self._stt = stt
        self._tts = tts
        self._gate = gate or wake.Always()
        # The talk key (a hotkey.TalkKey, or None). `trigger` says what opens
        # the mic: "wake", "key", or "both". Key-only is the fully-released
        # mode — between presses the recorder process does not exist.
        self._ptt = ptt
        self._trigger = trigger if ptt is not None else "wake"
        self._hints = hints
        # Key-only mode has no hot follow-up window: the mic is released the
        # moment the key comes up, and a follow-up is just another press.
        self._follow_up = 0 if self._trigger == "key" else follow_up_ms / 1000
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
        self._active_speaker: _StreamSpeaker | None = None
        self.transcribed_seconds = 0.0  # audio actually sent for transcription
        self.turn = timings.Turn(enabled=show_timings)

        phrase = getattr(self._gate, "_phrase", "")
        gated = getattr(self._gate, "is_gate", False)
        if self._trigger == "key":
            detail = ", hold the talk key"
        else:
            detail = f", say “{phrase.replace('_', ' ')}”" if gated and phrase else ", no wake word"
            if self._ptt is not None:
                detail += " or hold the talk key"
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
            if self._trigger == "key":
                text = self._key_mode_turn()
                if text is None:
                    return None
                if not text:
                    continue
                return text

            # In "both" mode a held key beats every other wait: whoever is
            # holding it has already decided they are talking to Mantrin.
            if self._ptt is not None and self._ptt.held and not _mic_paused():
                text = self._ptt_turn()
                if text is None:
                    return None
                if not text:
                    continue
                return text

            armed = gated and (_mic_paused() or time.monotonic() > self._listen_until)
            session = None

            if armed:
                got = self._await_wake()
                if not got:
                    return None
                if got == "ptt":
                    continue            # the loop top picks up the held key
                self._on_state("hearing")
                session = self._open_session()
                # Wait for the command rather than assuming it is already
                # underway. People say the wake word both ways — "hey jarvis,
                # remind me…" in one breath, and "hey jarvis" … pause …
                # "remind me". Requiring an onset handles both, because the
                # onset is only 120ms and the pre-roll keeps the 300ms before
                # it, so nothing is clipped in the run-on case. Assuming
                # speech had begun broke the pause case outright: it collected
                # silence, transcribed nothing, and went back to sleep.
                utterance = self._endpointer.collect_one(
                    self._tapped(session), onset_timeout_ms=_COMMAND_GRACE_MS,
                    interrupt=self._key_waiting,
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
                session = self._open_session()
                utterance = self._endpointer.collect_one(
                    self._tapped(session), onset_timeout_ms=remaining_ms,
                    interrupt=self._key_waiting,
                )
            else:
                utterance = self._endpointer.collect_one(
                    self._frames, interrupt=self._key_waiting
                )

            if utterance is None:
                if session is not None:
                    session.abort()
                return None
            if not utterance:
                # Silence: after the wake word, or for the rest of the follow-up
                # window. Re-arm rather than answering nothing — the next pass
                # through the loop finds the window expired and waits for the
                # wake word again.
                if session is not None:
                    session.abort()
                self._gate.reset()
                continue
            # What the recogniser is billed for starts at the onset; the wait
            # before it is idle time, not latency. The endpointer's cost per
            # turn is its trailing-silence window — fixed by design, but shown
            # so the total reads honestly.
            self.turn.mark("vad", self._endpointer.silence_ms)

            text = self._finish_transcription(utterance, session)
            if text:
                text = self._hear_the_rest(utterance, text)
                print(f"you  > {text}")
                return text
            # Nothing intelligible — go back to waiting rather than bothering the
            # brain with an empty turn.
            self._gate.reset()

    def _open_session(self):
        """A live streaming-STT session, when the provider has one. Audio goes
        up the wire while the person is still talking, so recognition time
        hides inside the speaking time instead of following it — the same
        trick the talk key uses, now for wake-word turns too."""
        maker = getattr(self._stt, "stream_session", None)
        if maker is None:
            return None
        try:
            return maker(audio.SAMPLE_RATE,
                         hints=self._hints() if self._hints else None)
        except Exception:                   # noqa: BLE001 — batch path remains
            return None

    def _tapped(self, session):
        """The frame stream, with a copy of every frame sent up the session."""
        if session is None:
            return self._frames

        def tap():
            for frame in self._frames:
                session.send(frame)
                yield frame

        return tap()

    def _finish_transcription(self, utterance: bytes, session) -> str | None:
        """The transcript — from the live session when there is one (only the
        tail is left to wait for), else the plain upload. The full audio is
        always in hand, so a dead socket costs a retry, never the words."""
        if session is not None:
            with self.turn.stage("stt"):
                text = session.finish()
            if text is not None:
                self.transcribed_seconds += len(utterance) / (audio.SAMPLE_RATE * audio.SAMPLE_WIDTH)
                return text
        return self._transcribe(utterance)

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

    # ------------------------------------------------------------- talk key

    def _key_waiting(self) -> bool:
        """Passed into collect_one as `interrupt`: a held talk key wins over
        any open-ended wait for speech."""
        return self._ptt is not None and self._ptt.held and not _mic_paused()

    def _collect_held(self) -> tuple[bytes | None, object | None]:
        """Record until the key comes up. The release IS the endpoint — no
        VAD, no trailing-silence wait; the user says when the turn is over,
        to the millisecond.

        With streaming ears (Grok's websocket), every frame also goes up the
        wire AS it is recorded — recognition happens inside the speaking
        time, so on release the transcript is already nearly done. The full
        audio is kept regardless: if the socket dies, plain transcribe()
        still has everything.
        """
        session = self._open_session()
        collected: list[bytes] = []
        while self._ptt.held:
            frame = next(self._frames, None)
            if frame is None:
                if session:
                    session.abort()
                return None, None
            collected.append(frame)
            if session is not None:
                session.send(frame)
        return b"".join(collected), session

    def _ptt_turn(self) -> str | None:
        """One held-key exchange in "both" mode — the stream is already live.
        None means the mic died; "" means nothing usable was said."""
        self._ptt.take_press()
        self._on_state("hearing")
        self._stream.drain()            # the press marks now; backlog is noise
        utterance, session = self._collect_held()
        if utterance is None:
            return None
        return self._transcribe_held(utterance, session)

    def _key_mode_turn(self) -> str | None:
        """One full cycle in key-only mode: wait released, record held.

        Between presses the recorder process does not exist, so the OS mic
        light is dark — the light burning is exactly the time Mantrin could
        hear anything. The ~100ms the device takes to reopen sits inside the
        human gap between pressing a key and starting to speak.
        """
        self._stream.suspend()
        paused = _mic_paused()
        self._on_state("paused" if paused else "ready")
        while not self._ptt.held or _mic_paused():
            time.sleep(0.03)
            # The mic is already released either way, but the icon must tell
            # the truth about WHY: muted means even the key is ignored.
            if _mic_paused() != paused:
                paused = not paused
                self._on_state("paused" if paused else "ready")
        self._ptt.take_press()
        self._stream.resume()
        self._on_state("hearing")
        utterance, session = self._collect_held()
        self._stream.suspend()          # released again before we even transcribe
        if utterance is None:
            return None
        return self._transcribe_held(utterance, session)

    def _transcribe_held(self, utterance: bytes, session=None) -> str:
        min_bytes = _MIN_PTT_MS * audio.SAMPLE_RATE * audio.SAMPLE_WIDTH // 1000
        if len(utterance) < min_bytes:
            if session is not None:
                session.abort()
            return ""                   # an accidental tap, not speech
        text = self._finish_transcription(utterance, session) or ""
        if text:
            print(f"you  > {text}")
        return text

    def _await_wake(self) -> str | None:
        """Consume frames until the wake word fires ("wake") or the talk key
        goes down ("ptt"). None if the mic died.

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
                return None                     # the mic actually died
            if self._ptt is not None and self._ptt.held:
                return "ptt"
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
                return "wake"

    # ----------------------------------------------------------------- out

    def begin_reply(self) -> "_StreamSpeaker | None":
        """A live speaker for the turn about to be generated, or None when
        streaming isn't possible (a voice that can't stream, or turned off)."""
        if not config.STREAM_REPLIES or not hasattr(self._tts, "stream"):
            return None
        self._active_speaker = _StreamSpeaker(self)
        return self._active_speaker

    def end_reply(self, speaker: "_StreamSpeaker | None", reply: str) -> None:
        """Wind the streamed turn down — or fall back to the plain path if
        nothing was actually spoken (no speaker, or the reply held no
        speakable sentence)."""
        self._active_speaker = None
        if speaker is None or (not speaker.spoke and not speaker._buf.strip()):
            self.speak(reply)
            return
        print(f"jarvis> {reply}\n")
        speaker.close()
        if speaker.first_audio_ms is not None:
            self.turn.mark("tts", speaker.first_audio_ms)
        if speaker.interrupted:
            print("(interrupted)", flush=True)
        self._after_turn()

    def abort_reply(self, speaker: "_StreamSpeaker | None") -> None:
        """The turn blew up mid-generation — cut any sound immediately."""
        self._active_speaker = None
        if speaker is not None:
            speaker.abandon()

    def speak(self, text: str) -> None:
        # Mid-stream speech (a tool's confirmation question) must not overlap
        # the sentences already playing: finish those first, then speak this
        # on its own playback as usual.
        active = self._active_speaker
        if active is not None:
            self._active_speaker = None
            active.close()
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
        if self._ptt is not None:
            # A press consumed while Mantrin was thinking is stale — but a key
            # still HELD is someone waiting to talk, and that outranks the reply.
            self._ptt.take_press()
            if self._trigger == "key":
                # Key-only mode speaks with the stream suspended (the mic is
                # released), so there are no frames to read: the key is the
                # only interrupter, and the only one needed.
                while playback.playing and not playback.stopped:
                    if self._ptt.take_press() or self._ptt.held:
                        playback.stop()
                        print("(barge-in: talk key)", flush=True)
                        return True
                    time.sleep(0.03)
                return False
        onset_needed = max(1, _BARGE_IN_ONSET_MS // audio.FRAME_MS)
        pending: collections.deque[int] = collections.deque(maxlen=onset_needed)
        own_voice = 0
        run = 0
        started = time.monotonic()
        blind_ms = _BARGE_IN_BLIND_EC_MS if audio.echo_cancelled() else _BARGE_IN_BLIND_MS

        for frame in self._frames:
            if playback.stopped or not playback.playing:
                return False
            if self._ptt is not None and (self._ptt.take_press() or self._ptt.held):
                playback.stop()
                print("(barge-in: talk key)", flush=True)
                return True
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
