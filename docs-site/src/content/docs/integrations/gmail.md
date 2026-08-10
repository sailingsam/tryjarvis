---
title: Gmail
description: Read and reply to email through Mantrin.
---

"Anything important in my inbox?", "reply that I'll confirm tonight."

## Setup

Reuses the same Google Cloud OAuth client as
[Calendar](/integrations/google-calendar/) — enable the **Gmail API** on it
too. This server keeps its credentials in `~/.gmail-mcp/`:

```bash
mkdir -p ~/.gmail-mcp
cp /path/to/gcp-oauth.keys.json ~/.gmail-mcp/
npx -y @gongrzhe/server-gmail-autoauth-mcp auth   # one-time browser sign-in
```

No environment variable is needed after that. Until you run the auth step,
the server fails to start and the daemon carries on without it.
