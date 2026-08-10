---
title: WhatsApp
description: Send, receive, and search WhatsApp chats through Mantrin.
---

Send, receive, search chats — the flagship integration, and the project's
own (see
[whatsapp-bridge/](https://github.com/sailingsam/tryjarvis/tree/main/whatsapp-bridge)
on GitHub). No clone needed: the block in `mcp.example.json` runs it
straight from npm via `npx -y mantrin-whatsapp`.

## Setup

One-time pairing: run `npx -y mantrin-whatsapp` yourself once, scan the QR
with your phone, then `Ctrl+C`.

State (session, message database, logs) lives wherever
`WHATSAPP_MCP_DATA_DIR` points — the example config uses
`~/.local/share/mantrin/whatsapp`.

## What you can say

- "Anything from Priya today?"
- "Tell Rahul I'm running 10 minutes late."
