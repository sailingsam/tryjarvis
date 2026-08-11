---
title: GitHub
description: Check reviews, issues, and CI status through Mantrin.
---

"Any reviews waiting on me?", "what broke in CI overnight?"

GitHub's official *hosted* server — nothing runs on your machine, no Docker,
nothing to install.

## Setup

1. Create a
   [fine-grained personal access token](https://github.com/settings/personal-access-tokens)
   scoped to the repos you care about.
2. Set it:

   ```bash
   export GITHUB_PAT=github_pat_...
   ```

Or just run `mantrin connect github` — it opens that page, takes the token,
and verifies the connection.

:::note
The full server exposes ~80 tools, which drowns the model's tool menu — the
`X-MCP-Toolsets` header in the `mcp.json` block trims it to the
chief-of-staff set (repos, issues, PRs, notifications). Widen it if you need
more.
:::
