"""First-run setup: choose ears and a voice, hand over any keys needed.

The first thing someone does with Mantrin is run it in a terminal, and the first
question it has to answer is whose speech services to use. Asking once and
remembering is better than a README telling people which environment variables
to export.

The wizard installs nothing behind your back: when a chosen provider needs a
python package that isn't there, it names the exact packages and asks before
running pip. Decline, and the summary at the end still prints the command to
run yourself. Either way a failure names itself instead of turning up later
as silence.

Dependencies are choice-sized on purpose (see pyproject's extras): someone on
hosted ears and a hosted voice never downloads a local model runtime.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys

from . import audio, config, wake
from .providers import voice_registry as registry


def _offer_install(label: str, modules: list[str]) -> None:
    """Something chosen needs packages that aren't there — offer to fetch
    them now, by name, with consent. Nobody should finish setup and meet an
    ImportError as their first conversation."""
    if not modules:
        return
    packages = registry.pip_packages(modules)
    print(f"\n  {label} needs: {', '.join(packages)} (this can be a large download)")
    answer = input("  Install now with pip? [Y/n] ").strip().lower()
    if answer in ("n", "no"):
        return
    result = subprocess.run([sys.executable, "-m", "pip", "install", *packages])
    if result.returncode != 0:
        print("  (pip failed — the summary below will name what's still missing)")


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


def _choose_wake_word(current: str) -> str:
    """Pick a wake phrase from what can actually be detected.

    Free text here burned a user: they typed "jarvis", no model by that name
    exists, and the gate silently fell open. Detection needs a trained model
    per phrase, so the menu offers exactly the phrases that have one — plus
    off, which at least is an *informed* open door.
    """
    phrases = wake.available_phrases()
    print("\n  Wake word")
    print("    An always-on microphone needs a gate, or everything said near")
    print("    the machine gets transcribed (and billed, on hosted ears). The")
    print("    gate runs locally. Each phrase needs a trained model, so the")
    print("    choices are the models that exist:")
    if not phrases:
        print("    (openwakeword is not installed — no gate is possible yet;")
        print("     pip install openwakeword, then rerun setup)")
        return current
    options = phrases + ["off — always listen (everything gets transcribed)"]
    for i, name in enumerate(options, 1):
        pretty = name if name.startswith("off") else f"“{name.replace('_', ' ')}”"
        mark = "   [current]" if name == current or (name.startswith("off") and not current) else ""
        print(f"    {i}. {pretty}{mark}")
    while True:
        default = phrases.index(current) + 1 if current in phrases else len(options) if not current else 1
        answer = input(f"  Pick 1-{len(options)} [{default}]: ").strip()
        if not answer:
            answer = str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            picked = options[int(answer) - 1]
            return "" if picked.startswith("off") else picked
        if answer.lower() in ("none", "off"):
            return ""
        # Typed a name — or several, comma-separated ("mantrin, jarvis"):
        # the gate answers to any of them.
        parts = [p.strip() for p in answer.split(",") if p.strip()]
        resolved = [wake.resolve(p) for p in parts]
        if parts and all(resolved):
            return ",".join(dict.fromkeys(resolved))    # dedupe, keep order
        print("  Not one of the options.")


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
    _offer_install(registry.STT[stt].label, registry.requirements(registry.STT[stt])[0])

    tts = _choose("Text to speech (how Mantrin answers)", registry.TTS,
                  settings.get("tts") or registry.DEFAULT_TTS)
    keys = _collect_keys([registry.TTS[tts]], keys)
    _offer_install(registry.TTS[tts].label, registry.requirements(registry.TTS[tts])[0])

    # The mic layer rides under every audio provider — hosted ears still need
    # endpointing and the wake word running locally.
    if registry.STT[stt].mode != "text":
        _offer_install("The microphone layer (endpointing + wake word)",
                       registry.missing_voice_layer())

    settings["keys"] = keys
    settings["stt"], settings["tts"] = stt, tts

    if registry.STT[stt].mode != "text":
        settings["wake_word"] = _choose_wake_word(settings.get("wake_word", wake.DEFAULT_PHRASE))
        from . import hotkey
        hotkey.offer_in_wizard(settings)

    path = config.save_settings(settings)
    print(f"\nSaved to {path} (readable only by you).")

    # Report what still stands between this and a working conversation, now,
    # rather than as a mysterious silence on the first real run.
    problems = []
    still_missing: list[str] = []
    for kind, name, table in (("STT", stt, registry.STT), ("TTS", tts, registry.TTS)):
        modules, missing = registry.requirements(table[name])
        still_missing += [m for m in modules if m not in still_missing]
        if modules:
            problems.append(f"{kind} ({table[name].label}) needs: {', '.join(modules)}")
        if missing:
            problems.append(f"{kind} ({table[name].label}) still has no {', '.join(missing)}")
    if registry.STT[stt].mode != "text":
        still_missing += [m for m in registry.missing_voice_layer() if m not in still_missing]

    if registry.STT[stt].mode != "text":
        reason = audio.probe()
        if reason:
            problems.append(f"Audio: {reason}")

    if problems:
        print("\nStill to do:")
        for p in problems:
            print(f"  - {p}")
        if still_missing:
            print(f"\n  Missing python packages: "
                  f"pip install {' '.join(registry.pip_packages(still_missing))}")
        return 1

    print("\nReady. Run `mantrin` and start talking.")
    print("Integrations (WhatsApp, Calendar, Spotify…): `mantrin connect` lists "
          "them, `mantrin connect <name>` walks you through one.")
    return 0
