# Mantrin brand assets

All PNGs have transparent backgrounds. The source of truth is
[`../site/logo.svg`](../site/logo.svg) — regenerate from it rather than editing
the PNGs.

## The mark

One mind at the centre, the things you speak to around it — the same idea the
hero diagram on the site animates.

| File | Use |
|---|---|
| `mantrin-mark-1024.png` | print, decks, anything that gets scaled down |
| `mantrin-mark-512.png` | app icons, social avatars |
| `mantrin-mark-256.png` | general web use |
| `mantrin-mark-128.png` / `-64` / `-32` | small UI, favicons |

## The lockup (mark + wordmark)

| File | Use |
|---|---|
| `mantrin-lockup.png` | on light backgrounds |
| `mantrin-lockup-onDark.png` | on dark backgrounds |

## LinkedIn

| File | Size | Where |
|---|---|---|
| `linkedin-page-banner.png` | 2256×382 (2× of 1128×191) | company page cover |
| `linkedin-profile-banner.png` | 3168×792 (2× of 1584×396) | personal profile cover |

Both keep the left ~40% empty on purpose. LinkedIn overlays the page logo (or
your profile photo) on the bottom-left, and on **mobile that overlay is much
bigger** — it reaches roughly 4%–31% of the width and covers the bottom half of
the banner. Text sits entirely to the right of it, and the secondary line is
sized to still be readable on a phone.

Checked against mocks of both the desktop and mobile layouts. If you change the
copy, keep it right of ~40% and re-check on a phone.

## Colours

| Role | Value |
|---|---|
| Amber (the mark) | `#d99a2b` — `oklch(0.74 0.155 72)` |
| Ink (wordmark on light) | `#1a1512` |
| Paper (wordmark on dark) | `#fbf8f4` |

Wordmark type is **Spectral Light (300)**.

## Regenerating

```bash
# mark, any size
google-chrome --headless=new --default-background-color=00000000 \
  --window-size=512,512 --screenshot=brand/mantrin-mark-512.png \
  "file://$PWD/site/logo.svg"
```

The lockup is rendered from a small HTML wrapper so the webfont loads; see the
commit that added these files.
