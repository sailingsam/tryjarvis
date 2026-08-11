---
title: Logs & the daemon
description: How the always-on Mantrin daemon works, and how to check on it.
---

`mantrin` starts a background daemon on first run and then talks to it. The
daemon is where Mantrin actually lives: it holds the microphone and keeps
integrations like WhatsApp connected, so messages are still captured when
you are not in a session and there is no terminal to keep open.

Only one process may hold those connections — two would mean two WhatsApp
clients on one set of credentials — which is why voice runs there rather
than in the CLI.

```bash
mantrin daemon        # run it in the foreground to watch it
mantrin --no-voice    # don't hold the microphone
```

## Checking on it

```bash
mantrin status     # is it running, is everything connected
mantrin logs       # tail the daemon's logs
```

## After installing as a service

```bash
mantrin install
```

installs a systemd user service: Mantrin starts when you log in, restarts
if it crashes, and there is no terminal to keep open. From then on:

```bash
mantrin status
mantrin logs
mantrin restart    # e.g. after adding an integration key by hand
mantrin stop
mantrin uninstall
```

`mantrin restart` and `mantrin start` print success only when it is true —
they wait for the daemon to answer and the voice to declare itself, and if
the voice comes up broken they print why, right there.

It also puts a status icon in the top bar (`mantrin tray`): green means
ready, blue mid-conversation, yellow starting, red something's wrong, grey
muted or stopped. The tray menu holds a **Mute microphone** hard mute — the
mic device is released (your OS's own mic light goes out) and even the wake
word is ignored, while the brain and connections keep working. Once a talk
key is set (`mantrin set-key`), a **Listen for** submenu switches between
wake word, talk key, or both.
