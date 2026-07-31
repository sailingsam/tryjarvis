"""First-run setup: choose ears and a voice, hand over any keys needed.

The first thing someone does with Mantrin is run it in a terminal, and the first
question it has to answer is whose speech services to use. Asking once and
remembering is better than a README telling people which environment variables
to export.

The wizard never installs anything or dials out. It writes one 0600 file and
prints exactly what is still missing, so a failure names itself instead of
turning up later as silence.
"""

from __future__ import annotations

import getpass
import os

from . import audio, config
from .providers import voice_registry as registry


def _choose(kind: str, table: dict, current: str) -> str:
    print(f"\n  {kind}")
    keys = list(table)
    for i, name in enumerate(keys, 1):
        spec = table[name]
        modules, missing_keys = registry.requirements(spec)
        marks = []
        if name == current:
            marks.append("current")
        if spec.needs_key and missing_keys:
            marks.append("needs a key")
        if modules:
            marks.append(f"needs {', '.join(modules)}")
        suffix = f"   [{' · '.join(marks)}]" if marks else ""
        print(f"    {i}. {spec.label}{suffix}")
        print(f"       {spec.hint}")

    while True:
        answer = input(f"  Pick 1-{len(keys)} [{keys.index(current) + 1 if current in keys else 1}]: ").strip()
        if not answer:
            return current if current in keys else keys[0]
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        if answer in table:
            return answer
        print("  Not one of the options.")


def _collect_keys(specs: list, saved: dict) -> dict:
    """Ask for any secret the chosen providers need and we do not already have."""
    wanted: list[tuple[str, str]] = []
    for spec in specs:
        for key in spec.env_keys:
            if key not in [k for k, _ in wanted]:
                wanted.append((key, spec.docs))

    for key, docs in wanted:
        if os.environ.get(key) and key not in saved:
            print(f"\n  {key} is already set in your environment — leaving it alone.")
            continue
        if saved.get(key):
            keep = input(f"\n  {key} is already saved. Replace it? [n] ").strip().lower()
            if keep not in ("y", "yes"):
                continue
        if docs:
            print(f"\n  Get a key at {docs}")
        value = getpass.getpass(f"  {key} (hidden, blank to skip): ").strip()
        if value:
            saved[key] = value
            os.environ[key] = value
    return saved


def run() -> int:
    try:
        return _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled — nothing saved.")
        return 1


def _run() -> int:
    settings = config.load_settings()
    print("Mantrin setup — pick whose ears and whose voice.")
    print("Everything here is swappable later; nothing is locked in.")

    keys = settings.get("keys") or {}

    # The key is asked for the moment a choice needs one — pick Grok, hand over
    # the key, done. Deferring it to the end read as "it never asked me".
    stt = _choose("Speech to text (how Mantrin hears you)", registry.STT,
                  settings.get("stt") or registry.DEFAULT_STT)
    keys = _collect_keys([registry.STT[stt]], keys)

    tts = _choose("Text to speech (how Mantrin answers)", registry.TTS,
                  settings.get("tts") or registry.DEFAULT_TTS)
    keys = _collect_keys([registry.TTS[tts]], keys)

    settings["keys"] = keys
    settings["stt"], settings["tts"] = stt, tts

    if registry.STT[stt].mode != "text":
        default_wake = settings.get("wake_word", "hey_jarvis")
        print("\n  Wake word")
        print("    An always-on microphone needs a gate, or everything said near")
        print("    the machine gets transcribed. This runs locally — only speech")
        print("    after the wake word is sent anywhere.")
        answer = input(f"  Wake word, or 'none' to always listen [{default_wake or 'none'}]: ").strip()
        if answer.lower() == "none":
            settings["wake_word"] = ""
        elif answer:
            settings["wake_word"] = answer
        else:
            settings["wake_word"] = default_wake

    path = config.save_settings(settings)
    print(f"\nSaved to {path} (readable only by you).")

    # Report what still stands between this and a working conversation, now,
    # rather than as a mysterious silence on the first real run.
    problems = []
    for kind, name, table in (("STT", stt, registry.STT), ("TTS", tts, registry.TTS)):
        modules, missing = registry.requirements(table[name])
        if modules:
            problems.append(f"{kind} ({table[name].label}) needs: {', '.join(modules)}")
        if missing:
            problems.append(f"{kind} ({table[name].label}) still has no {', '.join(missing)}")

    if registry.STT[stt].mode != "text":
        reason = audio.probe()
        if reason:
            problems.append(f"Audio: {reason}")

    if problems:
        print("\nStill to do:")
        for p in problems:
            print(f"  - {p}")
        print("\n  Missing python packages: pip install -r requirements-voice.txt")
        return 1

    print("\nReady. Run `mantrin` and start talking.")
    return 0
