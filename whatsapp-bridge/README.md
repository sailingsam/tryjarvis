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

## Run it

Published on npm as `mantrin-whatsapp` — no clone needed:

```bash
npx -y mantrin-whatsapp    # scan the QR with the dedicated number, then Ctrl+C
```

From a checkout it's `node src/main.ts` instead. Either way, Jarvis (or its
daemon) launches it automatically afterwards via `data/mcp.json` — see the
`whatsapp` block in `mcp.example.json`.

## Where its state lives

Set `WHATSAPP_MCP_DATA_DIR` and everything — `whatsapp.db`, `auth_info/`,
logs — lands there. Mantrin's example config points it at
`~/.local/share/mantrin/whatsapp`. Unset, state sits next to the source,
which is right for a checkout and wrong under npx (npm's cache is not a
home for your WhatsApp session).
