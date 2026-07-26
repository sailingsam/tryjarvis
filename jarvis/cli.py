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


def _run_conversation(voice: bool) -> None:
    # The embedder is only needed here — it's what writes fact vectors and powers
    # query-driven recall. The read-only commands don't load it (faster startup).
    memory = MemoryStore(config.DB_FILE, embedder=LocalEmbedder())

    tools = [WebSearch()]
    mcp_clients = _connect_mcp(tools)   # extends `tools` with any configured servers

    brain = Brain(
        llm=ClaudeLLM(model=config.LLM_MODEL),
        memory=memory,
        extractor=ClaudeLLM(model=config.EXTRACT_MODEL),
        tools=Registry(tools),
    )

    if voice:
        from .io.voice_io import VoiceIO
        from .providers.stt import WhisperSTT
        from .providers.tts import Pyttsx3TTS

        io = VoiceIO(stt=WhisperSTT(), tts=Pyttsx3TTS())
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
        for client in mcp_clients:
            client.close()


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
    if not mems:
        print("(Jarvis doesn't know anything yet.)")
        return
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


def _client_conversation() -> None:
    """Thin client: talk to the running daemon over its socket. The daemon holds
    the brain + live connections; we just relay text and handle confirmations."""
    import json
    import socket

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(config.SOCKET_FILE))
    f = s.makefile("rw")
    print("Connected to Jarvis (daemon). Type 'exit' to leave.\n")

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
                print(f"jarvis> {msg['text']}")
                ans = input("  > ").strip()
                f.write(json.dumps({"type": "input", "text": ans}) + "\n")
                f.flush()
            elif msg["type"] == "reply":
                print(f"jarvis> {msg['text']}\n")
                break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal Jarvis (v1).")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("memory", help="show everything Jarvis remembers (and why)")
    sub.add_parser("commitments", help="show open loops Jarvis is tracking")
    sub.add_parser("brief", help="a short daily brief from memory + open loops")
    sub.add_parser("daemon", help="run the persistent daemon (keeps WhatsApp etc. connected)")
    parser.add_argument("--voice", action="store_true", help="use the microphone instead of text")
    args = parser.parse_args(argv)

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

    # When there are live connections worth keeping warm (MCP servers like
    # WhatsApp), run through the daemon — auto-starting it if needed — so the
    # connection persists and stays warm. Otherwise just run in-process.
    try:
        if not args.voice and (_daemon().is_running() or config.load_mcp_servers()):
            if _ensure_daemon():
                _client_conversation()
                return 0
        _run_conversation(voice=args.voice)
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
