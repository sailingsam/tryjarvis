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

`mantrin connect gmail` does all of the above for you — it takes the path
to the downloaded JSON and runs the sign-in.

:::note
Google ships an official *hosted* Gmail MCP server, and Mantrin already
speaks to it — but it currently sits behind Google's Workspace Developer
Preview Program, which doesn't accept personal Gmail accounts. The day it
goes GA, this page shrinks to "sign in in your browser".
:::
