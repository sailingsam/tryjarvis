"""Run Mantrin as a login service, with commands a person can remember.

The product promise is presence: open the laptop, say the wake word, and it
answers — no terminal, nothing to start. On Linux the boring, correct way to
get that is a systemd *user* service: starts at login (when the microphone and
PipeWire exist), restarts on a crash, logs to the journal.

Nobody should have to remember `systemctl --user …` or `journalctl --user -u …`
though, so every operation is a mantrin command:

    mantrin install      # start at every login, starting now
    mantrin status       # is it alive, and what does it know
    mantrin logs         # follow what it is doing
    mantrin restart      # pick up new code
    mantrin stop         # stop until the next login or `mantrin start`
    mantrin uninstall    # remove the service; nothing else changes

Two things make the unit actually work that a hand-written one would miss:

* A service does not inherit the shell's environment. The API keys living only
  in `.bashrc` exports would simply be absent, and Mantrin would start
  brainless. `install` persists the keys it can see into the config store
  (0600) that the daemon already reads.
* `node` from nvm lives under the home directory, not on systemd's default
  PATH — the WhatsApp bridge would fail to spawn. The unit pins the PATH that
  was live at install time.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config

UNIT = "mantrin.service"
PID_FILE = config.DATA_DIR / "jarvis.pid"

# Keys worth carrying from the interactive shell into the service's world.
_KNOWN_KEYS = (
    "ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY",
    "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET",
    "HF_TOKEN",
)


def _unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "systemd" / "user" / UNIT


def _systemctl(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=capture, text=True,
    )


def _have_systemd() -> bool:
    return shutil.which("systemctl") is not None


def installed() -> bool:
    return _unit_path().exists()


def _persist_shell_keys() -> list[str]:
    """Copy API keys visible in this shell into the config store, so the
    service — which inherits nothing from the shell — still has them."""
    settings = config.load_settings()
    keys = settings.get("keys") or {}
    carried = []
    for name in _KNOWN_KEYS:
        value = os.environ.get(name)
        if value and keys.get(name) != value:
            keys[name] = value
            carried.append(name)
    if carried:
        settings["keys"] = keys
        config.save_settings(settings)
    return carried


def _render_unit() -> str:
    # sys.executable as-is, NOT resolved: the venv's python is a symlink to the
    # system interpreter, and resolving it would write a unit that runs the
    # system python — which has none of Mantrin's dependencies installed.
    python = Path(sys.executable)
    project = Path(__file__).resolve().parent.parent
    # After= names are weak ordering: ignored where those units don't exist,
    # and they save a login race where the mic isn't up yet where they do.
    return f"""\
[Unit]
Description=Mantrin — a chief of staff you talk to
After=default.target pipewire.service wireplumber.service pulseaudio.service

[Service]
Type=simple
ExecStart={python} -m jarvis daemon
WorkingDirectory={project}
Restart=on-failure
RestartSec=5
Environment=PATH={os.environ.get('PATH', '/usr/bin:/bin')}

[Install]
WantedBy=default.target
"""


def _stop_manual_daemon() -> None:
    """Stop a daemon started by hand, so the service doesn't find the socket
    taken and immediately exit."""
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGINT)         # the daemon's graceful path
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return
    for _ in range(20):
        if not _daemon_alive():
            return
        time.sleep(0.5)


def _daemon_alive() -> bool:
    from . import daemon

    return daemon.is_running()


def install() -> int:
    if not _have_systemd():
        print("This system doesn't run systemd — start Mantrin with `mantrin` "
              "instead (it stays alive in the background until reboot).")
        return 1
    carried = _persist_shell_keys()
    if carried:
        print(f"Saved {', '.join(carried)} into {config.CONFIG_FILE} — a service "
              f"doesn't inherit your shell's exports.")
    _stop_manual_daemon()

    path = _unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_unit())
    _systemctl("daemon-reload")
    result = _systemctl("enable", "--now", UNIT)
    if result.returncode != 0:
        print(f"Couldn't enable the service: {result.stderr.strip()}")
        return 1

    # Give it a moment, then tell the truth about whether it came up.
    for _ in range(20):
        if _daemon_alive():
            break
        time.sleep(0.5)
    if _daemon_alive():
        print("Mantrin is running, and will start itself at every login.")
        print("  mantrin status | logs | restart | stop | uninstall")
    else:
        print("Service enabled, but the daemon isn't answering yet — "
              "`mantrin logs` will say why.")
    return 0


def uninstall() -> int:
    if not installed():
        print("No service installed.")
        return 0
    _systemctl("disable", "--now", UNIT)
    _unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")
    print("Service removed. `mantrin` still works — it just won't start at login.")
    return 0


def start() -> int:
    if installed():
        result = _systemctl("start", UNIT)
        if result.returncode != 0:
            print(f"Couldn't start: {result.stderr.strip()}")
            return 1
        print("Started.")
        return 0
    # No service — fall back to the detached background daemon.
    from .cli import _ensure_daemon

    return 0 if _ensure_daemon() else 1


def stop() -> int:
    stopped = False
    if installed():
        stopped = _systemctl("stop", UNIT).returncode == 0
    if _daemon_alive():                     # manual daemon, or stop failed
        _stop_manual_daemon()
        stopped = True
    print("Stopped." if stopped or not _daemon_alive() else "Couldn't stop it.")
    if installed():
        print("(it will return at next login — `mantrin uninstall` stops that)")
    return 0


def restart() -> int:
    if installed():
        result = _systemctl("restart", UNIT)
        print("Restarted." if result.returncode == 0
              else f"Couldn't restart: {result.stderr.strip()}")
        return result.returncode
    _stop_manual_daemon()
    return start()


def status() -> int:
    if installed():
        result = _systemctl("is-active", UNIT)
        state = result.stdout.strip() or "unknown"
        print(f"service : {state} (starts at login)")
    else:
        print("service : not installed — `mantrin install` to start at every login")
    alive = _daemon_alive()
    print(f"daemon  : {'answering on ' + str(config.SOCKET_FILE) if alive else 'not running'}")
    if alive:
        memory_db = config.DB_FILE
        if memory_db.exists():
            import sqlite3

            conn = sqlite3.connect(str(memory_db))
            facts = conn.execute("SELECT count(*) FROM facts").fetchone()[0]
            open_c = conn.execute(
                "SELECT count(*) FROM commitments WHERE status = 'open'"
            ).fetchone()[0]
            conn.close()
            print(f"memory  : {facts} facts, {open_c} open commitments")
    return 0 if alive else 1


def logs() -> int:
    if installed():
        os.execvp("journalctl", ["journalctl", "--user", "-u", UNIT, "-n", "100", "-f"])
    log_file = config.DATA_DIR / "daemon.log"
    if log_file.exists():
        os.execvp("tail", ["tail", "-n", "100", "-f", str(log_file)])
    print("No logs yet — nothing has run.")
    return 1
