"""
Taskbar icons, drawn with cairo on a 24-unit grid. They stay sharp at any
size, follow the text colour of whatever they sit in, and need no icon theme.
"""

import math

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

DIM = 0.28


def _rad(degrees):
    return degrees * math.pi / 180


def _set(cr, color, alpha=1.0):
    cr.set_source_rgba(color.red, color.green, color.blue, color.alpha * alpha)


def _line(cr, *points):
    cr.move_to(*points[0])
    for p in points[1:]:
        cr.line_to(*p)
    cr.stroke()


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, _rad(-90), 0)
    cr.arc(x + w - r, y + h - r, r, 0, _rad(90))
    cr.arc(x + r, y + h - r, r, _rad(90), _rad(180))
    cr.arc(x + r, y + r, r, _rad(180), _rad(270))
    cr.close_path()


def _slash(cr, color):
    _set(cr, color)
    cr.set_line_width(2.2)
    _line(cr, (4, 4), (20, 20))


def draw_wifi(cr, color, level=0, off=False, connecting=False, **_):
    cx, cy = 12, 19.5
    for i, radius in enumerate((6, 11, 16), start=1):
        lit = not off and not connecting and level >= i
        _set(cr, color, 1.0 if lit else DIM)
        cr.set_line_width(2.4)
        cr.arc(cx, cy, radius * 0.95, _rad(228), _rad(312))
        cr.stroke()
    _set(cr, color, DIM if off else 1.0)
    cr.arc(cx, cy, 1.9, 0, 2 * math.pi)
    cr.fill()
    if off:
        _slash(cr, color)


def draw_ethernet(cr, color, off=False, dim=False, **_):
    _set(cr, color, DIM if (off or dim) else 1.0)
    cr.set_line_width(1.8)
    cr.rectangle(8.5, 3, 7, 5.5)
    cr.rectangle(2.5, 15.5, 7, 5.5)
    cr.rectangle(14.5, 15.5, 7, 5.5)
    cr.stroke()
    _line(cr, (12, 8.5), (12, 12))
    _line(cr, (6, 15.5), (6, 12), (18, 12), (18, 15.5))
    if off:
        _slash(cr, color)


def draw_bluetooth(cr, color, on=True, connected=False, **_):
    _set(cr, color, 1.0 if on else DIM)
    cr.set_line_width(2)
    _line(cr, (6.5, 7.5), (17, 16.5), (12, 21), (12, 3), (17, 7.5), (6.5, 16.5))
    if connected:
        for x in (4, 20):
            cr.arc(x, 12, 1.5, 0, 2 * math.pi)
            cr.fill()
    if not on:
        _slash(cr, color)


def draw_speaker(cr, color, level=2, muted=False, **_):
    _set(cr, color, DIM if muted else 1.0)
    cr.move_to(3, 9)
    cr.line_to(7, 9)
    cr.line_to(12, 4.5)
    cr.line_to(12, 19.5)
    cr.line_to(7, 15)
    cr.line_to(3, 15)
    cr.close_path()
    cr.fill()
    if muted:
        _set(cr, color)
        cr.set_line_width(2)
        _line(cr, (15.5, 9), (21, 15))
        _line(cr, (21, 9), (15.5, 15))
        return
    cr.set_line_width(2)
    for i, radius in enumerate((4.5, 8.5), start=1):
        _set(cr, color, 1.0 if level >= i else DIM)
        cr.arc(12, 12, radius, _rad(-45), _rad(45))
        cr.stroke()


def draw_mic(cr, color, muted=False, **_):
    _set(cr, color, DIM if muted else 1.0)
    _rounded_rect(cr, 8.5, 2.5, 7, 12, 3.5)
    cr.fill()
    cr.set_line_width(2)
    cr.arc(12, 11, 6.5, 0, math.pi)
    cr.stroke()
    _line(cr, (12, 17.5), (12, 21))
    _line(cr, (8, 21), (16, 21))
    if muted:
        _slash(cr, color)


def draw_sun(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(2)
    cr.arc(12, 12, 4, 0, 2 * math.pi)
    cr.stroke()
    for i in range(8):
        a = _rad(i * 45)
        _line(cr, (12 + 7 * math.cos(a), 12 + 7 * math.sin(a)),
              (12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))


def _hex(cr, value, alpha=1.0):
    h = value.lstrip("#")
    cr.set_source_rgba(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, alpha)


def draw_battery(cr, color, percent=100, charging=False, plugged=False, **_):
    # A horizontal cell whose fill turns amber, then red, as it drains, and
    # green while charging.
    percent = max(0, min(100, percent))
    if charging:
        fill = "#12a150"
    elif not plugged and percent <= 10:
        fill = "#dc2626"
    elif not plugged and percent <= 20:
        fill = "#d97706"
    else:
        fill = None

    _set(cr, color, 0.85)
    cr.set_line_width(1.5)
    _rounded_rect(cr, 1.75, 6.75, 18.5, 10.5, 3)
    cr.stroke()
    _rounded_rect(cr, 21, 9.8, 1.9, 4.4, 0.9)
    cr.fill()

    width = max(1.2, percent / 100 * 15)
    _rounded_rect(cr, 3.5, 8.5, width, 7, 1.6)
    if fill:
        _hex(cr, fill)
    else:
        _set(cr, color)
    cr.fill()

    if charging:
        cr.move_to(12.8, 4.2)
        cr.line_to(7.6, 12.6)
        cr.line_to(11.2, 12.6)
        cr.line_to(10.0, 19.8)
        cr.line_to(15.4, 11.2)
        cr.line_to(11.8, 11.2)
        cr.close_path()
        _hex(cr, "#ffffff")
        cr.set_line_width(2.2)
        cr.stroke_preserve()
        _hex(cr, "#0f1b3d")
        cr.fill()


def draw_globe(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(1.9)
    cr.arc(12, 12, 9, 0, 2 * math.pi)
    cr.stroke()
    cr.save()
    cr.translate(12, 12)
    cr.scale(0.42, 1)
    cr.arc(0, 0, 9, 0, 2 * math.pi)
    cr.restore()
    cr.stroke()
    _line(cr, (3, 12), (21, 12))


def draw_power(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(2.2)
    cr.arc(12, 13, 8, _rad(-50), _rad(230))
    cr.stroke()
    _line(cr, (12, 2.5), (12, 11.5))


def draw_install(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(2.2)
    _line(cr, (12, 3), (12, 14))
    _line(cr, (7, 9.5), (12, 14.5), (17, 9.5))
    _line(cr, (4, 15), (4, 20.5), (20, 20.5), (20, 15))


def draw_lock(cr, color, **_):
    _set(cr, color, 0.8)
    _rounded_rect(cr, 5, 10.5, 14, 11, 2)
    cr.fill()
    cr.set_line_width(2.4)
    cr.arc(12, 10.5, 4.5, _rad(180), _rad(360))
    cr.stroke()


def draw_tabs(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(1.8)
    _rounded_rect(cr, 2.5, 7, 16, 13, 2)
    cr.stroke()
    _line(cr, (6.5, 4), (19.5, 4), (21.5, 6), (21.5, 16))


def draw_moon(cr, color, **_):
    # A disc with a second disc cut out of it.
    cr.push_group()
    _set(cr, color)
    cr.arc(11, 13, 8.5, 0, 2 * math.pi)
    cr.fill()
    cr.set_operator(0)  # CLEAR
    cr.arc(16.5, 8, 7, 0, 2 * math.pi)
    cr.fill()
    cr.pop_group_to_source()
    cr.paint()


def draw_restart(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(2.2)
    cr.arc(12, 12, 8, _rad(-60), _rad(240))
    cr.stroke()
    cr.move_to(15.5, 1.5)
    cr.line_to(16.5, 6.5)
    cr.line_to(11.5, 7.5)
    cr.stroke()


def draw_user(cr, color, **_):
    _set(cr, color)
    cr.set_line_width(2)
    cr.arc(12, 8.5, 4, 0, 2 * math.pi)
    cr.stroke()
    cr.arc(12, 21, 7.5, _rad(200), _rad(340))
    cr.stroke()


def draw_settings(cr, color, **_):
    # Three sliders.
    _set(cr, color)
    cr.set_line_width(2)
    for y, knob in ((6, 15), (12, 9), (18, 16)):
        _line(cr, (3.5, y), (knob - 2.8, y))
        _line(cr, (knob + 2.8, y), (20.5, y))
        cr.arc(knob, y, 2.4, 0, 2 * math.pi)
        cr.stroke()


def draw_missing(cr, color, **_):
    _set(cr, color, DIM)
    cr.arc(12, 12, 8, 0, 2 * math.pi)
    cr.fill()


DRAWERS = {
    "wifi": draw_wifi,
    "ethernet": draw_ethernet,
    "bluetooth": draw_bluetooth,
    "speaker": draw_speaker,
    "mic": draw_mic,
    "sun": draw_sun,
    "battery": draw_battery,
    "power": draw_power,
    "install": draw_install,
    "lock": draw_lock,
    "tabs": draw_tabs,
    "moon": draw_moon,
    "restart": draw_restart,
    "globe": draw_globe,
    "user": draw_user,
    "settings": draw_settings,
}


class Icon(Gtk.DrawingArea):
    def __init__(self, name, size=18, **state):
        super().__init__()
        self.name = name
        self.size = size
        self.state = dict(state)
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self._on_draw)

    def update(self, name=None, **state):
        if name:
            self.name = name
            self.state = {}
        self.state.update(state)
        self.queue_draw()

    def _on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        side = min(width, height)
        color = widget.get_style_context().get_color(widget.get_state_flags())
        cr.translate((width - side) / 2, (height - side) / 2)
        cr.scale(side / 24.0, side / 24.0)
        cr.set_line_cap(1)   # round
        cr.set_line_join(1)  # round
        DRAWERS.get(self.name, draw_missing)(cr, color, **self.state)
        return False
