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
