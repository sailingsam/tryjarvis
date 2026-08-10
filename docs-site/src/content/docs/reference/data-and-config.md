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

## Integration state

Each integration keeps its own state under its configured data directory —
for example WhatsApp's session, message database and logs live wherever
`WHATSAPP_MCP_DATA_DIR` points (see [WhatsApp](/integrations/whatsapp/)).
