"""The persistent Mantrin daemon — the always-on process.

Why it exists: WhatsApp (Baileys) needs a stable, long-lived connection to stay
reliable and to capture incoming messages while you're not in a session. A CLI
that spawns and kills everything per run can't do that. The daemon holds the
brain + MCP connections alive.

It also owns the microphone. That is the difference between a program you run and
something that is simply there: with the mic here, there is no terminal to keep
open and no session to start — you say the wake word and Mantrin answers. The
alternative, letting the CLI own the mic, would mean a second process starting
its own copy of every MCP server; with WhatsApp that means two Baileys clients on
one set of credentials, which breaks the session for both.

Two ways in, one brain:
  * voice — a loop on a thread here, holding the mic for as long as the daemon runs
  * socket — the CLI as a thin client, for text mode and debugging

Socket protocol (newline-delimited JSON, one client at a time):
  client → {"type":"say","text": ...}
  daemon → {"type":"confirm_prompt","text": ...}   (mid-tool; client answers)
  client → {"type":"input","text": ...}            (the confirmation answer)
  daemon → {"type":"reply","text": ...}            (turn complete)
"""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading

from . import config
from .core.brain import Brain
from .core.memory import MemoryStore
from .io.remote_io import RemoteIO
from .providers.embeddings import LocalEmbedder
from .providers.llm import ClaudeLLM
from .tools.base import Registry
from .tools.web_search import WebSearch


def _x_tools() -> list:
    """X (Twitter) tools, only if creds are configured in the environment."""
    if not config.x_configured():
        return []
    from .tools.x_tools import x_tools

    return x_tools(config.X_API_KEY, config.X_API_SECRET, config.X_ACCESS_TOKEN, config.X_ACCESS_SECRET)


def _connect_mcp(tools: list) -> list:
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
            print(f"(MCP '{server['name']}': {len(mcp_tools)} tools)", flush=True)
        except Exception as e:
            print(f"(MCP '{server.get('name', '?')}' failed to start: {e})", flush=True)
    return clients


class _Turns:
    """One brain, reached from several places, one turn at a time.

    Voice arrives on its own thread and socket clients on another, but they share
    a single brain — the same conversation history, the same memory, the same open
    commitments. Whether you spoke or typed should not fork Mantrin into two
    minds. Funnelling every turn through one worker gives that for free, and
    keeps the SQLite connection effectively single-threaded without a lock around
    every read.
    """

    def __init__(self, brain):
        self._brain = brain
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._serve, daemon=True, name="brain")
        self._worker.start()

    def _serve(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            text, io, reply_to = item
            try:
                reply_to.put(("ok", self._brain.think(text, io=io)))
            except Exception as e:                       # noqa: BLE001
                reply_to.put(("error", e))

    def think(self, text: str, io=None) -> str:
        """Submit a turn and wait for the reply."""
        reply_to: queue.Queue = queue.Queue(maxsize=1)
        self._queue.put((text, io, reply_to))
        status, value = reply_to.get()
        if status == "error":
            raise value
        return value

    def stop(self) -> None:
        self._queue.put(None)


def _voice_loop(turns: _Turns, memory) -> None:
    """Hold the microphone and talk, for as long as the daemon lives.

    Runs on a thread so the socket keeps working: text mode stays available for
    debugging even while the mic is live, and both reach the same brain.
    """
    from . import wake
    from .io.voice_io import VoiceIO
    from .providers import voice_registry as registry

    # The cheap checks come first: building the local STT means loading a model,
    # which can take twenty seconds — pointless if there is no microphone or the
    # user's mode never uses one.
    spec = registry.spec_for("stt", config.STT_PROVIDER)
    if spec and spec.mode == "text":
        # The user dictates with their own app; there is no mic to hold, and no
        # terminal here to read from either.
        print("(voice off: your dictation app types into a terminal — run `mantrin --dictate`)",
              flush=True)
        return

    problem = audio_probe()
    if problem:
        print(f"(voice off: {problem})", flush=True)
        return

    try:
        stt = registry.build_stt(config.STT_PROVIDER, **config.STT_OPTIONS)
        tts = registry.build_tts(config.TTS_PROVIDER, **config.TTS_OPTIONS)
    except registry.Unavailable as e:
        print(f"(voice off: {e})", flush=True)
        return

    io = VoiceIO(
        stt, tts,
        gate=wake.build(config.WAKE_WORD),
        hints=lambda: _name_hints(memory),
        show_timings=config.SHOW_TIMINGS,
    )
    try:
        while True:
            text = io.listen()
            if text is None:
                print("(microphone stream ended — voice off)", flush=True)
                return
            try:
                # Timed here because only this loop sees the whole brain call —
                # and the brain is usually the biggest share of a turn, which is
                # exactly what --timings exists to show.
                with io.turn.stage("brain"):
                    reply = turns.think(text, io=io)
                io.speak(reply)
            except Exception as e:                      # noqa: BLE001
                io.speak(f"Something went wrong: {e}")
    finally:
        io.close()


def audio_probe() -> str | None:
    from . import audio

    return audio.probe()


def _name_hints(memory, limit: int = 60) -> str | None:
    """Proper nouns from memory, handed to the recogniser as an expectation.

    Speech models mangle names they have never seen — "Mridul" comes back as "Em
    Riddle" — and names are exactly what a chief of staff cannot afford to
    mishear. Mantrin already knows who matters to you, so it can tell its own
    ears what to listen for. This is the memory being useful somewhere other
    than the prompt.
    """
    import re

    words: list[str] = []
    seen: set[str] = set()
    for fact in memory.recall():
        # Capitalised words that are not sentence openers are usually people,
        # companies and places — the vocabulary worth biasing toward.
        for match in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z]{2,})\b", fact.content):
            word = match.group(1)
            if word.lower() in seen:
                continue
            seen.add(word.lower())
            words.append(word)
            if len(words) >= limit:
                break
        if len(words) >= limit:
            break
    return f"Names that may come up: {', '.join(words)}." if words else None


def run() -> int:
    if is_running():
        print("Jarvis daemon is already running.")
        return 0
    sock_path = config.SOCKET_FILE
    if sock_path.exists():
        sock_path.unlink()          # clear a stale socket from a previous run
    sock_path.parent.mkdir(parents=True, exist_ok=True)

    print("Jarvis daemon starting — loading brain + connections…", flush=True)
    memory = MemoryStore(config.DB_FILE, embedder=LocalEmbedder())
    tools = [WebSearch(), *_x_tools()]
    mcp_clients = _connect_mcp(tools)   # WhatsApp etc. now stay connected here
    brain = Brain(
        llm=ClaudeLLM(model=config.LLM_MODEL),
        memory=memory,
        extractor=ClaudeLLM(model=config.EXTRACT_MODEL),
        tools=Registry(tools),
    )

    turns = _Turns(brain)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    print(f"Jarvis daemon ready. Listening on {sock_path}. (Ctrl+C to stop)", flush=True)

    voice = None
    if config.VOICE_ENABLED:
        voice = threading.Thread(
            target=_voice_loop, args=(turns, memory), daemon=True, name="voice"
        )
        voice.start()

    try:
        while True:
            conn, _ = server.accept()
            _serve_client(conn, turns)
    except KeyboardInterrupt:
        print("\nShutting down…", flush=True)
    finally:
        turns.stop()
        server.close()
        if sock_path.exists():
            sock_path.unlink()
        for client in mcp_clients:
            client.close()
    return 0


def _serve_client(conn: socket.socket, turns: _Turns) -> None:
    """Handle one client connection until it disconnects."""
    f = conn.makefile("rw")
    io = RemoteIO(f)
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "say":
                continue
            try:
                reply = turns.think(msg.get("text", ""), io=io)
            except Exception as e:              # noqa: BLE001
                # A failed turn — an API error, a tool blowing up — is the
                # client's bad luck, not grounds to take down the always-on
                # process everything else depends on.
                reply = f"Something went wrong: {e}"
            f.write(json.dumps({"type": "reply", "text": reply}) + "\n")
            f.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            f.close()
            conn.close()
        except OSError:
            pass


def is_running() -> bool:
    """True if a daemon is accepting connections on the socket."""
    if not config.SOCKET_FILE.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(config.SOCKET_FILE))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(run())
