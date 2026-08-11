---
title: Google Maps
description: Ask about places, travel time and weather through Mantrin.
---

"How long to the airport right now?"

Google's official hosted **Maps Grounding Lite** server — places, routes and
weather, straight from Google, nothing running locally.

## Setup

1. In a Google Cloud project, create (or reuse) a **Maps API key**
   ([console](https://console.cloud.google.com/google/maps-apis/credentials)).
2. Set it:

   ```bash
   export GOOGLE_MAPS_API_KEY=...
   ```

Or run `mantrin connect google-maps` for the guided version.
