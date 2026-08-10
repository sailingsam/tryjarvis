---
title: Spotify
description: Control playback through Mantrin.
---

"Put on something quiet", "skip this one."

## Setup

1. Create an app at
   [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   with redirect URI `http://127.0.0.1:8080/callback`.
2. Set the credentials:

   ```bash
   export SPOTIFY_CLIENT_ID=...
   export SPOTIFY_CLIENT_SECRET=...
   ```

:::caution
Playback control needs Spotify Premium, and something (a phone, the desktop
app) has to be an active device.
:::
