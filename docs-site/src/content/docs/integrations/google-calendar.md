---
title: Google Calendar
description: Ask about your schedule and hold time on your calendar.
---

"What's on today?", "block Thursday 4pm with Ria."

## Setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or reuse one) and enable the **Google Calendar API**.
2. Create an **OAuth client ID** of type *Desktop app* and download its JSON.
3. Point the environment at it:

   ```bash
   export GOOGLE_OAUTH_CREDENTIALS=/path/to/gcp-oauth.keys.json
   ```

First use opens a browser once to sign in; the token is cached after that.
`mantrin connect google-calendar` walks the same steps for you.

:::note
This is the same OAuth client used by [Gmail](/integrations/gmail/) — enable
both APIs on one project if you want both integrations.
:::

:::note
Google ships an official *hosted* Calendar MCP server, and Mantrin already
speaks to it — but it currently sits behind Google's Workspace Developer
Preview Program, which doesn't accept personal Gmail accounts. The day it
goes GA, this page shrinks to "sign in in your browser".
:::
