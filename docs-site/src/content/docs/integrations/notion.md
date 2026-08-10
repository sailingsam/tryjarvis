---
title: Notion
description: Add to and query your Notion pages through Mantrin.
---

"Add this to my ideas page", "what's on the launch checklist?"

## Setup

1. Create an internal integration at
   [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
   and copy its secret.
2. In Notion, share the pages/databases it should see with that integration
   (page **⋯** menu → **Connections**).
3. Set the token:

   ```bash
   export NOTION_TOKEN=ntn_...
   ```
