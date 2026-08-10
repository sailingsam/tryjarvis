---
title: Commands
description: Every mantrin command and flag.
---

## Everyday

| Command | What it does |
|---|---|
| `mantrin` | Start (or attach to) the daemon and begin listening. |
| `mantrin setup` | Choose your STT/TTS providers and save any keys. |
| `mantrin set-key` | Bind a push-to-talk key. |
| `mantrin --text` | Keyboard in, text out — no microphone. |
| `mantrin --dictate` | Read a line from your own dictation app, reply out loud. |
| `mantrin --stt <name>` / `--tts <name>` | Swap providers for this run (e.g. `grok`, `openai`). |
| `mantrin --no-voice` | Don't hold the microphone. |
| `mantrin --timings` | Print where each turn's time actually went. |

## What it knows

| Command | What it does |
|---|---|
| `mantrin memory` | Every fact it holds, and where it came from. |
| `mantrin commitments` | Open loops it is tracking. |
| `mantrin brief` | A short daily brief. |

## Integrations

| Command | What it does |
|---|---|
| `mantrin connect` | List every integration, with live status. |
| `mantrin connect <service>` | Guided connect: opens the key page, takes the key, verifies. |

## The daemon and the service

| Command | What it does |
|---|---|
| `mantrin daemon` | Run the daemon in the foreground, to watch it. |
| `mantrin install` | Install the systemd user service; start at every login. |
| `mantrin status` | Is it running, and is everything connected. |
| `mantrin logs` | Tail the daemon's logs. |
| `mantrin restart` | Restart the daemon (e.g. after adding a key by hand). |
| `mantrin stop` | Stop the daemon. |
| `mantrin uninstall` | Remove the systemd service. |
| `mantrin tray` | The status-icon tray app (auto-started by `install`). |

See [Logs & the daemon](/reference/logs-and-daemon/) for what each daemon
command actually does under the hood.
