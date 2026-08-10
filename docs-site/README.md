# Mantrin docs

A [Starlight](https://starlight.astro.build) site, themed to match
[the landing page](../site/) — same OKLCH amber accent, same fonts. Content
lives as Markdown/MDX under `src/content/docs/`; the nav structure is in
`astro.config.mjs`.

```bash
npm install
npm run dev      # localhost:4321
npm run build    # static output in dist/
```

## Deploy

Same pattern as `site/`: it's a static build, so drop `dist/` on any static
host (Netlify / Vercel / Cloudflare Pages / GitHub Pages) and point
`docs.tryjarvis.in` at it with the CNAME they give you.
