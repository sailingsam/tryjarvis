---
title: Integrations overview
description: Connect WhatsApp, Gmail, Calendar, Spotify, GitHub, and more.
---

WhatsApp, Gmail, Calendar, Spotify, GitHub, Notion, Home Assistant, X — and
anything with an MCP server — plug into the same tool registry.

```bash
mantrin connect            # list them all, with live status
mantrin connect spotify    # walks you through that one, end to end
```

The guided flow seeds the config block, opens the page where the key is
created, takes the key (hidden input, saved `0600`), restarts, and then
tells you whether the server actually came up.

Every integration is an MCP server under the hood: a block in `mcp.json`
(template: `jarvis/assets/mcp.example.json`) plus whatever key it needs in
the environment. A block whose key isn't set yet is skipped at startup and
lights up the day the key appears.

:::caution
Secrets go in the environment (or the project `.env`), never in `mcp.json`
itself. After adding a key by hand, run `mantrin restart`.
:::

The pages below are the by-hand steps for each integration, for anyone who
prefers doing it that way instead of `mantrin connect <service>`.

- [WhatsApp](/integrations/whatsapp/)
- [Google Calendar](/integrations/google-calendar/)
- [Gmail](/integrations/gmail/)
- [Notion](/integrations/notion/)
- [GitHub](/integrations/github/)
- [Home Assistant](/integrations/home-assistant/)
- [Spotify](/integrations/spotify/)
- [Weather](/integrations/weather/)
- [Google Maps](/integrations/google-maps/)
