# Jarvis — v1

A personal AI companion that **remembers you across conversations**. Not a
passive recorder — you address it, it replies, and every session it knows you
a little better. This v1 exists to prove one thing: *memory compounds*.

> This is a scaffold. You launch it with a command today; the destination is
> an always-on presence you summon with "Jarvis". We build the brain first.

## What's here

```
jarvis/
  core/memory.py     # the moat — durable facts, each with its source. NOT rented.
  core/brain.py      # understanding — uses memory + reasons + decides what to learn
  providers/llm.py   # rented intelligence (Claude) behind a 1-method interface
  providers/stt.py   # rented ears (local Whisper) — voice mode
  providers/tts.py   # rented voice (local pyttsx3) — voice mode
  io/                # the skin: text today, voice next, phone later — same brain
```

Everything replaceable (LLM, STT, TTS) sits behind an interface. The only
thing we own outright is the memory + understanding.

## Run it (text mode — needs nothing but the API key)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # already set on this machine

./.venv/bin/python -m jarvis        # start talking; type 'exit' to leave
```

**See the bet in action:** tell it something in one run, exit, start it again —
it already knows.

```bash
./.venv/bin/python -m jarvis memory   # what it remembers, and WHY (provenance)
```

Memory lives in `data/memory.json` — open it, it's readable. Delete the file to
give Jarvis amnesia.

## Run it (voice mode — the real experience)

```bash
./.venv/bin/pip install -r requirements-voice.txt   # heavier: local Whisper + TTS
./.venv/bin/python -m jarvis --voice
```

Local-first: audio never leaves your machine. Swap to hosted STT/TTS later by
writing a new provider — the brain doesn't change.

## What v1 deliberately does NOT do yet

Always-on / wake word · real actions (tools) · proactivity · smart retrieval
(v1 loads all memories into the prompt) · confidence/decay/contradiction
handling · mobile. All of it layers on top of this core — later.
