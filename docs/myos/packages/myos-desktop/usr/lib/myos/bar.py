#!/usr/bin/env python3
"""The MyOS bar: a strip along the bottom of the screen with the
system's name, the time and a power button."""

import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

HEIGHT = 40
CSS = b"""
window        { background: #ffffff; border-top: 1px solid #c7d7ee; }
label         { color: #1f2937; font-size: 11pt; }
#name         { color: #1d4ed8; font-weight: bold; }
button        { background: #1d4ed8; color: #ffffff; border: none;
                border-radius: 6px; padding: 2px 12px; }
button label  { color: #ffffff; }
"""


class Bar(Gtk.Window):
    def __init__(self):
        super().__init__(title="MyOS bar")
        self.set_wmclass("myos-bar", "myos-bar")       # openbox.xml matches this name
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)    # a panel, not a normal window
        self.set_decorated(False)

        # Full width, at the bottom of the first screen.
        area = Gdk.Display.get_default().get_monitor(0).get_geometry()
        self.set_size_request(area.width, HEIGHT)
        self.move(area.x, area.y + area.height - HEIGHT)

        box = Gtk.Box(spacing=16, margin_start=14, margin_end=8)
        self.add(box)

        name = Gtk.Label(label="MyOS")
        name.set_name("name")
        box.pack_start(name, False, False, 0)

        power = Gtk.Button(label="Power off")
        power.connect("clicked", self.power_off)
        box.pack_end(power, False, False, 0)

        self.clock = Gtk.Label()
        box.pack_end(self.clock, False, False, 0)
        self.tick()
        GLib.timeout_add_seconds(5, self.tick)

    def tick(self):
        self.clock.set_text(time.strftime("%a %d %b  %H:%M"))
        return True                                    # keep the timer running

    def power_off(self, _button):
        ask = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL,
                                text="Switch the computer off?")
        answer = ask.run()
        ask.destroy()
        if answer == Gtk.ResponseType.OK:
            # logind lets the person sitting at the computer do this (via polkit).
            subprocess.run(["systemctl", "poweroff"])


style = Gtk.CssProvider()
style.load_from_data(CSS)
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style,
                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
bar = Bar()
bar.connect("destroy", Gtk.main_quit)
bar.show_all()
Gtk.main()
