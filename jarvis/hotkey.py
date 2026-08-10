"""The talk key — hold a key to talk, release it to get the answer.

The wake word answers "when may audio become text?" by listening. The talk
key answers it mechanically: while the key is down, Mantrin listens; the
release IS the endpoint. No voice-activity guessing, no trailing-silence
wait — the person says when they are done, to the millisecond.

Why this reads /dev/input rather than using desktop shortcuts: GNOME's
custom shortcuts fire a command on key-DOWN and never report the release,
so hold-to-talk cannot be built on them. The kernel reports both edges for
every key on every keyboard — including vendor extras like Lenovo's star
key, which are just keycodes here.

Reading /dev/input needs membership of the `input` group, and that
permission is honest about its size: a process that can read the keyboard
can see every key. Mantrin matches one keycode and drops everything else on
the floor — and this file stays small on purpose, so that claim can be
verified in one sitting.
"""

from __future__ import annotations

import os
import re
import select
import struct
import subprocess
import threading
import time
from pathlib import Path

from . import config

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
_EVENT = struct.Struct("llHHi")
_EV_KEY = 0x01
_KEY_UP, _KEY_DOWN = 0, 1                   # value 2 is autorepeat — ignored
_ENTER_CODES = {28, 96}                     # KEY_ENTER, KEY_KPENTER
# Keys that do nothing on their own while held — no character typed into the
# focused app, no autorepeat spam. Anything else works too, but leaks.
_SILENT_KEYS = {29, 42, 54, 56, 97, 100, 125, 126}   # ctrl/shift/alt/meta, both sides

_DEV = Path("/dev/input")
_SYS = Path("/sys/class/input")
_RESCAN_S = 5.0                             # how often to notice (un)plugged keyboards


def readable() -> bool:
    """Can this process read input devices at all? False means the user is
    not in the `input` group (or there are no devices)."""
    return any(os.access(p, os.R_OK) for p in _DEV.glob("event*"))


def _key_bits(event_name: str) -> int:
    """The device's key-capability bitmask — which keycodes it can emit.
    Zero for devices that have no keys (a touchpad's motion node, etc.)."""
    try:
        words = (_SYS / event_name / "device" / "capabilities" / "key").read_text().split()
    except OSError:
        return 0
    bits = 0
    for word in words:                      # most-significant word first
        bits = (bits << 64) | int(word, 16)
    return bits


def _device_name(event_name: str) -> str:
    try:
        return (_SYS / event_name / "device" / "name").read_text().strip()
    except OSError:
        return event_name


def _devices_with_key(code: int) -> list[Path]:
    """Only the devices that can physically emit this keycode get opened —
    not every input node on the machine."""
    return [p for p in sorted(_DEV.glob("event*"))
            if os.access(p, os.R_OK) and (_key_bits(p.name) >> code) & 1]


def key_name(code: int) -> str:
    """KEY_F10 instead of 68, when the kernel headers are around to say so."""
    header = Path("/usr/include/linux/input-event-codes.h")
    if header.exists():
        for line in header.read_text().splitlines():
            m = re.match(r"#define\s+(KEY_\w+)\s+(0x[0-9a-fA-F]+|\d+)\s*$", line)
            if m and int(m.group(2), 0) == code:
                return m.group(1)
    return f"key {code}"


class TalkKey:
    """Watches the keyboard for one keycode, from its own thread.

    `held` is the level (is the key down right now), `take_press()` is the
    edge (has a new press happened since last asked) — the voice loop polls
    the level to collect speech, playback watches the edge to be
    interruptible even by a press-and-hold that started mid-reply.
    """

    def __init__(self, code: int):
        self._code = code
        self._held = threading.Event()
        self._edge = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True, name="talk-key")  

    def start(self) -> "TalkKey":
        self._thread.start()
        return self

    @property
    def held(self) -> bool:
        return self._held.is_set()

    def take_press(self) -> bool:
        """True once per press — reading it consumes it."""
        if self._edge.is_set():
            self._edge.clear()
            return True
        return False

    def close(self) -> None:
        self._stop.set()

    def _watch(self) -> None:
        fds: dict[int, Path] = {}
        next_scan = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_scan:
                    next_scan = now + _RESCAN_S
                    current = set(_devices_with_key(self._code))
                    for fd, path in list(fds.items()):
                        if path not in current:
                            os.close(fd)
                            del fds[fd]
                    for path in current - set(fds.values()):
                        try:
                            fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
                        except OSError:
                            pass
                if not fds:
                    time.sleep(1.0)
                    continue
                ready, _, _ = select.select(list(fds), [], [], 1.0)
                for fd in ready:
                    try:
                        data = os.read(fd, _EVENT.size * 64)
                    except OSError:         # unplugged mid-read
                        os.close(fd)
                        fds.pop(fd, None)
                        continue
                    for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                        _, _, etype, code, value = _EVENT.unpack_from(data, off)
                        if etype != _EV_KEY or code != self._code:
                            continue
                        if value == _KEY_DOWN:
                            self._held.set()
                            self._edge.set()
                        elif value == _KEY_UP:
                            self._held.clear()
        finally:
            for fd in fds:
                os.close(fd)


# ------------------------------------------------------------------ setup

def capture(timeout_s: float = 30.0) -> tuple[int, str, str] | None:
    """Wait for the user to press their chosen key.

    Returns (keycode, key name, device name), or None on timeout. Opens
    every key-capable device, because vendor keys often live on their own
    little input device rather than the main keyboard.
    """
    paths = [p for p in sorted(_DEV.glob("event*"))
             if os.access(p, os.R_OK) and _key_bits(p.name)]
    fds = {}
    for p in paths:
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
        except OSError:
            pass
    if not fds:
        return None
    try:
        # Drain the Enter that submitted the prompt, and anything else pending.
        drain_until = time.monotonic() + 0.3
        while time.monotonic() < drain_until:
            ready, _, _ = select.select(list(fds), [], [], 0.05)
            for fd in ready:
                try:
                    os.read(fd, _EVENT.size * 64)
                except OSError:
                    pass

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ready, _, _ = select.select(list(fds), [], [], 0.5)
            for fd in ready:
                try:
                    data = os.read(fd, _EVENT.size * 64)
                except OSError:
                    continue
                for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                    _, _, etype, code, value = _EVENT.unpack_from(data, off)
                    if etype != _EV_KEY or value != _KEY_DOWN:
                        continue
                    if code in _ENTER_CODES:
                        print("  (not Enter — it fires every time you submit a "
                              "prompt. Pick another key.)")
                        continue
                    return code, key_name(code), _device_name(fds[fd].name)
        return None
    finally:
        for fd in fds:
            os.close(fd)


def _offer_input_group() -> None:
    """The one permission this feature needs, asked for honestly."""
    import getpass

    print("""
  Reading the keyboard needs your user in the `input` group.

  Honest note about the size of that permission: a process that can read
  /dev/input can see every key you press. Mantrin watches for exactly one
  keycode and ignores the rest — jarvis/hotkey.py is a single short file,
  so you can verify that yourself. If that trade isn't for you, skip this
  and keep the wake word.""")
    answer = input("\n  Add you to the `input` group now? (runs sudo) [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("  Skipped. You can do it later: sudo usermod -aG input $USER")
        return
    result = subprocess.run(["sudo", "usermod", "-aG", "input", getpass.getuser()])
    if result.returncode == 0:
        print("\n  Done — but group membership only applies to NEW logins.")
        print("  Log out, log back in, then run `mantrin set-key` again.")
    else:
        print("  (sudo failed — run it yourself: sudo usermod -aG input $USER)")


def _choose_trigger(current: str | None) -> str:
    options = [
        ("both", "Wake word AND talk key — say it or hold it, both work"),
        ("key", "Talk key only — the mic stays fully OFF (OS light out) except while held"),
        ("wake", "Wake word only — keep the key saved but unused"),
    ]
    print("\n  When should Mantrin listen?")
    keys = [k for k, _ in options]
    default = keys.index(current) + 1 if current in keys else 1
    for i, (_, label) in enumerate(options, 1):
        print(f"    {i}. {label}")
    while True:
        answer = input(f"  Pick 1-{len(options)} [{default}]: ").strip()
        if not answer:
            return keys[default - 1]
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return keys[int(answer) - 1]
        if answer in keys:
            return answer
        print("  Not one of the options.")


def capture_into(settings: dict) -> bool:
    """The shared capture flow: permission, press, mode. Mutates `settings`
    and returns True when a key was chosen. Used by both `mantrin set-key`
    and the setup wizard."""
    if not readable():
        _offer_input_group()
        return False
    print("\n  Press the key you want to hold while talking (30s, Ctrl+C to cancel).")
    print("  Right Ctrl is the best pick: it stays down as long as you hold it")
    print("  and types nothing into whatever app has focus. Vendor keys (star,")
    print("  media) often fire once instead of holding — firmware's choice, not ours…")
    got = capture()
    if got is None:
        print("  (no key seen — nothing changed)")
        return False
    code, name, device = got
    print(f"  Got it: {name} on “{device}”.")
    if code not in _SILENT_KEYS:
        print("  (heads-up: while held, this key will still type or act in the")
        print("   focused app — modifier keys like Right Ctrl don't. Re-run")
        print("   `mantrin set-key` any time to switch.)")
    settings["talk_key"] = code
    settings["talk_key_name"] = name
    settings["trigger"] = _choose_trigger(settings.get("trigger"))
    return True


def offer_in_wizard(settings: dict) -> None:
    """One optional question inside `mantrin setup`."""
    print("\n  Push-to-talk (optional)")
    print("    Hold a key to talk — no wake word needed, and the release ends")
    print("    the turn instantly instead of waiting out your silence.")
    answer = input("  Set a talk key now? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        capture_into(settings)


def set_key() -> int:
    """`mantrin set-key` — choose or change the talk key."""
    try:
        settings = config.load_settings()
        current = settings.get("talk_key")
        if current:
            print(f"Current talk key: {settings.get('talk_key_name') or f'key {current}'}"
                  f" (trigger: {settings.get('trigger') or 'both'})")
        if not capture_into(settings):
            return 1
        path = config.save_settings(settings)
        print(f"\nSaved to {path}.")
        if _daemon_running():
            print("Restarting Mantrin so it takes effect…")
            from . import service
            return service.restart()
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled — nothing changed.")
        return 1


def _daemon_running() -> bool:
    import socket

    if not config.SOCKET_FILE.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(str(config.SOCKET_FILE))
        return True
    except OSError:
        return False
    finally:
        s.close()
