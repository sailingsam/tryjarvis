"""The tray icon — how you know Mantrin is there without opening a terminal.

One glance at the top bar answers the only questions that matter about an
always-on microphone:

    green   ready — listening for the wake word, nothing being transcribed
    blue    in conversation — hearing you, thinking, or speaking
    yellow  starting up (models and connections take a moment after login)
    red     something is wrong — mic missing, provider down, daemon crashed
    grey    stopped, or the microphone is paused

The menu carries the one control that must never be more than a click away:
**Pause microphone** — a hard mute that ignores even the wake word until
turned back on (it drops a flag file the voice loop checks; no protocol).

This process is deliberately separate from the daemon. The daemon is a systemd
service that may outlive any desktop session; this is a desktop ornament that
may be killed freely. They meet at two files: `state.json` (daemon writes,
tray reads) and `mic-paused` (tray writes, daemon reads).

It also deliberately uses the SYSTEM python's GTK bindings rather than pip
packages: on any desktop that can show an indicator at all (Ubuntu ships
AppIndicator for Telegram, Docker and the rest), `python3-gi` is already
there. `mantrin tray` re-execs accordingly.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    from . import config
except ImportError:                     # running as a plain script (system python)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from jarvis import config

_ASSETS = Path(__file__).resolve().parent / "assets" / "tray"
PID_FILE = config.DATA_DIR / "tray.pid"

_STATE_ICON = {
    "ready": "green",
    "hearing": "blue",
    "thinking": "blue",
    "speaking": "blue",
    "starting": "yellow",
    "error": "red",
    "paused": "grey",
    "off": "grey",
}
_STATE_TEXT = {
    "ready": "Listening for the wake word",
    "hearing": "Hearing you…",
    "thinking": "Thinking…",
    "speaking": "Speaking",
    "starting": "Starting up…",
    "error": "Something's wrong",
    "paused": "Microphone paused",
    "off": "Stopped",
}


def _daemon_answering() -> bool:
    """Socket check without importing the daemon module — that would drag the
    whole brain's dependencies into the system python this runs under."""
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


def _read_state() -> tuple[str, str]:
    try:
        data = json.loads(config.STATE_FILE.read_text())
        return str(data.get("state", "off")), str(data.get("detail", ""))
    except (OSError, ValueError):
        return "off", ""


def current_status() -> tuple[str, str]:
    """(icon, human text) — the file says what the daemon last felt, the
    socket says whether it is still alive to feel anything. A 'ready' from a
    process that stopped answering is a crash, not a status."""
    state, detail = _read_state()
    # The daemon says "paused" only once the recorder process is actually gone
    # and the OS mic light is out. Until then the honest icon is the live one —
    # claiming muted while the device is still held is exactly the lie this
    # feature exists to avoid.
    if config.MIC_PAUSE_FILE.exists() and state != "paused":
        detail = "muting — finishing the current exchange"
    if not _daemon_answering():
        if state == "starting":
            pass                        # socket comes up last; yellow is the truth
        elif state == "off":
            state, detail = "off", detail or "not running"
        else:
            state, detail = "error", "daemon stopped answering"
    icon = _STATE_ICON.get(state, "grey")
    text = _STATE_TEXT.get(state, state)
    if detail:
        text = f"{text} — {detail}"
    return icon, text


def _mantrin(*args: str) -> None:
    """Run a mantrin command detached — menu clicks must never freeze GTK."""
    exe = shutil.which("mantrin") or str(Path.home() / ".local" / "bin" / "mantrin")
    subprocess.Popen([exe, *args], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _already_running() -> bool:
    """True only if the recorded pid is alive AND is actually a tray. After a
    reboot the old pid may belong to any process the kernel handed it to —
    trusting the number alone would make the tray silently refuse to start."""
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        return "tray" in cmdline and ("mantrin" in cmdline or "jarvis" in cmdline)
    except (OSError, ValueError):
        return False


def main() -> int:
    try:
        import gi
    except ImportError:
        # The venv doesn't carry GTK bindings; the system python does.
        system = "/usr/bin/python3"
        if sys.executable != system and Path(system).exists():
            os.execv(system, [system, str(Path(__file__).resolve())])
        print("The tray needs the system GTK bindings: sudo apt install "
              "python3-gi gir1.2-ayatanaappindicator3-0.1")
        return 1

    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
    except ValueError:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    if _already_running():
        return 0
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    indicator = AppIndicator.Indicator.new(
        "mantrin", "mantrin-grey", AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_icon_theme_path(str(_ASSETS))
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    status_item = Gtk.MenuItem(label="…")
    status_item.set_sensitive(False)
    menu.append(status_item)
    menu.append(Gtk.SeparatorMenuItem())

    pause_item = Gtk.CheckMenuItem(label="Pause microphone")
    updating = {"pause": False}         # guard: set_active() also fires 'toggled'

    def on_pause(item) -> None:
        if updating["pause"]:
            return
        if item.get_active():
            config.MIC_PAUSE_FILE.touch()
        else:
            config.MIC_PAUSE_FILE.unlink(missing_ok=True)
        refresh()
    pause_item.connect("toggled", on_pause)
    menu.append(pause_item)
    menu.append(Gtk.SeparatorMenuItem())

    for label, args in (("Restart Mantrin", ("restart",)), ("Stop Mantrin", ("stop",))):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _w, a=args: _mantrin(*a))
        menu.append(item)

    # Quit means quit: daemon, microphone, icon — all of it. The one thing
    # this menu must never do is remove the visible face of an always-on
    # microphone while leaving the ears running.
    quit_item = Gtk.MenuItem(label="Quit Mantrin")

    def on_quit(_w) -> None:
        _mantrin("stop")
        Gtk.main_quit()
    quit_item.connect("activate", on_quit)
    menu.append(quit_item)
    menu.show_all()
    indicator.set_menu(menu)

    last = {"icon": ""}

    def refresh() -> bool:
        icon, text = current_status()
        if icon != last["icon"]:
            last["icon"] = icon
            indicator.set_icon_full(f"mantrin-{icon}", text)
        status_item.set_label(text)
        updating["pause"] = True
        pause_item.set_active(config.MIC_PAUSE_FILE.exists())
        updating["pause"] = False
        return True                     # keep the GLib timer alive

    refresh()
    GLib.timeout_add(1000, refresh)
    try:
        Gtk.main()
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
