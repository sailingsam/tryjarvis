---
title: Installation
description: Install Mantrin and run it for the first time.
---

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "mantrin[voice]"
export ANTHROPIC_API_KEY=...
```

`[voice]` is the microphone layer. The heavy local providers install only if
you pick them: `mantrin setup` offers to fetch what your choices need, or
grab everything up front with `pip install "mantrin[all]"`.

:::note
Working from a checkout instead of a package install? Use
`pip install -e ".[all]"` — see
[CONTRIBUTING.md](https://github.com/sailingsam/tryjarvis/blob/main/CONTRIBUTING.md).
:::

## First run

```bash
mantrin setup      # choose whose ears and voice; save any keys
mantrin            # then just say "hey jarvis"
```

The default stack is free and entirely local — Whisper for hearing, Piper
for speaking, openWakeWord for the wake word. Nothing you say leaves the
machine until you choose a hosted provider.

## Run at every login

```bash
mantrin install
```

On Linux this installs a systemd user service and puts a `mantrin` command
on your PATH: Mantrin starts when you log in, restarts if it crashes, and
there is no terminal to keep open. From then on, see
[Commands](/reference/commands/) for `status`, `logs`, `restart`, `stop`.

It also puts a status icon in the top bar (`mantrin tray`, auto-started at
login): green means ready (listening for the wake word, or waiting for your
[talk key](/talking-to-it/#push-to-talk)), blue means mid-conversation,
yellow starting, red something's wrong, grey muted or stopped.

## Next

- [Talking to Mantrin](/talking-to-it/)
- [Connecting your accounts](/integrations/)
