# Integrations

Every integration is an MCP server: a block in `data/mcp.json` (start from
`mcp.example.json`) plus whatever key it needs in the environment. A block whose
key isn't set yet is skipped at startup and lights up the day the key appears —
so all of these can sit in your config from day one.

Secrets go in the environment (or the project `.env`), never in `mcp.json`
itself. After adding a key, restart the daemon: `./.venv/bin/python -m jarvis daemon`.

## Google Calendar

"What's on today?", "block Thursday 4pm with Ria."

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or reuse one) and enable the **Google Calendar API**.
2. Create an **OAuth client ID** of type *Desktop app* and download its JSON.
3. Point the environment at it:

   ```bash
   export GOOGLE_OAUTH_CREDENTIALS=/path/to/gcp-oauth.keys.json
   ```

First use opens a browser once to sign in; the token is cached after that.

## Gmail

"Anything important in my inbox?", "reply that I'll confirm tonight."

Reuses the same Google Cloud OAuth client as Calendar (enable the **Gmail API**
on it too). This server keeps its credentials in `~/.gmail-mcp/`:

```bash
mkdir -p ~/.gmail-mcp
cp /path/to/gcp-oauth.keys.json ~/.gmail-mcp/
npx -y @gongrzhe/server-gmail-autoauth-mcp auth   # one-time browser sign-in
```

No environment variable needed after that. Until you run the auth step, the
server fails to start and the daemon carries on without it.

## Notion

"Add this to my ideas page", "what's on the launch checklist?"

1. Create an internal integration at
   [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
   and copy its secret.
2. In Notion, share the pages/databases it should see with that integration
   (page ⋯ menu → Connections).
3. `export NOTION_TOKEN=ntn_...`

## GitHub

"Any reviews waiting on me?", "what broke in CI overnight?"

Runs GitHub's official server in Docker (needs Docker installed).

1. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens)
   scoped to the repos you care about.
2. `export GITHUB_PAT=github_pat_...`

The full server exposes ~80 tools, which drowns the model's tool menu —
`GITHUB_TOOLSETS` in the block trims it to the chief-of-staff set (repos,
issues, PRs, notifications). Widen it if you need more.
