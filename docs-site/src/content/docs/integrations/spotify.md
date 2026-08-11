---
title: Spotify
description: Control playback through Mantrin.
---

"Put on something quiet", "skip this one."

## Setup

```bash
mantrin connect spotify
```

The guided flow is the way here, because Spotify needs two things and only
one of them is a key:

1. **App credentials** — it opens
   [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard);
   create an app with redirect URI exactly `http://127.0.0.1:8080/callback`,
   paste the Client ID and Secret.
2. **Your account's one-time sign-in** — a browser opens for Spotify's
   consent page. This step can't happen inside the headless daemon, which is
   why setting the environment variables by hand isn't enough on its own.

:::caution
Playback control needs Spotify Premium, and something (a phone, the desktop
app, an `open.spotify.com` tab) has to be an *active device* — Mantrin is a
remote control, not a speaker. It plays wherever Spotify is already awake.
:::
