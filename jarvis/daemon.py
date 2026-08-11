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
import os
import queue
import socket
import sys
import threading
import time

from . import config
from .core.brain import Brain
from .core.memory import MemoryStore
from .io.remote_io import RemoteIO
from .providers.embeddings import LocalEmbedder
from .providers.llm import ClaudeLLM
from .tools.base import Registry
from .tools.web_search import WebSearch


def publish_state(state: str, detail: str = "") -> None:
    """Drop the daemon's condition where the desktop can see it — the tray
    icon's colour is literally this file. Atomic write so a reader never
    catches half a JSON object; best-effort because a missing state file
    must never take the voice down with it."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config.STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"state": state, "detail": detail, "ts": time.time()}))
        tmp.replace(config.STATE_FILE)
    except OSError:
        pass


def _x_tools() -> list:
    """X (Twitter) tools, only if creds are configured in the environment."""
    if not config.x_configured():
        return []
    from .tools.x_tools import x_tools

    return x_tools(config.X_API_KEY, config.X_API_SECRET, config.X_ACCESS_TOKEN, config.X_ACCESS_SECRET)


def _connect_mcp(tools: list) -> list:
    clients = []
    for server in config.load_mcp_servers():
        name = server.get("name", "?")
        try:
            from .tools.mcp_client import connect

            auth = None
            if server.get("url") and server.get("auth") == "oauth":
                # A remote server that wants a signed-in account. The daemon
                # is headless: it may USE stored tokens (and refresh them),
                # but the browser dance belongs to `mantrin connect`.
                from .tools import mcp_oauth

                if not mcp_oauth.signed_in(name):
                    print(f"(MCP '{name}' off — sign in first: mantrin connect {name})",
                          flush=True)
                    continue
                auth = mcp_oauth.build(name, server["url"], interactive=False)

            # Local servers run with DATA_DIR as their working directory
            # unless the block says otherwise: scratch files (spotipy's token
            # cache, for one) land in one predictable place instead of
            # wherever the daemon happened to be started from —
            # site-packages, on a pip install.
            client, mcp_tools = connect(
                name, server.get("command"), server.get("args", []),
                server.get("env"), server.get("cwd") or str(config.DATA_DIR),
                errlog_path=str(config.DATA_DIR / f"mcp-{name}.log"),
                url=server.get("url"), headers=server.get("headers"), auth=auth,
            )
            clients.append(client)
            tools.extend(mcp_tools)
            print(f"(MCP '{name}': {len(mcp_tools)} tools)", flush=True)
        except Exception as e:
            print(f"(MCP '{name}' failed to start: {e})", flush=True)
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
            text, io, on_text, reply_to = item
            try:
                reply_to.put(("ok", self._brain.think(text, io=io, on_text=on_text)))
            except Exception as e:                       # noqa: BLE001
                reply_to.put(("error", e))

    def think(self, text: str, io=None, on_text=None) -> str:
        """Submit a turn and wait for the reply."""
        reply_to: queue.Queue = queue.Queue(maxsize=1)
        self._queue.put((text, io, on_text, reply_to))
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
        publish_state("off", "dictation mode — no microphone held")
        return

    # At login the daemon can beat PipeWire to the punch — the service starts
    # in parallel with the sound stack. Retry before declaring the mic absent,
    # so "voice off" means the machine truly has no microphone, not that we
    # looked three seconds too early.
    problem = audio_probe()
    for _ in range(5):
        if not problem:
            break
        time.sleep(6)
        problem = audio_probe()
    if problem:
        print(f"(voice off: {problem})", flush=True)
        publish_state("error", f"voice off: {problem}")
        return

    try:
        stt = registry.build_stt(config.STT_PROVIDER, **config.STT_OPTIONS)
        tts = registry.build_tts(config.TTS_PROVIDER, **config.TTS_OPTIONS)
    except registry.Unavailable as e:
        print(f"(voice off: {e})", flush=True)
        publish_state("error", f"voice off: {e}")
        return

    # The talk key (push-to-talk). A trigger that needs a key nobody can read
    # falls back to the wake word — an unreachable Mantrin helps no one.
    from . import audio, hotkey

    trigger = config.VOICE_TRIGGER
    ptt = None
    if trigger != "wake":
        if not hotkey.readable():
            print("(talk key off: /dev/input isn't readable — "
                  "sudo usermod -aG input $USER, then log out and back in)", flush=True)
            trigger = "wake"
        else:
            ptt = hotkey.TalkKey(config.TALK_KEY).start()
            name = config.SETTINGS.get("talk_key_name") or f"key {config.TALK_KEY}"
            print(f"(talk key: hold {name} to speak)", flush=True)

    io = VoiceIO(
        stt, tts,
        # Key-only mode never loads the wake model, and skips echo
        # cancellation: the mic is closed while Mantrin speaks, so there is
        # no echo to cancel — and each key-press reopen stays fast.
        gate=wake.build(config.WAKE_WORD) if trigger != "key" else None,
        hints=lambda: _name_hints(memory),
        show_timings=config.SHOW_TIMINGS,
        stream=audio.FrameStream(ec=(trigger != "key")),
        on_state=publish_state,
        ptt=ptt,
        trigger=trigger,
    )
    try:
        while True:
            text = io.listen()
            if text is None:
                print("(microphone stream ended — voice off)", flush=True)
                publish_state("error", "microphone stream ended")
                return
            speaker = None
            try:
                # Timed here because only this loop sees the whole brain call —
                # and the brain is usually the biggest share of a turn, which is
                # exactly what --timings exists to show. The speaker starts
                # talking DURING that stage: first sentence out while the rest
                # is still being generated.
                publish_state("thinking")
                speaker = io.begin_reply()
                with io.turn.stage("brain"):
                    reply = turns.think(
                        text, io=io, on_text=speaker.feed if speaker else None
                    )
                io.end_reply(speaker, reply)
            except Exception as e:                      # noqa: BLE001
                io.abort_reply(speaker)
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
    # So `mantrin stop` can reach a daemon that was started by hand.
    pid_path = sock_path.parent / "jarvis.pid"
    pid_path.write_text(str(os.getpid()))

    print("Jarvis daemon starting — loading brain + connections…", flush=True)
    publish_state("starting", "loading brain + connections")
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
    else:
        publish_state("off", "voice disabled — text only")

    try:
        while True:
            conn, _ = server.accept()
            _serve_client(conn, turns)
    except KeyboardInterrupt:
        print("\nShutting down…", flush=True)
    finally:
        # An impatient second Ctrl+C lands here, mid-cleanup — closing the MCP
        # clients waits on their threads for a few seconds. Finish quietly
        # rather than dying with a traceback over a shutdown that was already
        # underway.
        try:
            publish_state("off", "shut down")
            turns.stop()
            brain.close()       # let queued memory updates land before exit
            server.close()
            if sock_path.exists():
                sock_path.unlink()
            pid_path.unlink(missing_ok=True)
            for client in mcp_clients:
                client.close()
        except KeyboardInterrupt:
            print("(cleanup interrupted — exiting now)", flush=True)
            pid_path.unlink(missing_ok=True)
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
