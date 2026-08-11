---
title: Notion
description: Add to and query your Notion pages through Mantrin.
---

"Add this to my ideas page", "what's on the launch checklist?"

Notion's official *hosted* server — nothing runs on your machine, and there
is no key or token to create.

## Setup

```bash
mantrin connect notion
```

A browser opens: sign in to Notion and pick the pages Mantrin may see.
That's the whole setup.

:::note
The sign-in happens in a terminal once, via `mantrin connect` — the
always-on daemon is headless and can't open a browser. After that, the
token lives on your disk (`0600`) and refreshes itself.
:::
