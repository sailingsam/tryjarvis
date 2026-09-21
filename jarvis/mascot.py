"""The mascot — Mantrin's face on the desktop.

A small pixel creature that floats above every window and simply *shows* what
the daemon feels: asleep when muted, ears up when hearing you, satellites
orbiting while it thinks. Click it and the mic mutes (it visibly falls
asleep); drag it anywhere and it stays there. When an action needs your OK,
a card unfolds next to it with the full text — so the voice can stop reading
whole drafts aloud and just say "it's on your screen".

How it floats above everything on GNOME Wayland, where apps are not allowed
to be always-on-top: the same trick the ChatGPT desktop app uses. The window
is *override-redirect* — an X11 window (via XWayland) that bypasses the
window manager entirely, the class of window menus and tooltips live in,
which the compositor paints above the regular world. GTK gives exactly that
to any `Gtk.WindowType.POPUP` window. The tray process therefore runs with
`GDK_BACKEND=x11` (see tray.main) — on an X11 session that's a no-op, on
Wayland it lands us on XWayland where the trick works.

This module runs under the SYSTEM python next to the tray, so it may touch
nothing but gi and the standard library.
"""

from __future__ import annotations

from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets" / "mascot"

SIZE = 120                       # on-screen pixels (art is 40px grid × 3)
MARGIN = 28                      # default distance from the workarea corner
_CARD_WIDTH = 400
_CLICK_SLOP = 6                  # a "click" that moved further is a drag

# daemon state (state.json) -> face
FACES = {
    "ready": "idle",
    "hearing": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
    "starting": "waking",
    "paused": "sleeping",
    "off": "sleeping",
    "error": "error",
}

_CSS = b"""
.mantrin-card {
    background-color: rgba(26, 21, 18, 0.97);
    border: 1px solid rgba(217, 154, 43, 0.55);
    border-radius: 14px;
    padding: 14px 16px;
}
.mantrin-card-title {
    color: #d99a2b;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
}
.mantrin-card-body {
    color: #fbf8f4;
    font-size: 14px;
}
"""


class Mascot:
    """Owns two override-redirect windows: the creature and its card.

    `on_click` runs on a clean click (mute toggle, wired by the tray);
    `on_move(x, y)` reports where a drag ended so the spot can be saved.
    """

    def __init__(self, on_click=None, on_move=None, pos: tuple[int, int] | None = None):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GdkPixbuf, Gtk

        self._Gdk, self._Gtk, self._GdkPixbuf = Gdk, Gtk, GdkPixbuf
        self._on_click, self._on_move = on_click, on_move
        self._face = ""
        self._card_text = None
        self._drag = None                     # (pointer_x0, y0, win_x0, y0, moved)

        style = Gtk.CssProvider()
        style.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), style,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._win = self._popup_window()
        self._image = Gtk.Image()
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(self._image)
        self._win.add(box)
        self._win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                             | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self._win.connect("button-press-event", self._press)
        self._win.connect("button-release-event", self._release)
        self._win.connect("motion-notify-event", self._motion)

        x, y = pos if pos else self._corner()
        self._win.move(x, y)
        self.set_state("off")
        self._win.show_all()

        self._card = self._popup_window()
        self._card_title = Gtk.Label(label="NEEDS YOUR OK")
        self._card_title.get_style_context().add_class("mantrin-card-title")
        self._card_title.set_xalign(0.0)
        self._card_body = Gtk.Label()
        self._card_body.get_style_context().add_class("mantrin-card-body")
        self._card_body.set_line_wrap(True)
        self._card_body.set_max_width_chars(46)
        self._card_body.set_xalign(0.0)
        card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_box.get_style_context().add_class("mantrin-card")
        card_box.pack_start(self._card_title, False, False, 0)
        card_box.pack_start(self._card_body, False, False, 0)
        self._card.add(card_box)
        self._card.set_default_size(_CARD_WIDTH, -1)
        # The card's height depends on its text; park it next to the mascot
        # only once GTK has decided how tall it actually is.
        self._card.connect("size-allocate", lambda *_: self._place_card())

    # ------------------------------------------------------------- windows
    def _popup_window(self):
        """A frameless, transparent, above-everything window (see module doc)."""
        Gtk, Gdk = self._Gtk, self._Gdk
        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_keep_above(True)             # belt — X11 sessions honour it
        win.set_app_paintable(True)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)

        def clear(_w, cr):
            cr.set_source_rgba(0, 0, 0, 0)
            cr.set_operator(1)               # cairo.OPERATOR_SOURCE
            cr.paint()
            cr.set_operator(2)               # back to OPERATOR_OVER
            return False
        win.connect("draw", clear)
        return win

    def _workarea(self):
        display = self._Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()

    def _corner(self) -> tuple[int, int]:
        wa = self._workarea()
        return (wa.x + wa.width - SIZE - MARGIN,
                wa.y + wa.height - SIZE - MARGIN)

    def _place_card(self) -> None:
        if not self._card.get_visible():
            return
        cw, ch = self._card.get_size()
        mx, my = self._win.get_position()
        wa = self._workarea()
        x = min(mx + SIZE - cw, wa.x + wa.width - cw - 8)   # right edges align
        y = my - ch - 12                                     # floats above
        if y < wa.y:
            y = my + SIZE + 12                               # no room: below
        self._card.move(max(wa.x + 8, x), y)

    # -------------------------------------------------------- interaction
    def _press(self, _w, ev):
        if ev.button == 1:
            wx, wy = self._win.get_position()
            self._drag = (ev.x_root, ev.y_root, wx, wy, False)
        return True

    def _motion(self, _w, ev):
        if self._drag is None:
            return False
        x0, y0, wx, wy, moved = self._drag
        dx, dy = ev.x_root - x0, ev.y_root - y0
        if moved or abs(dx) > _CLICK_SLOP or abs(dy) > _CLICK_SLOP:
            self._drag = (x0, y0, wx, wy, True)
            self._win.move(int(wx + dx), int(wy + dy))
            self._place_card()
        return True

    def _release(self, _w, ev):
        if self._drag is None:
            return False
        moved = self._drag[4]
        self._drag = None
        if moved:
            if self._on_move:
                self._on_move(*self._win.get_position())
        elif self._on_click:
            self._on_click()
        return True

    # -------------------------------------------------------------- state
    def set_state(self, state: str) -> None:
        face = FACES.get(state, "idle")
        if face == self._face:
            return
        self._face = face
        pixbuf = self._GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(_ASSETS / f"{face}.png"), SIZE, SIZE, False)
        self._image.set_from_pixbuf(pixbuf)

    def set_card(self, text: str | None) -> None:
        if text == self._card_text:
            return
        self._card_text = text
        if not text:
            self._card.hide()
            return
        self._card_body.set_text(text)
        self._card.show_all()
        self._place_card()

    def destroy(self) -> None:
        self._card.destroy()
        self._win.destroy()
