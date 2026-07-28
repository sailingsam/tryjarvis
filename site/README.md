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

## The call to action

Both CTAs ("Book a call") link to `https://cal.com/sailingsam`. No email capture
and no backend, deliberately: pre-launch, a conversation is worth more than a
row in a table. To change where it points, edit the two `.cta` hrefs.

## What's on the page

1. **Hero** — the role, plus a live diagram: you speak to one device, the one
   mind hears it, and every other device ends up knowing.
2. **Dark band** — the positioning: everyone is building AI tools; this is the
   one who uses them for you.
3. **Say it once** — the said → remembered → done demo, then Remembers /
   Understands / Acts with a memory-compounds visual.
4. **It doesn't wait to be asked** — proactivity, and asking before acting.
5. **man·trin** — a type specimen explaining the name for people outside India.
6. **Close** — the invitation.

## Notes

- Content renders without JavaScript; JS only drives motion (the constellation
  cycle, the ambient motes, translate-only reveals). Honours
  `prefers-reduced-motion`, and pauses when the tab is hidden.
- Hero fits one screen down to ~700px tall viewports.
- Colours are OKLCH: white surfaces, one amber accent, one drenched dark band.
- Background is three light layers: drifting "memory" motes on a canvas, a soft
  amber presence aura, and a fine grain so the white reads as paper.
