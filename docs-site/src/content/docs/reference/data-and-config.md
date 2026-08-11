---
title: Config & data locations
description: Where Mantrin keeps its settings and memory.
---

## Settings

Settings live in `~/.config/mantrin/config.json` (mode `0600`, since it
holds keys). Anything set in the environment wins over what is saved there.

## Memory

Memory is SQLite:

- `data/jarvis.db` in a checkout
- `~/.local/share/mantrin/` when installed via `pip`

Open it directly with `sqlite3` and you can read everything Mantrin knows
about you. Delete the file to give it amnesia.

## The data directory

Everything else lives next to the memory, in the same data directory
(`data/` in a checkout, `~/.local/share/mantrin/` installed):

- `mcp.json` — which integrations are configured
- `mcp-<name>.log` — each local server's own chatter, out of your way
  until something breaks
- `oauth/<name>.json` — sign-in tokens for hosted servers (mode `0600`,
  self-refreshing; delete one to sign out)
- `state.json` and the mute flag — how the daemon and the tray icon talk

Settings saved by `mantrin setup` and `mantrin set-key` (providers, keys,
the talk key and trigger mode) live in `~/.config/mantrin/config.json`.

## Integration state

Each integration keeps its own state under its configured data directory —
for example WhatsApp's session, message database and logs live wherever
`WHATSAPP_MCP_DATA_DIR` points (see [WhatsApp](/integrations/whatsapp/)).
