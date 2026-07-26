# whatsapp-bridge

Jarvis's WhatsApp bridge — an MCP server over Baileys (unofficial WhatsApp Web
multi-device). Runs as an MCP server; Jarvis reaches it through the normal MCP
adapter. Auth is a one-time QR scan (`auth_info/`); chats/messages/contacts are
stored locally in `data/whatsapp.db`.

## Forked from
[`jlucaso1/whatsapp-mcp-ts`](https://github.com/jlucaso1/whatsapp-mcp-ts) (ISC).
We vendored and modified it because the upstream had gaps for our use:

- **Groups were dropped** — upstream set `shouldIgnoreJid: isJidGroup`, so no
  group ever synced. Removed; plus `syncGroups()` pulls every participating
  group with its real subject on connect.
- **Full history** — added `syncFullHistory: true`.
- **Names** — sender `pushName` is now captured into `contacts.notify`, so
  @lid chats resolve to real names (upstream left them blank).
- **Send to groups** — group JIDs (`@g.us`) are no longer run through
  `jidNormalizedUser` (that mangled them).

## Run standalone (for the one-time QR auth)
```bash
node src/main.ts   # scan the QR with the dedicated number, then Ctrl+C
```
Then Jarvis (or its daemon) launches it automatically via `data/mcp.json`.
