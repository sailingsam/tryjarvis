"""Microphone, endpointing and playback — shared by every voice provider.

This is deliberately *not* swappable. Capturing audio and deciding when someone
stopped talking is not the product; it is plumbing that every provider needs to
work identically. Providers get handed finished audio and return text (STT), or
get handed text and return audio (TTS). Nothing here knows who they are.

Two things matter about the design:

**One long-running recorder.** The mic process starts once and streams forever.
Spawning a recorder per utterance costs 100-200ms of startup, which eats the
first syllable — and an always-on assistant needs a continuous stream anyway to
run a wake word over it.

**Pre-roll.** By the time the VAD is confident you are speaking, the onset is
already a few frames in the past. A small ring buffer keeps those frames so the
audio we send starts at the actual beginning of the word, not part-way through.

Backends are subprocesses (`arecord`/`aplay`, present on any Linux with ALSA or
PipeWire) rather than a compiled binding. `sounddevice` needs PortAudio as a
system library, which is one more thing for a user to install before Mantrin
will start — see requirements-voice.txt.
"""

from __future__ import annotations

import collections
import shutil
import subprocess
import threading
import time
from typing import Iterable, Iterator

# 16kHz mono s16 throughout. Whisper resamples to 16k anyway, webrtcvad only
# accepts 8/16/32/48k, and every hosted STT takes it — so there is no reason to
# capture higher and pay for the bytes.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2                    # bytes per sample (s16)
FRAME_MS = 30                       # webrtcvad accepts 10, 20 or 30 only
FRAME_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * FRAME_MS // 1000


class AudioUnavailable(RuntimeError):
    """No way to reach the microphone or speaker on this machine."""


# ---------------------------------------------------------------- capture


def _record_command() -> list[str]:
    if shutil.which("arecord"):
        return ["arecord", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(SAMPLE_RATE), "-c", "1"]
    if shutil.which("pw-record"):
        return ["pw-record", "--format=s16", f"--rate={SAMPLE_RATE}",
                "--channels=1", "-"]
    raise AudioUnavailable(
        "No recorder found. Install alsa-utils (arecord) or pipewire-utils "
        "(pw-record)."
    )


class Mic:
    """A continuous 16kHz mono stream, yielded as fixed-size frames.

    Held open for the life of the process. `frames()` blocks; it stops when
    `close()` is called or the recorder dies.
    """

    def __init__(self):
        self._proc = subprocess.Popen(
            _record_command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._closed = False

    def frames(self) -> Iterator[bytes]:
        # An unbuffered pipe returns whatever bytes happen to be available, so a
        # single read() is usually a *partial* frame. Accumulate to an exact
        # frame or the VAD gets ragged input and the stream ends early.
        assert self._proc.stdout is not None
        buf = bytearray()
        while not self._closed:
            chunk = self._proc.stdout.read(FRAME_BYTES - len(buf))
            if not chunk:
                break                       # recorder exited or stream closed
            buf += chunk
            if len(buf) == FRAME_BYTES:
                yield bytes(buf)
                buf.clear()

    def close(self) -> None:
        self._closed = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def __enter__(self) -> "Mic":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FrameStream:
    """The microphone, read continuously, with stale audio thrown away.

    An always-on assistant cannot simply stop reading the mic while it thinks or
    talks. The recorder keeps running, its pipe fills, and whatever accumulated
    gets replayed the moment reading resumes — so Mantrin would transcribe its
    own reply, or answer a question from a minute ago. A reader thread keeps
    draining the device and holds only the most recent moment of audio; anything
    older is dropped, because in conversation old audio is not backlog, it is
    noise.

    `drain()` is what makes barge-in safe: after speaking, discard everything the
    mic picked up of Mantrin's own voice before listening again.
    """

    def __init__(self, mic: "Mic | None" = None, *, keep_ms: int = 3_000):
        self._mic = mic or Mic()
        # A bounded buffer *is* the policy: once it is full the oldest frame is
        # dropped, so a slow consumer falls behind by a bounded amount instead of
        # accumulating a backlog it would later mistake for the present.
        self._queue: collections.deque[bytes] = collections.deque(
            maxlen=max(1, keep_ms // FRAME_MS)
        )
        self._cv = threading.Condition()
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._pump, daemon=True, name="mic-reader")
        self._reader.start()

    def _pump(self) -> None:
        try:
            for frame in self._mic.frames():
                if self._closed.is_set():
                    break
                with self._cv:
                    self._queue.append(frame)
                    self._cv.notify()
        finally:
            self._closed.set()
            with self._cv:
                self._cv.notify_all()       # release any waiting consumer

    def frames(self) -> Iterator[bytes]:
        """Yield frames as they arrive, forever, oldest first."""
        while True:
            with self._cv:
                while not self._queue and not self._closed.is_set():
                    self._cv.wait(timeout=0.5)
                if not self._queue:
                    if self._closed.is_set():
                        return
                    continue
                frame = self._queue.popleft()
            yield frame

    def drain(self) -> int:
        """Discard everything buffered. Returns how many frames were dropped."""
        with self._cv:
            dropped = len(self._queue)
            self._queue.clear()
            return dropped

    def close(self) -> None:
        self._closed.set()
        self._mic.close()

    def __enter__(self) -> "FrameStream":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ------------------------------------------------------------ endpointing


def _peak(frame: bytes) -> int:
    """Loudest sample in a frame, 0-32767. Used as a cheap energy gate next to
    the VAD — webrtcvad is tuned for speech-vs-noise, not speech-vs-quiet, so a
    distant TV can read as voiced."""
    peak = 0
    for i in range(0, len(frame) - 1, 2):
        sample = frame[i] | (frame[i + 1] << 8)
        if sample >= 0x8000:
            sample -= 0x10000
        peak = max(peak, abs(sample))
    return peak


CALIBRATION_MS = 1_000
MIN_PEAK_FLOOR = 700
_FLOOR_MARGIN = 2.2             # how far above the background speech has to sit
_FLOOR_PERCENTILE = 0.9


class NoiseFloor:
    """The background level of the room, kept up to date as the room changes.

    A fixed threshold cannot work across machines — mic gain and rooms differ by
    more than an order of magnitude — and a *one-off* measurement at startup is
    just as wrong for something that runs all day. Music starts, a fan kicks in,
    someone shuts a window: a floor measured once is stale minutes later, leaving
    Mantrin either deaf or jumpy for the rest of the session.

    So the floor is learned continuously from frames the VAD considers non-speech.
    Music raises it, silence lowers it, and one slammed door does not set it for
    the day because it tracks a high percentile rather than the maximum.
    """

    def __init__(self, *, window_ms: int = 6_000, initial: int | None = None):
        self._recent: collections.deque[int] = collections.deque(
            maxlen=max(8, window_ms // FRAME_MS)
        )
        self._floor = max(MIN_PEAK_FLOOR, initial or MIN_PEAK_FLOOR)

    def observe(self, peak: int) -> None:
        """Record a frame that is known not to be speech."""
        self._recent.append(peak)
        if len(self._recent) >= 8:
            ranked = sorted(self._recent)
            index = min(len(ranked) - 1, int(len(ranked) * _FLOOR_PERCENTILE))
            self._floor = max(MIN_PEAK_FLOOR, int(ranked[index] * _FLOOR_MARGIN))

    @property
    def gate(self) -> int:
        return self._floor


def calibrate_noise_floor(frames: Iterable[bytes], *, ms: int = CALIBRATION_MS) -> int:
    """A starting value for the gate, so the first thing said is not missed.

    Only a seed — `NoiseFloor` takes over and keeps adjusting from there.
    """
    floor = NoiseFloor()
    for frame in _take(frames, max(1, ms // FRAME_MS)):
        floor.observe(_peak(frame))
    return floor.gate


def _take(frames: Iterable[bytes], n: int) -> list[bytes]:
    out = []
    for frame in frames:
        out.append(frame)
        if len(out) >= n:
            break
    return out


class Endpointer:
    """Turns a frame stream into whole utterances.

    There is no recording limit by design — you may speak for three seconds or
    three minutes, and the only thing that ends a turn is you stopping. The
    `max_ms` ceiling exists solely so a stuck VAD on constant noise cannot
    record forever; it is not a turn length.
    """

    def __init__(
        self,
        *,
        aggressiveness: int = 3,        # webrtcvad 0-3; 3 filters most non-speech
        silence_ms: int = 700,          # trailing quiet that means "I'm done"
        onset_ms: int = 120,            # speech this long before we believe it
        preroll_ms: int = 300,          # keep this much audio before the onset
        max_ms: int = 300_000,          # 5 min runaway guard, not a turn limit
        min_peak: int = MIN_PEAK_FLOOR,  # energy gate; see calibrate_noise_floor
    ):
        try:
            import webrtcvad
        except ImportError as e:                        # pragma: no cover
            raise AudioUnavailable(
                "webrtcvad is required for voice. pip install -r requirements-voice.txt"
            ) from e
        self._vad = webrtcvad.Vad(aggressiveness)
        self._silence_frames = max(1, silence_ms // FRAME_MS)
        self._onset_frames = max(1, onset_ms // FRAME_MS)
        self._preroll_frames = max(1, preroll_ms // FRAME_MS)
        self._max_frames = max_ms // FRAME_MS
        self._floor = NoiseFloor(initial=min_peak)

    @property
    def gate(self) -> int:
        """The energy threshold currently in force — moves with the room."""
        return self._floor.gate

    @property
    def silence_ms(self) -> int:
        """The trailing quiet that ends a turn — the endpointer's fixed cost."""
        return self._silence_frames * FRAME_MS

    def observe(self, frame: bytes) -> None:
        """Let the noise floor learn from a frame without collecting anything.
        Used while idling on the wake word, which is where most audio goes by."""
        self._voiced(frame)

    def _voiced(self, frame: bytes) -> bool:
        """Speech, by two independent opinions.

        webrtcvad alone called ~6% of frames in a quiet room speech, so an energy
        gate sits behind it. Frames the VAD rejects are exactly the sample of
        "whatever this room sounds like when nobody is talking to Mantrin", so
        they are what teaches the gate where the background is.
        """
        peak = _peak(frame)
        if not self._vad.is_speech(frame, SAMPLE_RATE):
            self._floor.observe(peak)
            return False
        return peak >= self._floor.gate

    def collect_one(self, frames: Iterable[bytes], *,
                    onset_timeout_ms: int | None = None) -> bytes | None:
        """Block until one utterance is complete, then return it.

        Taking a single utterance rather than a generator matters because the
        wake word has to read the same frames: one consumer at a time, handing
        the stream back and forth, instead of two iterators fighting over it.

        Returns `b""` if `onset_timeout_ms` passes with nobody speaking, and
        `None` only when the microphone stream ends. The caller needs to tell
        those apart: silence means go back to waiting, a dead stream means stop.
        """
        preroll: collections.deque[bytes] = collections.deque(maxlen=self._preroll_frames)
        collected: list[bytes] = []
        speaking = False
        voiced_run = 0
        silent_run = 0
        waited = 0
        patience = None if onset_timeout_ms is None else onset_timeout_ms // FRAME_MS

        for frame in frames:
            voiced = self._voiced(frame)

            if not speaking:
                preroll.append(frame)
                voiced_run = voiced_run + 1 if voiced else 0
                if voiced_run >= self._onset_frames:
                    speaking, silent_run = True, 0
                    collected = list(preroll)   # onset included, not clipped
                    preroll.clear()
                    continue
                waited += 1
                if patience is not None and waited >= patience:
                    return b""                  # nobody spoke
                continue

            collected.append(frame)
            silent_run = 0 if voiced else silent_run + 1

            if silent_run >= self._silence_frames or len(collected) >= self._max_frames:
                # Drop most of the trailing silence but leave a little, so the
                # last word does not sound cut off to the recogniser.
                keep = max(0, len(collected) - silent_run + self._onset_frames)
                return b"".join(collected[:keep]) or None
        return None                             # stream ended

    def utterances(self, frames: Iterable[bytes]) -> Iterator[bytes]:
        """Yield one audio blob per utterance, forever."""
        while True:
            utterance = self.collect_one(frames)
            if utterance is None:
                return
            if utterance:
                yield utterance

    def wait_for_speech(self, frames: Iterable[bytes], *, onset_frames: int | None = None) -> bool:
        """Block until someone starts talking. Used for barge-in, where we only
        need to know *that* speech began, not what was said. A stricter onset
        can be passed because the speaker is audible to the mic."""
        need = onset_frames or self._onset_frames
        run = 0
        for frame in frames:
            run = run + 1 if self._voiced(frame) else 0
            if run >= need:
                return True
        return False


# --------------------------------------------------------------- playback


def _play_command(sample_rate: int) -> list[str]:
    if shutil.which("aplay"):
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(sample_rate), "-c", "1"]
    if shutil.which("pw-play"):
        return ["pw-play", "--format=s16", f"--rate={sample_rate}",
                "--channels=1", "-"]
    raise AudioUnavailable(
        "No player found. Install alsa-utils (aplay) or pipewire-utils (pw-play)."
    )


def to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw s16 mono PCM in a WAV container. Hosted transcription APIs take
    a file upload, not a naked sample stream, and WAV is the one container all
    of them accept without a transcode."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def decode_to_pcm(data: bytes) -> tuple[bytes, int]:
    """Decode compressed audio (MP3, etc.) to (s16 mono PCM, sample_rate).

    Hosted voices default to MP3, which the ALSA/PipeWire players cannot take.
    Decoding in-process with miniaudio avoids making ffmpeg a hard requirement.
    """
    if data.startswith(b"RIFF"):
        # The container says its own rate; guessing instead plays chipmunk or
        # slow-motion audio, depending on which side the guess missed.
        return strip_wav_header(data), _wav_sample_rate(data)
    try:
        import miniaudio
    except ImportError as e:                   # pragma: no cover
        raise AudioUnavailable(
            "This voice returns compressed audio; miniaudio is needed to play "
            "it. pip install -r requirements-voice.txt"
        ) from e
    decoded = miniaudio.decode(
        data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1
    )
    return decoded.samples.tobytes(), decoded.sample_rate


def _wav_sample_rate(data: bytes) -> int:
    """The sample rate a WAV file declares for itself, or 0 if unreadable."""
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        pos += 8
        if cid == b"fmt " and pos + 8 <= len(data):
            return int.from_bytes(data[pos + 4:pos + 8], "little")
        pos += size + (size & 1)
    return 0


def strip_wav_header(chunk: bytes) -> bytes:
    """Return the PCM payload of a WAV chunk. Hosted voices often stream WAV,
    whose header only appears on the first chunk; the player wants raw frames."""
    if not chunk.startswith(b"RIFF"):
        return chunk
    pos = 12
    while pos + 8 <= len(chunk):
        cid = chunk[pos:pos + 4]
        size = int.from_bytes(chunk[pos + 4:pos + 8], "little")
        pos += 8
        if cid == b"data":
            return chunk[pos:]
        pos += size + (size & 1)
    return b""


class Playback:
    """Audio being spoken right now. `stop()` cuts it off mid-word — that is
    what makes interrupting Mantrin feel like interrupting a person."""

    def __init__(self, sample_rate: int):
        self._proc = subprocess.Popen(
            _play_command(sample_rate), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Deliberately lock-free. The player's pipe holds only a few hundred
        # milliseconds of audio, so a synthesiser that outruns the speaker sits
        # blocked inside write(). If stop() needed the same lock, interrupting
        # would have to wait for that write to drain — which is precisely the
        # moment interruption has to be instant. Instead only the pump thread
        # ever writes, and stop() kills the player out from under it.
        self._stop_requested = threading.Event()
        self._fed_everything = threading.Event()

    def feed(self, pcm: bytes) -> bool:
        """Push audio to the speaker. False means playback ended (or was cut)."""
        if self._stop_requested.is_set():
            return False
        stdin = self._proc.stdin
        if stdin is None:
            return False
        try:
            stdin.write(pcm)
            stdin.flush()
            return True
        except (BrokenPipeError, ValueError, OSError):
            return False        # player gone, or stop() closed the pipe under us

    def stop(self) -> None:
        """Cut playback off immediately, mid-word."""
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        # Terminate before closing stdin: killing the player is what unblocks a
        # pump thread already stuck writing into a full pipe.
        if self._proc.poll() is None:
            self._proc.terminate()
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
        self._fed_everything.set()

    def done_feeding(self) -> None:
        """No more audio is coming; let the player drain and exit."""
        if not self._stop_requested.is_set():
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass
        self._fed_everything.set()

    @property
    def stopped(self) -> bool:
        return self._stop_requested.is_set()

    @property
    def playing(self) -> bool:
        """True while the player is still alive with audio to render."""
        return not self._stop_requested.is_set() and self._proc.poll() is None

    def wait(self, timeout: float | None = None) -> None:
        """Block until everything queued has actually been heard."""
        deadline = None if timeout is None else time.monotonic() + timeout
        self._fed_everything.wait(timeout)
        remaining = 300.0 if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            self._proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:      # pragma: no cover
            self._proc.kill()


def play_stream(chunks: Iterable[bytes], *, sample_rate: int,
                on_start=None) -> Playback:
    """Start playing PCM chunks as they arrive; return at once.

    Returning immediately is what makes interruption possible: the caller gets a
    live handle and can keep watching the microphone while Mantrin talks, then
    `stop()` the moment the user cuts in. Feeding happens on a background
    thread, so a slow synthesiser never blocks that watch.

    Streaming rather than buffering is also the whole latency game for speech:
    first audio can reach the speaker in ~100-300ms instead of after the entire
    reply has been synthesised.
    """
    playback = Playback(sample_rate)

    def pump() -> None:
        first = True
        try:
            for chunk in chunks:
                if playback.stopped:
                    break
                if not chunk:
                    continue
                if first:
                    chunk, first = strip_wav_header(chunk), False
                    if on_start:
                        on_start()
                if not playback.feed(chunk):
                    break
        finally:
            playback.done_feeding()

    threading.Thread(target=pump, daemon=True, name="tts-pump").start()
    return playback


def probe() -> str | None:
    """Return None if audio works, else a human-readable reason it doesn't.
    Called by `mantrin setup` and at daemon start so failures name themselves."""
    try:
        _record_command()
        _play_command(SAMPLE_RATE)
    except AudioUnavailable as e:
        return str(e)
    try:
        import webrtcvad  # noqa: F401
    except ImportError:
        return ("webrtcvad is not installed — voice needs it for endpointing. "
                "pip install -r requirements-voice.txt")
    # Reading the mic blocks, so a device that opens but never delivers audio
    # would hang here forever. Read on a thread and give up after a few seconds.
    result: list[str | None] = []
    try:
        mic = Mic()
    except Exception as e:                   # noqa: BLE001 — reported, not raised
        return f"Microphone could not be opened: {e}"

    def _read_one() -> None:
        try:
            for _ in mic.frames():
                result.append(None)
                return
            result.append("Microphone stream closed immediately.")
        except Exception as e:               # noqa: BLE001
            result.append(f"Microphone read failed: {e}")

    reader = threading.Thread(target=_read_one, daemon=True)
    reader.start()
    reader.join(timeout=4)
    mic.close()
    if not result:
        return "Microphone opened but produced no audio within 4s."
    return result[0]
