# Mantrin landing page

Single self-contained file: `index.html` (HTML + CSS + JS inline, no build step,
no dependencies beyond Google Fonts). Drop it on any static host.

## Deploy to tryjarvis.in

Pick whichever is easiest:

- **Netlify / Vercel / Cloudflare Pages** — drag the `site/` folder into their
  dashboard, then point `tryjarvis.in` at it in the DNS settings they give you.
- **GitHub Pages** — push `site/` as the pages source, add `tryjarvis.in` as the
  custom domain.
- **Any cPanel / VPS** — upload `index.html` to the web root.

## Waitlist

The form currently posts to `mailto:hello@tryjarvis.in`, which opens the
visitor's mail client. That's a placeholder. For real capture, swap the
`<form action>` for a form service (Tally, Formspree, Buttondown) — one
attribute change, no other edits needed.

## Notes

- Content is visible without JavaScript; JS only adds motion (a slow breathing
  "presence" canvas and translate-only reveals). Respects
  `prefers-reduced-motion`.
- Hero is sized to fit one screen down to ~700px tall viewports.
- Colors are OKLCH; the single accent is the gold used for the presence mark.
