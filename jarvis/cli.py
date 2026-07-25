"""Entrypoint. `jarvis` starts a conversation; the brain persists across runs.

Right now you launch it with a command. That's a scaffold — the destination
is an always-on presence you summon with "Jarvis", no command. We build the
brain first, then put the always-on skin around it.
"""

from __future__ import annotations

import argparse
import sys

from . import config
from .core.brain import Brain
from .core.memory import MemoryStore
from .providers.llm import ClaudeLLM


def _run_conversation(voice: bool) -> None:
    memory = MemoryStore(config.DB_FILE)
    brain = Brain(
        llm=ClaudeLLM(model=config.LLM_MODEL),
        memory=memory,
        extractor=ClaudeLLM(model=config.EXTRACT_MODEL),
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

    while True:
        user_text = io.listen()
        if user_text is None:
            io.speak("Talk soon.")
            break
        io.speak(brain.think(user_text))


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal Jarvis (v1).")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("memory", help="show everything Jarvis remembers (and why)")
    sub.add_parser("commitments", help="show open loops Jarvis is tracking")
    sub.add_parser("brief", help="a short daily brief from memory + open loops")
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

    try:
        _run_conversation(voice=args.voice)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
