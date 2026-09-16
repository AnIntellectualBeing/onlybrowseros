"""
The OnlyBrowserOS look, shared by the taskbar, the home screen and the
installer: one palette, one set of widget styles, the logo and the wordmark.

Everything is drawn with GTK's built-in widgets, CSS and cairo, so no icon
theme, image files or extra processes are needed.
"""

import math

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

NAME = "OnlyBrowserOS"

# Light and airy: white cards on a pale sky, navy text, one bright blue.
# Keep in step with the :root colours in src/start/index.html.
C = {
    "bg": "#f3f7fd",
    "surface": "#ffffff",
    "raised": "#eef3fa",
    "hover": "#e4ecf8",
    "border": "#dbe3ef",
    "text": "#0f1b3d",
    "muted": "#56627a",
    "faint": "#8a94a8",
    "accent": "#1f6fff",
    "accent_hover": "#3d82ff",
    "accent_pressed": "#155ee0",
    "accent_soft": "rgba(31, 111, 255, 0.10)",
    "logo_light": "#4da3ff",
    "logo_dark": "#1a5ae6",
    "violet": "#8b5cf6",
    "good": "#12a150",
    "good_text": "#15803d",
    "warn": "#d97706",
    "warn_text": "#9a5200",
    "bad": "#dc2626",
}


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


BASE_CSS = """
@define-color accent {accent};
* { outline-color: alpha(@accent, 0.5); }

label.title { font-size: 28px; font-weight: 800; color: {text}; }
label.subtitle { font-size: 15px; color: {muted}; }
label.heading { font-size: 16px; font-weight: 700; color: {text}; }
label.section { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: {faint}; }
label.muted { color: {muted}; }
label.faint { color: {faint}; }
label.good { color: {good_text}; }
label.warn { color: {warn_text}; }
label.error { color: {bad}; }
label.big { font-size: 34px; font-weight: 800; color: {text}; }

button {
  background-image: none; background-color: {surface}; color: {text};
  border: 1px solid {border}; border-radius: 12px; box-shadow: none; text-shadow: none;
  padding: 8px 16px; min-height: 20px;
  transition: background-color 120ms ease;
}
button:hover { background-color: {raised}; }
button:active { background-color: {hover}; }
button:disabled { color: {faint}; background-color: {bg}; border-color: {border}; }
button label { color: inherit; }
button.primary { background-color: {accent}; border-color: {accent}; color: #ffffff; font-weight: 700; }
button.primary:hover { background-color: {accent_hover}; border-color: {accent_hover}; }
button.primary:active { background-color: {accent_pressed}; }
button.primary:disabled { background-color: #b8cdf5; border-color: #b8cdf5; color: #ffffff; }
button.success { background-color: {good}; border-color: {good}; color: #ffffff; font-weight: 700; }
button.success:hover { background-color: #19b45c; border-color: #19b45c; }
button.danger { background-color: {bad}; border-color: {bad}; color: #ffffff; font-weight: 700; }
button.danger:hover { background-color: #e84545; border-color: #e84545; }
button.danger:disabled { background-color: #f1b8b8; border-color: #f1b8b8; color: #ffffff; }
button.pill { border-radius: 999px; padding: 12px 30px; font-size: 15px; }
button.flat, button.row { background-color: transparent; border-color: transparent; }
button.flat:hover, button.row:hover { background-color: {hover}; }
button.row { padding: 8px 10px; border-radius: 10px; }
button.link { background-color: transparent; border-color: transparent; color: {accent}; padding: 4px 6px; font-weight: 600; }
button.link:hover { color: {accent_pressed}; background-color: transparent; }

entry {
  background-image: none; background-color: {surface}; color: {text};
  border: 1px solid {border}; border-radius: 12px; box-shadow: none; padding: 10px 12px;
  caret-color: {accent};
}
entry:focus { border-color: {accent}; box-shadow: 0 0 0 3px {accent_soft}; }
selection, entry selection, label selection { background-color: {accent}; color: #ffffff; }
entry image { color: {muted}; }
spinbutton { background-color: {surface}; border: 1px solid {border}; border-radius: 12px; box-shadow: none; }
spinbutton entry { border: none; background: transparent; box-shadow: none; }
spinbutton button { border: none; border-radius: 0; background: transparent; }

combobox button, combobox > box > button {
  background-color: {surface}; border: 1px solid {border}; padding: 8px 12px; border-radius: 12px;
}
menu, .menu, .context-menu { background-color: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }
menuitem { padding: 6px 12px; border-radius: 6px; }
menuitem:hover { background-color: {accent}; color: #ffffff; }

check, radio {
  background-image: none; background-color: {surface}; border: 2px solid #b9c3d3; color: #ffffff;
  min-width: 16px; min-height: 16px; box-shadow: none; -gtk-icon-shadow: none;
}
check { border-radius: 5px; }
radio { border-radius: 50%; }
check:checked, radio:checked { background-color: {accent}; border-color: {accent}; }
checkbutton, radiobutton { color: {text}; }
checkbutton label, radiobutton label { padding-left: 4px; }

switch {
  background-image: none; background-color: #c9d3e3; border: none; border-radius: 14px;
  min-width: 44px; min-height: 24px; box-shadow: none; color: transparent;
}
switch:checked { background-color: {accent}; }
switch slider {
  background-image: none; background-color: #ffffff; border: none; border-radius: 50%;
  min-width: 20px; min-height: 20px; margin: 2px; box-shadow: 0 1px 2px rgba(15, 27, 61, 0.25);
}

scale trough { background-color: {border}; min-height: 6px; border-radius: 3px; border: none; }
scale highlight { background-color: {accent}; border-radius: 3px; border: none; }
scale slider {
  background-image: none; background-color: #ffffff; border: 1px solid {border};
  box-shadow: 0 1px 3px rgba(15, 27, 61, 0.25);
  min-width: 18px; min-height: 18px; border-radius: 50%; margin: -7px;
}

progressbar trough { min-height: 12px; background-color: #dde7f5; border-radius: 6px; border: none; }
progressbar progress { min-height: 12px; border-radius: 6px; border: none; background-color: {accent}; }

separator { background-color: {border}; min-height: 1px; min-width: 1px; }
scrollbar { background-color: transparent; border: none; }
scrollbar slider { background-color: #c9d3e3; border-radius: 4px; min-width: 6px; min-height: 6px; border: none; }
scrollbar slider:hover { background-color: {faint}; }
tooltip, tooltip.background { background-color: {text}; color: #ffffff; border: none; border-radius: 8px; }
tooltip label { color: #ffffff; }
expander title { color: {muted}; }
expander title:hover { color: {text}; }
expander arrow { color: {muted}; }
textview, textview text { background-color: {raised}; color: {muted}; font-family: monospace; font-size: 11px; }
spinner { color: {accent}; }
calendar { background-color: transparent; color: {text}; border: none; padding: 4px; }
calendar:selected { background-color: {accent}; color: #ffffff; border-radius: 6px; }
calendar.header { border: none; background: transparent; }
calendar.button { color: {muted}; }
calendar:indeterminate { color: {faint}; }

.card { background-color: {surface}; border: 1px solid {border}; border-radius: 16px; }
.card.selected { border-color: {accent}; background-color: #f2f7ff; }
.notice { background-color: #fff7ea; border: 1px solid #f6d7a7; border-radius: 16px; }
.notice label { color: {warn_text}; }
.chip { background-color: {raised}; color: {muted}; border-radius: 8px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
"""


def css(template):
    """Fill {name} colour placeholders without tripping over CSS braces."""
    out = template
    for key in sorted(C, key=len, reverse=True):
        out = out.replace("{" + key + "}", C[key])
    return out


def apply(extra_css=""):
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", False)
        settings.set_property("gtk-font-name", "Noto Sans 10")
        settings.set_property("gtk-enable-animations", True)
    provider = Gtk.CssProvider()
    provider.load_from_data(css(BASE_CSS + extra_css).encode())
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def add_class(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        for name in c.split():
            ctx.add_class(name)
    return widget


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_logo(cr, size):
    """The mark: a blue sphere holding a white globe, circled by an orbit
    that passes behind the globe and in front of it ("the whole computer is
    the web"). Drawn on a 48-unit grid. Keep in step with the SVG in
    src/start/index.html."""
    import cairo

    s = size / 48.0
    cr.save()
    cr.scale(s, s)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)

    def blue():
        grad = cairo.LinearGradient(8, 4, 40, 44)
        grad.add_color_stop_rgb(0, *rgb(C["logo_light"]))
        grad.add_color_stop_rgb(1, *rgb(C["logo_dark"]))
        return grad

    def orbit(start, end, alpha):
        cr.save()
        cr.translate(24, 24)
        cr.rotate(math.radians(-24))
        cr.scale(1, 0.34)
        cr.arc(0, 0, 21, start, end)
        cr.restore()
        cr.set_source_rgba(1, 1, 1, alpha)
        cr.set_line_width(2.4)
        cr.stroke()

    cr.arc(24, 24, 24, 0, 2 * math.pi)
    cr.set_source(blue())
    cr.fill()

    orbit(math.pi, 2 * math.pi, 0.55)       # the back half, behind the globe

    cr.arc(24, 24, 14.2, 0, 2 * math.pi)    # hides the orbit where the globe covers it
    cr.set_source(blue())
    cr.fill()

    cr.set_source_rgb(1, 1, 1)
    cr.set_line_width(2.6)
    cr.arc(24, 24, 12.5, 0, 2 * math.pi)
    cr.stroke()
    cr.save()
    cr.translate(24, 24)
    cr.scale(0.44, 1)
    cr.arc(0, 0, 12.5, 0, 2 * math.pi)
    cr.restore()
    cr.stroke()
    cr.move_to(11.5, 24)
    cr.line_to(36.5, 24)
    cr.stroke()

    orbit(0, math.pi, 1.0)                  # the front half, over the globe
    cr.restore()


class Logo(Gtk.DrawingArea):
    def __init__(self, size=48):
        super().__init__()
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", lambda w, cr: draw_logo(cr, min(w.get_allocated_width(), w.get_allocated_height())))


def wordmark_markup(size_pt=None):
    """"OnlyBrowser" in navy and "OS" in blue, as Pango markup."""
    size = f' size="{int(size_pt * 1024)}"' if size_pt else ""
    return (f'<span weight="bold"{size}><span foreground="{C["text"]}">OnlyBrowser</span>'
            f'<span foreground="{C["accent"]}">OS</span></span>')


def brand(size=28, text_size=None):
    """Logo and wordmark side by side."""
    box = Gtk.Box(spacing=10)
    box.pack_start(Logo(size), False, False, 0)
    name = Gtk.Label(xalign=0)
    name.set_markup(wordmark_markup(text_size or max(10, size * 0.46)))
    box.pack_start(name, False, False, 0)
    return box
