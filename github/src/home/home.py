#!/usr/bin/env python3
"""
OnlyBrowserOS home screen.

Shown when someone closes the browser on purpose (its menu, Ctrl+Q). Instead
of the browser popping straight back, they get a calm screen with the
landscape, the time, a big "Open the browser" button and the power buttons.
The taskbar stays usable underneath it.

Exits with status 0 when the browser should start again. Started and waited
for by /usr/lib/onlybrowseros/browser.
"""

import ctypes
import datetime
import os
import subprocess
import sys
import time

from gi.repository import GLib

GLib.set_prgname("obos-home")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "panel"))
import landscape  # noqa: E402
import theme  # noqa: E402
from icons import Icon  # noqa: E402

CSS = """
window.home { background-color: #cfe5ff; }
.home-greeting { font-size: 18px; font-weight: 600; color: {muted}; }
.home-time { font-size: 96px; font-weight: 800; color: {text}; }
.home-date { font-size: 20px; color: #34405a; }
.home-hint { font-size: 14px; color: #34405a; }
button.open-browser {
  font-size: 17px; padding: 14px 36px; border-radius: 999px;
  box-shadow: 0 6px 18px rgba(31, 111, 255, 0.35);
}
button.power {
  background-color: #ffffff; border-color: transparent; padding: 10px 22px; border-radius: 999px;
  box-shadow: 0 2px 8px rgba(15, 27, 61, 0.18);
}
button.power:hover { background-color: {raised}; }
"""


def greeting(hour):
    if hour < 5:
        return "Good night"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


class Home(Gtk.Window):
    def __init__(self):
        super().__init__(title="OnlyBrowserOS")
        theme.add_class(self, "home")
        self.set_decorated(False)
        self.maximize()
        self.connect("delete-event", lambda *_: True)  # only the button leaves this screen
        self.connect("key-press-event", self.on_key)

        overlay = Gtk.Overlay()
        self.add(overlay)
        scenery = Gtk.DrawingArea()
        scenery.connect("draw", lambda w, cr: landscape.draw(cr, w.get_allocated_width(),
                                                             w.get_allocated_height()))
        overlay.add(scenery)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.add_overlay(outer)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        # Sit in the sky, above the mountains.
        center.set_margin_bottom(180)
        outer.pack_start(center, True, True, 0)

        center.pack_start(theme.brand(40, 20), False, False, 14)
        self.greeting = theme.add_class(Gtk.Label(), "home-greeting")
        self.time = theme.add_class(Gtk.Label(), "home-time")
        self.date = theme.add_class(Gtk.Label(), "home-date")
        for w in (self.greeting, self.time, self.date):
            center.pack_start(w, False, False, 0)

        open_button = Gtk.Button()
        inner = Gtk.Box(spacing=12)
        inner.pack_start(Icon("globe", 22), False, False, 0)
        inner.pack_start(Gtk.Label(label="Open the browser"), False, False, 0)
        open_button.add(inner)
        theme.add_class(open_button, "primary", "open-browser")
        open_button.set_halign(Gtk.Align.CENTER)
        open_button.connect("clicked", lambda _b: self.open_browser())
        center.pack_start(open_button, False, False, 26)

        hint = theme.add_class(Gtk.Label(label="Your tabs come back where you left them."), "home-hint")
        center.pack_start(hint, False, False, 0)
        self.open_button = open_button

        power = Gtk.Box(spacing=12)
        power.set_halign(Gtk.Align.CENTER)
        power.set_margin_bottom(36)
        for text, icon, action in (("Sleep", "moon", "suspend"),
                                   ("Restart", "restart", "reboot"),
                                   ("Shut down", "power", "poweroff")):
            b = Gtk.Button()
            box = Gtk.Box(spacing=8)
            box.pack_start(Icon(icon, 16), False, False, 0)
            box.pack_start(Gtk.Label(label=text), False, False, 0)
            b.add(box)
            theme.add_class(b, "power")
            b.connect("clicked", lambda _b, a=action: subprocess.Popen(["systemctl", a]))
            power.pack_start(b, False, False, 0)
        outer.pack_end(power, False, False, 0)

        self.tick()

    def tick(self):
        time.tzset()
        now = datetime.datetime.now()
        self.greeting.set_text(greeting(now.hour))
        self.time.set_text(now.strftime("%-I:%M"))
        self.date.set_text(now.strftime("%A, %-d %B"))
        GLib.timeout_add_seconds(max(1, 60 - now.second), self.tick)
        return False

    def on_key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.open_browser()
            return True
        return False

    def open_browser(self):
        Gtk.main_quit()


def main():
    try:
        ctypes.CDLL("libc.so.6").prctl(15, b"obos-home\0", 0, 0, 0)
    except (OSError, AttributeError):
        pass
    theme.apply(CSS)
    window = Home()
    window.show_all()
    window.open_button.grab_focus()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
