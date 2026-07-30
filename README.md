# Mantrin

A personal chief of staff you talk to. It remembers your people, your promises
and your plans across every conversation, and then acts on them.

Not a recorder and not a chat window. You say something once; it holds onto it
and does something about it.

## What's here

```
jarvis/
  core/memory.py       # the moat — durable facts with provenance. Not rented.
  core/brain.py        # understanding: reply, then decide what was worth learning
  audio.py             # mic, endpointing, playback — shared by every voice provider
  wake.py              # the wake word, running locally
  daemon.py            # the always-on process: holds the mic and the connections
  providers/llm.py     # rented intelligence (Claude) behind one interface
  providers/stt.py     # rented ears — local Whisper, OpenAI, Grok, or your own app
  providers/tts.py     # rented voice — local Piper, OpenAI, Grok
  providers/voice_registry.py   # the table of what you can pick, and what it needs
  tools/               # real actions: web, X, and any MCP server
  io/                  # the skin: voice or text, same brain either way
```

Everything replaceable sits behind an interface — the language model, the ears,
the voice, the memory store. What we own outright is the memory and the
understanding built on it.

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
```

## Talk to it

```bash
./.venv/bin/pip install -r requirements-voice.txt
./.venv/bin/python -m jarvis setup      # choose whose ears and voice; save any keys
./.venv/bin/python -m jarvis            # then just say "hey jarvis"
```

The default stack is free and entirely local — Whisper for hearing, Piper for
speaking, openWakeWord for the wake word. Nothing you say leaves the machine
until you choose a hosted provider.

There is no button and no time limit: it works out that you stopped talking by
listening. Interrupt it mid-sentence and it stops, like a person would. After it
answers it keeps listening for a few seconds, so a back-and-forth doesn't need
the wake word every time.

### Type instead

```bash
./.venv/bin/python -m jarvis --text        # keyboard in, text out
./.venv/bin/python -m jarvis --dictate     # dictate with your own app, spoken reply
```

`--dictate` is for Wispr Flow's app, superwhisper, Willow and the rest. They own
the microphone and type into whatever has focus, so there is nothing to
integrate with — Mantrin reads the line and answers out loud.

### Swap providers

```bash
./.venv/bin/python -m jarvis --stt grok --tts openai
./.venv/bin/python -m jarvis --timings     # where each turn's time actually went
```

Settings live in `~/.config/mantrin/config.json` (mode 0600, it holds keys).
Anything in the environment wins over what is saved there.

Adding a provider is one class with one method, plus a line in
`providers/voice_registry.py`.

## See what it knows

```bash
./.venv/bin/python -m jarvis memory        # every fact, and where it came from
./.venv/bin/python -m jarvis commitments   # open loops it is tracking
./.venv/bin/python -m jarvis brief         # a short daily brief
```

Memory is SQLite at `data/jarvis.db` — open it with `sqlite3` and you can read
everything it knows about you. Delete the file to give it amnesia.

## The daemon

`mantrin` starts a background daemon on first run and then talks to it. The
daemon is where Mantrin actually lives: it holds the microphone and keeps
integrations like WhatsApp connected, so messages are still captured when you are
not in a session and there is no terminal to keep open.

Only one process may hold those connections — two would mean two WhatsApp clients
on one set of credentials — which is why voice runs there rather than in the CLI.

```bash
./.venv/bin/python -m jarvis daemon        # run it in the foreground to watch it
./.venv/bin/python -m jarvis --no-voice    # don't hold the microphone
```

## Not there yet

Proactivity — it answers when spoken to, and does not yet start conversations
itself. Reminders and anything on a schedule need a real scheduler, not a
language model. Auto-reply to messages waits on always-on being solid first.
Google and Slack need your sign-in. Streaming transcription is worth adding only
if `--timings` says it would help.
