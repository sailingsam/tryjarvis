"""`mantrin logs` — the daemon's story, told so a person can actually read it.

The journal's raw view buries the two lines that matter under hostnames, pids
and five kinds of housekeeping. This view keeps every line but ranks them:
the conversation in colour (you cyan, Mantrin green), problems in red with
the fix beside them, everything mechanical dimmed to a murmur. A restart
becomes a visible seam instead of twelve more identical grey lines.

Reads the journal when the service is installed, the daemon.log file when
running by hand. `--chat` narrows to the conversation alone; `--raw` is the
untouched journalctl view for when the full truth is needed.
"""

from __future__ import annotations

import re
import subprocess
import sys

from . import config

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"

# `-o short-iso` is requested explicitly so this shape is stable across
# distros: 2026-08-19T23:06:39+0530 host tag[pid]: message
_JOURNAL = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}):\d{2}\S*\s+\S+\s+"
    r"(?P<tag>[^\[\s]+)\[\d+\]:\s?(?P<msg>.*)$"
)

_MCP_FAILED = re.compile(r"\(MCP '([\w-]+)' failed")


def _unwrap(s: str) -> str:
    """One matched outer pair only — .strip("()") would also eat the closing
    paren of an inner "(1 sub-exception)" and print it unbalanced."""
    return s[1:-1] if s.startswith("(") and s.endswith(")") else s


def _classify(msg: str) -> tuple[str, str]:
    """(kind, display text) for one daemon line. Kinds drive colour and
    survive `--chat` filtering; the text is what a person should read."""
    if msg.startswith("Jarvis daemon starting"):
        return "restart", ""
    if msg.startswith("Jarvis daemon ready"):
        return "ready", "ready — brain and connections up"
    if msg.startswith("you  >"):
        return "you", msg[6:].strip()
    if msg.startswith("jarvis>"):
        return "jarvis", msg[7:].strip()
    if msg.startswith("(reminder due"):
        return "reminder", "reminder due — speaking up"
    if msg.startswith("Traceback") or msg.startswith("  File \""):
        return "error", msg.rstrip()

    s = msg.strip()
    # Only the daemon's own parenthesised notes are judged for trouble — a
    # REPLY that happens to contain the word "error" is conversation, not
    # an incident, and must never light up red.
    if s.startswith("("):
        if " failed" in s or "went wrong" in s or "voice off" in s:
            text = _unwrap(s)
            m = _MCP_FAILED.search(s)
            if m:
                text += f"  → try: mantrin connect {m.group(1)}"
            return "error", text
        if "off — set" in s or "off — sign in" in s or s.startswith("(MCP off"):
            return "waiting", _unwrap(s)
        return "chatter", _unwrap(s)
    if "ms" in s and "= " in s and s.endswith("s"):
        return "timing", s
    # Anything else the daemon prints bare is almost always the rest of a
    # multi-line reply; _emit knows whether one is in flight.
    return "plain", s


# What `--chat` keeps: the conversation and its seams, nothing mechanical.
_CHAT_KINDS = {"restart", "you", "jarvis", "jarvis_more", "reminder"}


def _paint(kind: str, text: str, when: str, date: str, color: bool) -> str | None:
    def c(code: str, s: str) -> str:
        return f"{code}{s}{_RESET}" if color else s

    stamp = c(_DIM, f"{when}  ") if when else ""
    if kind == "restart":
        seam = f"── restart · {date} {when} " + "─" * 34
        return "\n" + c(_DIM, seam)
    if kind == "ready":
        return stamp + c(_GREEN, "✓  " + text)
    if kind == "you":
        return stamp + c(_BOLD + _CYAN, "you     ") + c(_CYAN, text)
    if kind == "jarvis":
        return stamp + c(_BOLD + _GREEN, "jarvis  ") + c(_GREEN, text)
    if kind == "jarvis_more":                # the rest of a multi-line reply
        return stamp + c(_GREEN, "        " + text)
    if kind == "reminder":
        return stamp + c(_YELLOW, "⏰ " + text)
    if kind == "error":
        return stamp + c(_RED, "✗  " + text)
    if kind == "waiting":
        return stamp + c(_YELLOW, "…  ") + c(_DIM, text)
    return stamp + c(_DIM, text)           # timing + chatter: visible, quiet


def _show(msg: str, when: str, date: str, chat: bool, color: bool, state: dict) -> None:
    kind, text = _classify(msg)
    # A bare, unrecognised line right after a "jarvis>" line is the rest of
    # that reply — the daemon prints replies verbatim, newlines included.
    if kind == "plain" and state.get("in_reply"):
        kind = "jarvis_more"
    state["in_reply"] = kind in ("jarvis", "jarvis_more")
    if chat and kind not in _CHAT_KINDS:
        return
    out = _paint(kind, text, when, date, color)
    if out is not None:
        print(out, flush=True)


def _emit(line: str, chat: bool, color: bool, state: dict) -> None:
    m = _JOURNAL.match(line)
    if not m:
        return                              # journal boot markers and the like
    if not m["tag"].startswith("python"):
        return                              # systemd's own housekeeping
    if m["msg"].startswith("Jarvis daemon starting"):
        pass                                # the seam carries its own date
    elif m["date"] != state.get("date"):
        # A quiet seam when the calendar flips without a restart.
        print(f"{_DIM}── {m['date']} ──{_RESET}" if color else f"── {m['date']} ──")
    state["date"] = m["date"]
    _show(m["msg"], m["time"], m["date"], chat, color, state)


def _journal_cmd(*extra: str) -> list[str]:
    from . import service

    return ["journalctl", "--user", "-u", service.UNIT, "-o", "short-iso",
            "--no-pager", *extra]


def _run_journal(chat: bool, color: bool) -> int:
    # The backlog: this daemon's current life, not its whole history. The
    # last "starting" line is the birth; everything before it is a past life.
    backlog = subprocess.run(
        _journal_cmd("-n", "3000"), capture_output=True, text=True
    ).stdout.splitlines()
    start = 0
    for i, line in enumerate(backlog):
        if "Jarvis daemon starting" in line:
            start = i
    state: dict = {}
    for line in backlog[start:]:
        _emit(line, chat, color, state)

    # ...then keep following, live. Ctrl+C to leave.
    proc = subprocess.Popen(
        _journal_cmd("-f", "-n", "0"), stdout=subprocess.PIPE, text=True
    )
    try:
        for line in proc.stdout:
            _emit(line.rstrip("\n"), chat, color, state)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


def _run_file(chat: bool, color: bool) -> int:
    """No service: the daemon was started by hand and logs to a plain file,
    which carries no timestamps — the lines still get their colours."""
    log = config.DATA_DIR / "daemon.log"
    if not log.exists():
        print("No logs yet — nothing has run.")
        return 1
    proc = subprocess.Popen(
        ["tail", "-n", "300", "-F", str(log)], stdout=subprocess.PIPE, text=True
    )
    state: dict = {}
    try:
        for line in proc.stdout:
            _show(line.rstrip("\n"), "", "", chat, color, state)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


def run(chat: bool = False, raw: bool = False) -> int:
    from . import service

    if raw:
        return service.logs()               # the untouched journalctl view
    color = sys.stdout.isatty()
    try:
        if service.installed():
            return _run_journal(chat, color)
        return _run_file(chat, color)
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # `mantrin logs | head` closing early is a reader done reading,
        # not an error worth a traceback.
        return 0
