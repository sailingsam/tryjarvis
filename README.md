# Mantrin

**Everyone deserves a chief of staff — your personal Jarvis.**

Mantrin (you'll also see it called Jarvis — that's the name it answers to, and
the name of the package inside) is a personal chief of staff you talk to. It
remembers your people, your promises and your plans across every conversation,
and then acts on them.

Not a recorder and not a chat window. You say something once; it holds onto it
and does something about it.

> **Status: beta.** It runs my day, every day — but it's young: Linux only for
> now, version 0.x, and things change without ceremony. If you're the kind of
> person who enjoys software at this stage, welcome; if you need boring and
> settled, check back in a few releases.

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
python3 -m venv .venv && source .venv/bin/activate
pip install "mantrin[voice]"
export ANTHROPIC_API_KEY=...
```

`[voice]` is the microphone layer. The heavy local providers install only if
you pick them: `mantrin setup` offers to fetch what your choices need, or grab
everything up front with `pip install "mantrin[all]"`. Working from a checkout
instead: `pip install -e ".[all]"` — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Talk to it

```bash
mantrin setup      # choose whose ears and voice; save any keys
mantrin            # then just say "hey jarvis"
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
mantrin --text        # keyboard in, text out
mantrin --dictate     # dictate with your own app, spoken reply
```

`--dictate` is for Wispr Flow's app, superwhisper, Willow and the rest. They own
the microphone and type into whatever has focus, so there is nothing to
integrate with — Mantrin reads the line and answers out loud.

### Swap providers

```bash
mantrin --stt grok --tts openai
mantrin --timings     # where each turn's time actually went
```

Settings live in `~/.config/mantrin/config.json` (mode 0600, it holds keys).
Anything in the environment wins over what is saved there.

Adding a provider is one class with one method, plus a line in
`providers/voice_registry.py`.

## See what it knows

```bash
mantrin memory        # every fact, and where it came from
mantrin commitments   # open loops it is tracking
mantrin brief         # a short daily brief
```

Memory is SQLite (`data/jarvis.db` in a checkout, `~/.local/share/mantrin/` when installed) — open it with `sqlite3` and you can read
everything it knows about you. Delete the file to give it amnesia.

## Integrations

WhatsApp, Slack, X — and anything with an MCP server — plug into the same tool
registry. Each is a block in `data/mcp.json` plus a key in the environment; a
block whose key isn't set yet just waits. See [docs/integrations.md](docs/integrations.md)
for what's wired and how to get each key.

## The daemon

`mantrin` starts a background daemon on first run and then talks to it. The
daemon is where Mantrin actually lives: it holds the microphone and keeps
integrations like WhatsApp connected, so messages are still captured when you are
not in a session and there is no terminal to keep open.

Only one process may hold those connections — two would mean two WhatsApp clients
on one set of credentials — which is why voice runs there rather than in the CLI.

```bash
mantrin daemon        # run it in the foreground to watch it
mantrin --no-voice    # don't hold the microphone
```

### Run at every login

```bash
mantrin install
```

On Linux this installs a systemd user service and puts a `mantrin` command on
your PATH: Mantrin starts when you log in, restarts if it crashes, and there is
no terminal to keep open. From then on the commands are ones a person can
remember — `mantrin status`, `mantrin logs`, `mantrin restart`, `mantrin stop`,
`mantrin uninstall`.

It also puts a status icon in the top bar (`mantrin tray`, auto-started at
login): green means listening for the wake word, blue means mid-conversation,
yellow starting, red something's wrong. The menu holds a **Mute microphone**
hard mute — the mic device is released (your OS's mic light goes out) and even
the wake word is ignored, while the brain and connections keep working.

## Contributing

Issues and PRs welcome — [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the
rules that matter (start with the Human PA Test), and how changes are reviewed.
The label [good first issue](https://github.com/sailingsam/tryjarvis/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
marks self-contained starting points. Big roadmap features (proactivity,
streaming voice) are being built by the maintainer — open an issue to discuss
before starting anything large.

## License

[FSL-1.1-ALv2](LICENSE.md) — use it, change it, run it for yourself or inside
your company, all free. The one thing you can't do is take this code and sell
it as your own product or hosted service. Every release becomes plain
Apache 2.0 two years after it ships.

## Not there yet

Proactivity — it answers when spoken to, and does not yet start conversations
itself. Reminders and anything on a schedule need a real scheduler, not a
language model. Auto-reply to messages waits on always-on being solid first.
Google and Slack need your sign-in. Streaming transcription is worth adding only
if `--timings` says it would help.
