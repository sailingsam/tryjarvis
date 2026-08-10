"""Entrypoint. `jarvis` starts a conversation; the brain persists across runs.

Right now you launch it with a command. That's a scaffold — the destination
is an always-on presence you summon with "Jarvis", no command. We build the
brain first, then put the always-on skin around it.
"""

from __future__ import annotations

import argparse
import sys

# Importing readline gives input() proper line editing — arrow keys, cursor
# movement, and in-session history — instead of raw ^[[A escape codes.
try:
    import readline  # noqa: F401
except ImportError:
    pass

from . import config
from .core.brain import Brain
from .core.memory import MemoryStore
from .providers.embeddings import LocalEmbedder
from .providers.llm import ClaudeLLM
from .tools.base import Registry
from .tools.web_search import WebSearch


def _run_conversation(dictation: bool = False) -> None:
    """A whole Mantrin in this process — used when there is no daemon to talk to.

    Voice does not run here. The microphone belongs to the daemon, because a
    second process would start its own copy of every MCP server: with WhatsApp
    that means two Baileys clients sharing one set of credentials, which kills
    the session for both.
    """
    # The embedder is only needed here — it's what writes fact vectors and powers
    # query-driven recall. The read-only commands don't load it (faster startup).
    memory = MemoryStore(config.DB_FILE, embedder=LocalEmbedder())

    tools = [WebSearch(), *_daemon()._x_tools()]
    mcp_clients = _connect_mcp(tools)   # extends `tools` with any configured servers

    brain = Brain(
        llm=ClaudeLLM(model=config.LLM_MODEL),
        memory=memory,
        extractor=ClaudeLLM(model=config.EXTRACT_MODEL),
        tools=Registry(tools),
    )

    if dictation:
        io = _dictation_io()
    else:
        from .io.text_io import TextIO

        io = TextIO()

    known = len(memory)
    open_c = memory.open_commitments()
    if known:
        hello = f"Hey — good to see you again. I remember {known} thing{'s' if known != 1 else ''} about you."
        if open_c:
            hello += f" You've got {len(open_c)} open item{'s' if len(open_c) != 1 else ''} I'm tracking."
    else:
        hello = "Hi, I'm Jarvis. We're just getting started — tell me about yourself."
    io.speak(hello)

    try:
        while True:
            user_text = io.listen()
            if user_text is None:
                io.speak("Talk soon.")
                break
            io.speak(brain.think(user_text, io=io))
    finally:
        brain.close()           # let queued memory updates land before exit
        close = getattr(io, "close", None)
        if callable(close):
            close()
        for client in mcp_clients:
            client.close()


def _dictation_io():
    """Text in, speech out — for someone using their own dictation app."""
    from .io.voice_io import DictationIO
    from .providers import voice_registry as registry

    try:
        tts = registry.build_tts(config.TTS_PROVIDER, **config.TTS_OPTIONS)
    except registry.Unavailable as e:
        print(f"({e} — replies will be printed only)")
        from .providers.tts import Silent

        tts = Silent()
    return DictationIO(tts, show_timings=config.SHOW_TIMINGS)


def _connect_mcp(tools: list) -> list:
    """Start any MCP servers from config, append their tools to `tools`, and
    return the live clients (so the caller can close them on exit). A server
    that fails to start is skipped with a note — it never blocks the session."""
    clients = []
    for server in config.load_mcp_servers():
        try:
            from .tools.mcp_client import connect

            client, mcp_tools = connect(
                server["name"], server["command"], server.get("args", []),
                server.get("env"), server.get("cwd"),
                errlog_path=str(config.DATA_DIR / f"mcp-{server['name']}.log"),
            )
            clients.append(client)
            tools.extend(mcp_tools)
            print(f"(MCP '{server['name']}': {len(mcp_tools)} tools)")
        except Exception as e:
            print(f"(MCP '{server.get('name', '?')}' failed to start: {e})")
    return clients


def _show_memory() -> None:
    memory = MemoryStore(config.DB_FILE)
    mems = memory.recall()
    directives = memory.directives()
    if not mems and not directives:
        print("(Jarvis doesn't know anything yet.)")
        return
    if directives:
        print(f"Standing instructions ({len(directives)}):\n")
        for d in directives:
            print(f"  ! {d.content}")
            print(f"      why: heard \"{d.source}\"  ({d.human_time()})")
        print()
    print(f"Jarvis remembers {len(mems)} thing(s):\n")
    for m in mems:
        print(f"  • {m.content}")
        print(f"      why: heard \"{m.source}\"  ({m.human_time()})")


def _show_commitments() -> None:
    memory = MemoryStore(config.DB_FILE)
    open_c = memory.open_commitments()
    done = [c for c in memory.all_commitments() if c.status == "done"]
    if not open_c and not done:
        print("(No commitments tracked yet.)")
        return
    if open_c:
        print(f"Open loops ({len(open_c)}):\n")
        for c in open_c:
            print(f"  ☐ {c.content}  ({c.human_time()})")
    if done:
        print(f"\nDone ({len(done)}):\n")
        for c in done:
            print(f"  ☑ {c.content}")


def _daily_brief() -> None:
    memory = MemoryStore(config.DB_FILE)
    brain = Brain(llm=ClaudeLLM(model=config.LLM_MODEL), memory=memory)
    print(brain.brief())


def _client_conversation(speak: bool = False) -> None:
    """Thin client: talk to the running daemon over its socket. The daemon holds
    the brain + live connections; we just relay text and handle confirmations.

    `speak` reads replies out loud here in the client. That is dictation mode: the
    user's own app types the input, and the voice belongs to whoever is at this
    terminal — the daemon's microphone is a different conversation.
    """
    import json
    import socket

    voice = _client_voice() if speak else None

    def show(text: str) -> None:
        print(f"jarvis> {text}\n")
        if voice is not None:
            playback = voice.speak(text)
            if playback is not None:
                playback.wait(timeout=120)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(config.SOCKET_FILE))
    f = s.makefile("rw")
    print("Connected to Mantrin (daemon). Type 'exit' to leave.\n")

    from .io.text_io import _EXIT

    while True:
        try:
            text = input("you  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text or text.lower() in _EXIT:
            break
        f.write(json.dumps({"type": "say", "text": text}) + "\n")
        f.flush()
        while True:
            line = f.readline()
            if not line:
                print("(daemon disconnected)")
                return
            msg = json.loads(line)
            if msg["type"] == "confirm_prompt":
                show(msg["text"])
                ans = input("  > ").strip()
                f.write(json.dumps({"type": "input", "text": ans}) + "\n")
                f.flush()
            elif msg["type"] == "reply":
                show(msg["text"])
                break


def _client_voice():
    """A voice for the client, or None if one cannot be built."""
    from .providers import voice_registry as registry

    try:
        return registry.build_tts(config.TTS_PROVIDER, **config.TTS_OPTIONS)
    except registry.Unavailable as e:
        print(f"({e} — replies will be printed only)")
        return None


def main(argv: list[str] | None = None) -> int:
    # The flags live on a parent parser attached to the main parser AND every
    # subcommand, so `mantrin daemon --timings` and `mantrin --timings daemon`
    # both work — nobody remembers which side of the subcommand a flag goes on.
    # Defaults are SUPPRESS on the parent: a subparser runs after the main
    # parser, and a plain default would overwrite a flag given before the
    # subcommand with False again.
    flags = argparse.ArgumentParser(add_help=False)
    n = argparse.SUPPRESS
    flags.add_argument("--text", action="store_true", default=n,
                       help="type instead of talking, and leave the microphone alone")
    flags.add_argument("--dictate", action="store_true", default=n,
                       help="dictate with your own app; Mantrin speaks the reply back")
    flags.add_argument("--stt", metavar="NAME", default=n,
                       help="override the speech-to-text provider")
    flags.add_argument("--tts", metavar="NAME", default=n,
                       help="override the voice provider")
    flags.add_argument("--timings", action="store_true", default=n,
                       help="print where each turn's time went")
    flags.add_argument("--no-voice", action="store_true", default=n,
                       help="don't hold the microphone at all")

    parser = argparse.ArgumentParser(
        prog="mantrin", description="Mantrin — a chief of staff you talk to.",
        parents=[flags],
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup", parents=[flags],
                   help="choose whose ears and voice to use, and save any keys")
    sub.add_parser("memory", parents=[flags],
                   help="show everything Mantrin remembers (and why)")
    sub.add_parser("commitments", parents=[flags],
                   help="show open loops Mantrin is tracking")
    sub.add_parser("brief", parents=[flags],
                   help="a short daily brief from memory + open loops")
    sub.add_parser("daemon", parents=[flags],
                   help="run the always-on daemon in the foreground")
    sub.add_parser("install", parents=[flags],
                   help="start Mantrin at every login (systemd user service)")
    sub.add_parser("uninstall", parents=[flags], help="remove the login service")
    sub.add_parser("start", parents=[flags], help="start Mantrin in the background")
    sub.add_parser("stop", parents=[flags], help="stop the running Mantrin")
    sub.add_parser("restart", parents=[flags], help="restart Mantrin (picks up new code)")
    sub.add_parser("status", parents=[flags], help="is Mantrin running, and what does it know")
    sub.add_parser("logs", parents=[flags], help="follow what Mantrin is doing")
    sub.add_parser("tray", parents=[flags], help="show the status icon in the top bar")
    sub.add_parser("set-key", parents=[flags],
                   help="choose a push-to-talk key: hold it to talk, release to get the answer")
    connect_p = sub.add_parser("connect", parents=[flags],
                               help="plug in an integration — WhatsApp, Spotify, Calendar…")
    connect_p.add_argument("integration", nargs="?", default=None,
                           help="which one (bare `mantrin connect` lists them all)")
    args = parser.parse_args(argv)

    # Per-run overrides go into the environment, not onto the config module.
    # Voice lives in the daemon, which is a *separate process* that imports its
    # own config — so assigning attributes here would change nothing where it
    # matters. The environment is inherited by the daemon we spawn, and config
    # already reads exactly these names.
    import os

    stt = getattr(args, "stt", None)
    tts = getattr(args, "tts", None)
    dictate = getattr(args, "dictate", False)
    if stt:
        os.environ["MANTRIN_STT"] = stt
        config.STT_PROVIDER = stt
    if tts:
        os.environ["MANTRIN_TTS"] = tts
        config.TTS_PROVIDER = tts
    if getattr(args, "timings", False):
        os.environ["MANTRIN_TIMINGS"] = "1"
        config.SHOW_TIMINGS = True
    # Only the explicit flag turns the daemon's microphone off. --text and
    # --dictate describe *this client's* input, but the environment set here is
    # inherited by a daemon spawned below and outlives this run — typing one
    # command must not leave a permanently deaf always-on process behind.
    if getattr(args, "no_voice", False):
        os.environ["MANTRIN_VOICE"] = "0"
        config.VOICE_ENABLED = False

    if args.cmd == "setup":
        from .setup_wizard import run as run_setup
        return run_setup()
    if args.cmd == "memory":
        _show_memory()
        return 0
    if args.cmd == "commitments":
        _show_commitments()
        return 0
    if args.cmd == "brief":
        _daily_brief()
        return 0
    if args.cmd == "daemon":
        from .daemon import run
        return run()
    if args.cmd == "tray":
        from .tray import main as tray_main
        return tray_main()
    if args.cmd == "set-key":
        from .hotkey import set_key
        return set_key()
    if args.cmd == "connect":
        from .connect import connect
        return connect(args.integration)
    if args.cmd in ("install", "uninstall", "start", "stop", "restart", "status", "logs"):
        from . import service
        return getattr(service, args.cmd)()

    # The daemon is where Mantrin actually lives: it holds the microphone and the
    # MCP connections. Anything here is a thin client onto that one brain — which
    # is also why voice never runs in this process. Two processes would each start
    # their own WhatsApp client against the same credentials.
    try:
        if _daemon().is_running() or config.load_mcp_servers() or config.VOICE_ENABLED:
            if _ensure_daemon():
                _client_conversation(speak=dictate)
                return 0
        _run_conversation(dictation=dictate)
    except KeyboardInterrupt:
        print()
    return 0


def _daemon():
    from . import daemon
    return daemon


def _ensure_daemon() -> bool:
    """Ensure a daemon is running (start it in the background if not). Returns
    True if one is available to talk to. First launch takes a moment while it
    connects; after that it stays warm in the background."""
    import subprocess
    import time

    if _daemon().is_running():
        return True
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(config.DATA_DIR / "daemon.log", "a")
    print("Starting Jarvis in the background (first launch takes a moment)…")
    subprocess.Popen(
        [sys.executable, "-m", "jarvis", "daemon"],
        stdout=log, stderr=log, start_new_session=True,
    )
    for _ in range(75):                 # up to ~150s for WhatsApp to connect
        if _daemon().is_running():
            return True
        time.sleep(2)
    print("(daemon didn't come up — running in-process this time)")
    return False


if __name__ == "__main__":
    sys.exit(main())
