"""Draws the mascot's faces — run once, commit the PNGs.

The character is the brand mark come alive: an amber body (the mind at the
centre) with an antenna node on top, and when it thinks, the satellites from
the logo orbit its head. Everything is drawn on a 40x40 pixel grid and scaled
up with nearest-neighbour, because the crunchy pixel look is the point — it
reads as "friendly little machine", not "corporate blob".

    python jarvis/assets/mascot/generate.py

Needs Pillow (dev-time only; the PNGs ship, this script doesn't).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

GRID = 40                      # design canvas, in pixels
SCALE = 4                      # shipped size: 160x160
OUT = Path(__file__).resolve().parent

AMBER = (217, 154, 43, 255)    # brand #d99a2b
DARK = (160, 111, 24, 255)     # outline
GLOW = (232, 181, 88, 255)     # highlight / arcs
INK = (26, 21, 18, 255)        # brand #1a1512 — face
PAPER = (251, 248, 244, 255)   # brand #fbf8f4 — eye shine
SLEEPY = (190, 137, 44, 255)   # body when asleep — lights dimmed

# Body geometry, shared by every face so the character never "jumps"
# between states: circle centred on (20, 23), antenna rising to (20, 7).
BODY = (9, 12, 31, 34)
CX = 20


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (GRID, GRID), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _body(d: ImageDraw.ImageDraw, fill=AMBER, antenna=True, ball=GLOW) -> None:
    if antenna:
        d.line([(CX, 12), (CX, 8)], fill=DARK, width=2)
        d.ellipse((CX - 2, 5, CX + 2, 9), fill=ball, outline=DARK)
    d.ellipse(BODY, fill=fill, outline=DARK, width=1)
    # one soft highlight, upper-left — makes the sphere read as a sphere
    d.arc((12, 15, 28, 31), start=200, end=250, fill=GLOW, width=2)


def _eyes(d: ImageDraw.ImageDraw, dy: int = 0, dx: int = 0, wide: bool = False) -> None:
    """Two tall pupils with a light in each. `wide` is the listening face."""
    w = 2 if wide else 1
    for ex in (15, 25):
        d.rectangle((ex - w + dx, 20 + dy, ex + w + dx, 24 + dy), fill=INK)
        d.point((ex - w + 1 + dx, 21 + dy), fill=PAPER)


def _smile(d: ImageDraw.ImageDraw) -> None:
    d.arc((16, 24, 24, 29), start=25, end=155, fill=INK, width=1)


def idle() -> Image.Image:
    img, d = _canvas()
    _body(d)
    _eyes(d)
    _smile(d)
    return img


def sleeping() -> Image.Image:
    img, d = _canvas()
    _body(d, fill=SLEEPY, ball=SLEEPY)
    for ex in (15, 25):                      # closed lids
        d.line([(ex - 2, 22), (ex + 2, 22)], fill=INK, width=1)
    d.line([(17, 27), (23, 27)], fill=INK, width=1)
    for x, y, s in ((29, 8, 3), (34, 3, 4)):  # z, Z
        d.line([(x, y), (x + s, y)], fill=DARK, width=1)
        d.line([(x + s, y), (x, y + s)], fill=DARK, width=1)
        d.line([(x, y + s), (x + s, y + s)], fill=DARK, width=1)
    return img


def waking() -> Image.Image:
    img, d = _canvas()
    _body(d)
    for ex in (15, 25):                      # half-open lids
        d.rectangle((ex - 1, 22, ex + 1, 24), fill=INK)
        d.line([(ex - 2, 21), (ex + 2, 21)], fill=INK, width=1)
    d.line([(18, 27), (22, 27)], fill=INK, width=1)
    return img


def listening() -> Image.Image:
    img, d = _canvas()
    _body(d)
    _eyes(d, wide=True)
    _smile(d)
    for box in ((1, 14, 9, 32), (31, 14, 39, 32)):   # sound reaching both ears
        d.arc(box, start=115, end=245, fill=GLOW, width=2) if box[0] == 1 else \
            d.arc(box, start=295, end=65, fill=GLOW, width=2)
    return img


def thinking() -> Image.Image:
    img, d = _canvas()
    _body(d, antenna=False)
    _eyes(d, dy=-2, dx=1)                    # eyes drift up with the thought
    d.line([(18, 27), (22, 27)], fill=INK, width=1)
    # the logo's satellites, orbiting the head while it works
    for x, y, r in ((9, 7, 1), (20, 3, 2), (31, 7, 1)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=GLOW, outline=DARK)
    return img


def speaking() -> Image.Image:
    img, d = _canvas()
    _body(d)
    _eyes(d)
    d.ellipse((17, 25, 23, 30), fill=INK)    # mouth open mid-word
    d.point((19, 26), fill=PAPER)
    for box in ((30, 19, 35, 29), (33, 16, 39, 32)):  # voice leaving, stage right
        d.arc(box, start=300, end=60, fill=GLOW, width=1)
    return img


def error() -> Image.Image:
    img, d = _canvas()
    _body(d, ball=(200, 80, 60, 255))        # the node blushes red
    for ex in (15, 25):                      # x_x
        d.line([(ex - 2, 20), (ex + 2, 24)], fill=INK, width=1)
        d.line([(ex + 2, 20), (ex - 2, 24)], fill=INK, width=1)
    d.line([(17, 28), (19, 26), (21, 28), (23, 26)], fill=INK, width=1)
    return img


FACES = {
    "idle": idle, "sleeping": sleeping, "waking": waking,
    "listening": listening, "thinking": thinking,
    "speaking": speaking, "error": error,
}

if __name__ == "__main__":
    for name, draw in FACES.items():
        img = draw().resize((GRID * SCALE, GRID * SCALE), Image.NEAREST)
        img.save(OUT / f"{name}.png")
        print(f"  {name}.png")
