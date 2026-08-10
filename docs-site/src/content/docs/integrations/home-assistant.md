---
title: Home Assistant
description: Control lights, locks, and more through Mantrin.
---

"Turn off the bedroom lights", "is the front door locked?" — the Iron Man
part.

Home Assistant speaks MCP over SSE; `mcp-proxy` (run via `uvx`, so it needs
[uv](https://docs.astral.sh/uv/) installed) bridges that to the stdio the
client speaks.

## Setup

1. In Home Assistant: **Settings → Devices & services → Add integration →
   Model Context Protocol Server**.
2. In your HA profile, create a long-lived access token.
3. Set the token and fix the URL in the `mcp.json` block if your HA isn't at
   `homeassistant.local:8123`:

   ```bash
   export HASS_TOKEN=...
   ```
