#!/usr/bin/env python3
"""
OnlyBrowserOS taskbar.

A 44 px bar along the bottom of the screen: the logo and name (memory and
tabs) and the install button (live USB only) on the left; network, Bluetooth,
sound, brightness, battery, clock and power on the right. Each button opens a small menu above it. The
browser fills the rest of the screen; openbox keeps it clear of the bar
(margins in /etc/onlybrowseros/openbox/rc.xml).
"""

import ctypes
import datetime
import os
import signal
import sys
import threading
import time

from gi.repository import GLib

# The window class openbox matches on comes from the program name, which must
# be set before GTK initialises.
GLib.set_prgname("obos-panel")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shared"))
import levels  # noqa: E402
import system  # noqa: E402
import theme  # noqa: E402
from icons import Icon  # noqa: E402

PANEL_HEIGHT = 44          # keep in step with <margins><bottom> in openbox rc.xml
POPUP_WIDTH = 360
POPUP_GAP = 8

CSS = """
window.panel { background-color: {surface}; color: {text}; border-top: 1px solid {border}; }
window.panel button {
  background-color: transparent; border: none; color: {text};
  padding: 0 10px; margin: 6px 1px; border-radius: 10px; min-height: 30px;
}
window.panel button:hover { background-color: {hover}; }
window.panel button.open { background-color: {accent_soft}; }
window.panel button.logo { padding: 0 10px 0 6px; }
window.panel button.install { background-color: {accent}; color: #ffffff; font-weight: 700; padding: 0 16px; border-radius: 999px; }
window.panel button.install:hover { background-color: {accent_hover}; }
window.panel .tray { margin: 0 4px; }
window.panel .tray button { padding: 0 8px; }
window.panel .battery-text { font-weight: 600; }
window.panel .battery-text.low { color: {warn_text}; }
window.panel .battery-text.critical { color: {bad}; }
window.panel .clock-time { font-weight: 600; font-size: 13px; }

window.popup { background-color: {surface}; color: {text}; border: 1px solid {border}; }
window.popup .popup-title { font-size: 15px; font-weight: 700; }
window.popup .count { font-size: 22px; font-weight: 800; }
window.popup .clock-big { font-size: 38px; font-weight: 800; }
window.popup .gauge-percent { font-size: 30px; font-weight: 800; }
window.popup .stat { background-color: {raised}; border-radius: 12px; }
window.popup .stat-value { font-weight: 700; font-size: 13px; }
window.popup button.action { padding: 14px 4px; border-radius: 14px; }
window.popup button.action.shutdown:hover { background-color: #fdecec; border-color: #f5b5b5; color: {bad}; }
window.popup button.tiny { padding: 2px 10px; min-width: 20px; font-size: 16px; font-weight: 700; }
window.popup levelbar trough { background-color: {border}; border: none; border-radius: 4px; min-height: 8px; }
window.popup levelbar block { border: none; border-radius: 4px; min-height: 8px; }
window.popup levelbar block.filled { background-color: {accent}; }
window.popup levelbar block.filled.high { background-color: {warn}; }
window.popup levelbar block.filled.full { background-color: {bad}; }
window.popup levelbar block.empty { background-color: transparent; }

window.osd { background-color: {surface}; color: {text}; border: 1px solid {border}; }
window.osd levelbar trough { background-color: {border}; border: none; border-radius: 4px; min-height: 8px; }
window.osd levelbar block { border: none; border-radius: 4px; min-height: 8px; }
window.osd levelbar block.filled { background-color: {accent}; }
window.osd levelbar block.empty { background-color: transparent; }
window.osd .osd-value { font-weight: 700; font-size: 13px; }

window.alert { background-color: {surface}; color: {text}; border: 1px solid {border}; }
window.alert .alert-title { font-size: 20px; font-weight: 800; }
"""

LOW_BATTERY = 10          # percent: a warning
CRITICAL_BATTERY = 5      # a shutdown countdown that can be put off once
LAST_CHANCE_BATTERY = 3   # the countdown again, without "Keep working"
SHUTDOWN_SECONDS = 60


# ------------------------------------------------------------------ helpers

def set_process_name(name):
    """earlyoom and pgrep see the process name; 'python3' says nothing."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(15, name.encode()[:15] + b"\0", 0, 0, 0)  # PR_SET_NAME
    except (OSError, AttributeError):
        pass


def in_background(work, done=None):
    """Run work() on a thread, then done(result, error) on the GTK main loop."""
    def runner():
        try:
            result, error = work(), None
        except Exception as exc:  # noqa: BLE001 - shown to the user
            result, error = None, exc
        if done:
            GLib.idle_add(lambda: done(result, error) and False)
    threading.Thread(target=runner, daemon=True).start()


def add_class(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def label(text="", classes="", xalign=0.0, wrap=False, ellipsize=False):
    widget = Gtk.Label(label=text, xalign=xalign)
    if classes:
        add_class(widget, *classes.split())
    if wrap:
        widget.set_line_wrap(True)
        widget.set_max_width_chars(38)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


def button(text=None, icon=None, classes="", on_click=None, tooltip=None, vertical=False):
    b = Gtk.Button()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                  spacing=6 if vertical else 8)
    box.set_halign(Gtk.Align.CENTER)
    if icon is not None:
        box.pack_start(icon, False, False, 0)
    if text is not None:
        box.pack_start(Gtk.Label(label=text), False, False, 0)
    b.add(box)
    b.set_can_focus(False)
    if classes:
        add_class(b, *classes.split())
    if tooltip:
        b.set_tooltip_text(tooltip)
    if on_click:
        b.connect("clicked", lambda _b: on_click())
    return b


def clear(box):
    for child in box.get_children():
        child.destroy()


def section(text):
    return label(text.upper(), "section")


def wifi_bars(signal_strength):
    if signal_strength >= 67:
        return 3
    if signal_strength >= 34:
        return 2
    return 1 if signal_strength > 0 else 0


def duration(minutes):
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} h" if hours else f"{mins} min"


# -------------------------------------------------------------------- popup

class Popup(Gtk.Window):
    """A taskbar menu: an undecorated window above its button that closes when
    you click anywhere else."""

    title_text = ""

    title_icon = None

    def __init__(self, panel):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.panel = panel
        self.anchor = None
        self.set_title(self.title_text)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        add_class(self, "popup")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_border_width(18)
        header = Gtk.Box(spacing=10)
        if self.title_icon == "logo":
            header.pack_start(theme.Logo(24), False, False, 0)
        header.pack_start(label(self.title_text, "popup-title"), True, True, 0)
        self.header_extra = Gtk.Box(spacing=8)
        header.pack_end(self.header_extra, False, False, 0)
        outer.pack_start(header, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.pack_start(self.body, True, True, 0)
        self.add(outer)
        self.set_size_request(POPUP_WIDTH, -1)

        self.connect("focus-out-event", lambda *_: GLib.timeout_add(150, self._close_if_unfocused) and False)
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", lambda *_: self.close_menu() or True)
        self.connect("size-allocate", lambda *_: self.place())

    def open(self, anchor):
        self.anchor = anchor
        add_class(anchor, "open")
        self.refresh()
        self.show_all()
        self.after_show()
        self.place()
        self.present_with_time(Gtk.get_current_event_time())

    def close_menu(self):
        if self.anchor is not None:
            self.anchor.get_style_context().remove_class("open")
        self.hide()

    def _close_if_unfocused(self):
        if self.get_visible() and not self.is_active():
            self.close_menu()
        return False

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_menu()
            return True
        return False

    def place(self):
        if self.anchor is None or self.anchor.get_window() is None:
            return False
        geo = self.panel.monitor_geometry()
        _, origin_x, _ = self.anchor.get_window().get_origin()
        alloc = self.anchor.get_allocation()
        width = max(POPUP_WIDTH, self.get_allocated_width())
        height = max(self.get_preferred_size()[1].height, self.get_allocated_height())
        x = origin_x + alloc.x + alloc.width // 2 - width // 2
        x = max(geo.x + POPUP_GAP, min(x, geo.x + geo.width - width - POPUP_GAP))
        y = max(geo.y, geo.y + geo.height - PANEL_HEIGHT - height - POPUP_GAP)
        if self.get_position() != (x, y):
            self.move(x, y)
        return False

    # Subclasses fill these in.
    def refresh(self):
        pass

    def after_show(self):
        pass


# ------------------------------------------------------------------ network

class NetworkMenu(Popup):
    title_text = "Network"

    def __init__(self, panel):
        super().__init__(panel)
        self.expanded = None       # (ssid, "password"|"actions", error text)
        self.busy = False

        self.wifi_label = label("Wi-Fi", "muted")
        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", self.on_switch)
        self.header_extra.pack_start(self.wifi_label, False, False, 0)
        self.header_extra.pack_start(self.switch, False, False, 0)

        self.wired = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.networks_title = section("Wi-Fi networks")
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_max_content_height(300)
        self.scroller.add(self.list_box)
        self.message = label("", "muted", wrap=True)

        footer = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.scan_button = button("Search again", on_click=lambda: self.load(rescan=True))
        footer.pack_start(self.spinner, False, False, 0)
        footer.pack_end(self.scan_button, False, False, 0)

        for w in (self.wired, self.networks_title, self.scroller, self.message, footer):
            self.body.pack_start(w, False, False, 0)

    def refresh(self):
        self.message.set_text("")
        self.expanded = None
        self.load(rescan=False)

    def status_changed(self):
        if self.get_visible() and not self.busy and self.expanded is None:
            self.load(rescan=False)

    def load(self, rescan):
        self.spinner.start()
        self.scan_button.set_sensitive(False)
        if rescan:
            self.message.set_text("Looking for networks…")

        def work():
            status = system.network_status()
            wired = system.ethernet_details()
            networks, scan_error = [], ""
            if status["has_wifi"] and status["wifi_enabled"]:
                try:
                    networks = system.wifi_networks(rescan)
                except RuntimeError as exc:
                    scan_error = str(exc)
            return status, wired, networks, scan_error

        in_background(work, self.show_result)

    def show_result(self, result, error):
        self.spinner.stop()
        self.scan_button.set_sensitive(True)
        if error is not None:
            self.message.set_text(str(error))
            return
        status, wired, networks, scan_error = result

        self.switch.handler_block(self.switch_handler)
        self.switch.set_active(status["wifi_enabled"])
        self.switch.handler_unblock(self.switch_handler)
        self.switch.set_visible(status["has_wifi"])
        self.wifi_label.set_visible(status["has_wifi"])

        clear(self.wired)
        for eth in wired:
            if eth["state"] == "connected":
                detail = " · ".join(x for x in ("Connected", eth["ip"], eth["speed"]) if x)
            elif eth["state"] == "unavailable":
                detail = "Cable not plugged in"
            elif eth["state"].startswith("connecting"):
                detail = "Connecting…"
            else:
                detail = "Not connected"
            row = Gtk.Box(spacing=10)
            row.pack_start(Icon("ethernet", 20, dim=eth["state"] != "connected"), False, False, 0)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.pack_start(label("Network cable (LAN)"), False, False, 0)
            col.pack_start(label(detail, "good" if eth["state"] == "connected" else "muted"), False, False, 0)
            row.pack_start(col, True, True, 0)
            self.wired.pack_start(row, False, False, 0)
        if wired:
            self.wired.pack_start(Gtk.Separator(), False, False, 4)
        self.wired.show_all()

        clear(self.list_box)
        show_list = status["has_wifi"] and status["wifi_enabled"]
        self.networks_title.set_visible(show_list)
        self.scroller.set_visible(show_list)
        self.scan_button.set_visible(show_list)

        if not status["has_wifi"]:
            if not wired:
                self.message.set_text("This computer has no network adapter that OnlyBrowserOS can use.")
            elif not self.busy:
                self.message.set_text("This computer has no Wi-Fi adapter.")
            return
        if not status["wifi_enabled"]:
            self.message.set_text("Wi-Fi is off. Turn it on with the switch above.")
            return
        if scan_error:
            self.message.set_text(scan_error)
        elif not networks:
            self.message.set_text("No Wi-Fi networks found. Choose Search again in a moment.")
        elif not self.busy and self.message.get_text() == "Looking for networks…":
            self.message.set_text("")

        for net in networks:
            self.list_box.pack_start(self.network_row(net), False, False, 0)
        self.list_box.show_all()

    def network_row(self, net):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b = Gtk.Button()
        b.set_can_focus(False)
        add_class(b, "row")
        box = Gtk.Box(spacing=10)
        box.pack_start(Icon("wifi", 18, level=wifi_bars(net["signal"])), False, False, 0)
        name = label(net["ssid"], ellipsize=True)
        name.set_hexpand(True)
        box.pack_start(name, True, True, 0)
        if net["active"]:
            box.pack_end(label("Connected", "good"), False, False, 0)
        elif net["saved"]:
            box.pack_end(label("Saved", "muted"), False, False, 0)
        if net["secure"]:
            box.pack_end(Icon("lock", 12), False, False, 0)
        b.add(box)
        b.connect("clicked", lambda _b: self.on_network_clicked(net, outer))
        outer.pack_start(b, False, False, 0)

        if self.expanded and self.expanded[0] == net["ssid"]:
            self.expand(net, outer, self.expanded[1], self.expanded[2])
        return outer

    def on_network_clicked(self, net, outer):
        if self.busy:
            return
        if self.expanded and self.expanded[0] == net["ssid"]:
            self.expanded = None
            self.load(rescan=False)
            return
        if net["active"] or net["saved"]:
            self.expand(net, outer, "actions")
        elif net["enterprise"]:
            self.message.set_text(f"“{net['ssid']}” needs a user name as well as a password "
                                  "(work or school Wi-Fi). OnlyBrowserOS cannot join that kind of network yet.")
        elif net["secure"]:
            self.expand(net, outer, "password")
        else:
            self.connect_to(net, None)

    def expand(self, net, outer, kind, error_text=""):
        # Only one open row at a time.
        for row in self.list_box.get_children():
            for child in row.get_children()[1:]:
                child.destroy()
        self.expanded = (net["ssid"], kind, error_text)

        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail.set_margin_start(36)
        detail.set_margin_end(8)
        detail.set_margin_bottom(6)

        if kind == "password":
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            entry.set_placeholder_text("Wi-Fi password")
            show = Gtk.CheckButton(label="Show password")
            show.connect("toggled", lambda c: entry.set_visibility(c.get_active()))
            go = button("Connect", classes="primary",
                        on_click=lambda: self.connect_to(net, entry.get_text()))
            entry.connect("activate", lambda _e: self.connect_to(net, entry.get_text()))
            row = Gtk.Box(spacing=8)
            row.pack_start(show, True, True, 0)
            row.pack_end(go, False, False, 0)
            detail.pack_start(entry, False, False, 0)
            if error_text:
                detail.pack_start(label(error_text, "error", wrap=True), False, False, 0)
            detail.pack_start(row, False, False, 0)
            GLib.idle_add(lambda: entry.grab_focus() and False)
        else:
            row = Gtk.Box(spacing=8)
            if net["active"]:
                row.pack_start(button("Disconnect", on_click=self.disconnect), False, False, 0)
            else:
                row.pack_start(button("Connect", classes="primary",
                                      on_click=lambda: self.connect_to(net, None)), False, False, 0)
            row.pack_start(button("Forget", on_click=lambda: self.forget(net)), False, False, 0)
            detail.pack_start(row, False, False, 0)

        outer.pack_start(detail, False, False, 0)
        outer.show_all()

    def connect_to(self, net, password):
        if password is not None and len(password) < 8:
            self.expanded = (net["ssid"], "password", "Wi-Fi passwords are at least 8 characters.")
            self.load(rescan=False)
            return
        self.busy = True
        self.spinner.start()
        add_class(self.message, "muted")
        self.message.get_style_context().remove_class("error")
        self.message.set_text(f"Connecting to {net['ssid']}…")

        def done(result, error):
            self.busy = False
            self.spinner.stop()
            ok, text, needs_password = result if result else (False, str(error), False)
            if ok:
                self.expanded = None
                self.message.set_text(text)
            elif needs_password:
                self.expanded = (net["ssid"], "password", text)
                self.message.set_text("")
            else:
                self.expanded = None
                self.message.set_text(text)
            self.load(rescan=False)
            self.panel.refresh("network")

        in_background(lambda: system.wifi_connect(net["ssid"], password), done)

    def disconnect(self):
        self.expanded = None
        in_background(system.wifi_disconnect, lambda *_: (self.load(False), self.panel.refresh("network")))

    def forget(self, net):
        self.expanded = None
        in_background(lambda: system.wifi_forget(net["ssid"]),
                      lambda *_: (self.load(False), self.panel.refresh("network")))

    def on_switch(self, switch, _param):
        on = switch.get_active()
        self.message.set_text("Turning Wi-Fi on…" if on else "Turning Wi-Fi off…")
        in_background(lambda: system.set_wifi_enabled(on),
                      lambda *_: GLib.timeout_add(1800, lambda: self.load(rescan=on) and False))
        self.panel.refresh("network")


# ---------------------------------------------------------------- bluetooth

class BluetoothMenu(Popup):
    title_text = "Bluetooth"

    def __init__(self, panel):
        super().__init__(panel)
        self.busy = False
        self.open_mac = None
        self.nearby = []

        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", self.on_switch)
        self.header_extra.pack_start(self.switch, False, False, 0)

        self.paired_title = section("Your devices")
        self.paired_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.nearby_title = section("Nearby")
        self.nearby_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.message = label("", "muted", wrap=True)

        footer = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.find_button = button("Find devices", on_click=self.find)
        footer.pack_start(self.spinner, False, False, 0)
        footer.pack_end(self.find_button, False, False, 0)
        self.footer = footer

        for w in (self.paired_title, self.paired_box, self.nearby_title, self.nearby_box,
                  self.message, footer):
            self.body.pack_start(w, False, False, 0)

    def refresh(self):
        self.message.set_text("")
        self.nearby = []
        self.open_mac = None
        self.load()

    def load(self):
        self.spinner.start()
        in_background(lambda: (system.bt_status(), system.bt_devices()), self.show_result)

    def show_result(self, result, error):
        if not self.busy:
            self.spinner.stop()
        if error is not None:
            self.message.set_text(str(error))
            return
        status, devices = result

        self.switch.handler_block(self.switch_handler)
        self.switch.set_active(status["powered"])
        self.switch.handler_unblock(self.switch_handler)

        powered = status["powered"]
        for w in (self.paired_title, self.paired_box, self.nearby_title, self.nearby_box, self.footer):
            w.set_visible(powered)
        if not status["available"]:
            self.message.set_text("This computer has no Bluetooth.")
            return
        if not powered:
            self.message.set_text("Bluetooth is off.")
            return

        clear(self.paired_box)
        self.paired_title.set_visible(bool(devices))
        for dev in devices:
            self.paired_box.pack_start(self.device_row(dev, paired=True), False, False, 0)
        self.paired_box.show_all()
        self.show_nearby()
        if not devices and not self.nearby and not self.busy and not self.message.get_text():
            self.message.set_text("Put your headphones, speaker, mouse or keyboard in pairing mode, then choose Find devices.")

    def show_nearby(self):
        clear(self.nearby_box)
        self.nearby_title.set_visible(bool(self.nearby))
        for dev in self.nearby:
            self.nearby_box.pack_start(self.device_row(dev, paired=False), False, False, 0)
        self.nearby_box.show_all()

    def device_row(self, dev, paired):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b = Gtk.Button()
        b.set_can_focus(False)
        add_class(b, "row")
        box = Gtk.Box(spacing=10)
        box.pack_start(Icon("bluetooth", 16, on=True, connected=dev.get("connected", False)), False, False, 0)
        name = label(dev["name"], ellipsize=True)
        name.set_hexpand(True)
        box.pack_start(name, True, True, 0)
        if dev.get("connected"):
            box.pack_end(label("Connected", "good"), False, False, 0)
        elif not paired:
            box.pack_end(label("Pair", "muted"), False, False, 0)
        b.add(box)
        outer.pack_start(b, False, False, 0)

        if paired:
            b.connect("clicked", lambda _b: self.toggle_actions(dev))
            if self.open_mac == dev["mac"]:
                row = Gtk.Box(spacing=8)
                row.set_margin_start(34)
                if dev["connected"]:
                    row.pack_start(button("Disconnect", on_click=lambda: self.act(system.bt_disconnect, dev, "Disconnecting…")), False, False, 0)
                else:
                    row.pack_start(button("Connect", classes="primary", on_click=lambda: self.act(system.bt_connect, dev, f"Connecting to {dev['name']}…")), False, False, 0)
                row.pack_start(button("Forget", on_click=lambda: self.act(system.bt_forget, dev, "Removing…")), False, False, 0)
                outer.pack_start(row, False, False, 0)
        else:
            b.connect("clicked", lambda _b: self.pair(dev))
        return outer

    def toggle_actions(self, dev):
        if self.busy:
            return
        self.open_mac = None if self.open_mac == dev["mac"] else dev["mac"]
        self.load()

    def act(self, action, dev, text):
        self.busy = True
        self.spinner.start()
        self.message.set_text(text)

        def done(result, error):
            self.busy = False
            self.open_mac = None
            ok, msg = result if result else (False, str(error))
            self.message.set_text(msg if not ok or msg else "")
            self.load()
            self.panel.refresh("bluetooth")

        in_background(lambda: action(dev["mac"]), done)

    def find(self):
        if self.busy:
            return
        self.busy = True
        self.spinner.start()
        self.find_button.set_sensitive(False)
        self.message.set_text("Looking for devices (about 12 seconds)…")

        def done(result, error):
            self.busy = False
            self.spinner.stop()
            self.find_button.set_sensitive(True)
            self.nearby = result or []
            if error is not None:
                self.message.set_text(str(error))
            elif not self.nearby:
                self.message.set_text("Nothing found. Make sure the device is in pairing mode (often: hold its power button until a light flashes).")
            else:
                self.message.set_text("Choose a device to pair it.")
            self.show_nearby()

        in_background(system.bt_scan, done)

    def pair(self, dev):
        if self.busy:
            return
        self.busy = True
        self.spinner.start()
        self.message.set_text(f"Pairing with {dev['name']}…")

        def done(result, error):
            self.busy = False
            self.spinner.stop()
            ok, msg = result if result else (False, str(error))
            self.message.set_text(msg)
            if ok:
                self.nearby = [d for d in self.nearby if d["mac"] != dev["mac"]]
            self.load()
            self.panel.refresh("bluetooth")

        def on_code(text):
            GLib.idle_add(lambda: self.message.set_text(text) and False)

        in_background(lambda: system.bt_pair(dev["mac"], on_code), done)

    def on_switch(self, switch, _param):
        on = switch.get_active()
        self.message.set_text("Turning Bluetooth on…" if on else "Turning Bluetooth off…")

        def done(result, error):
            ok, msg = result if result else (False, str(error))
            self.message.set_text("" if ok else msg)
            self.nearby = []
            GLib.timeout_add(800, lambda: self.load() and False)
            self.panel.refresh("bluetooth")

        in_background(lambda: system.bt_set_powered(on), done)


# -------------------------------------------------------------------- sound

class VolumeRow(Gtk.Box):
    """Mute button, slider and percentage for one kind of device."""

    def __init__(self, kind, on_change):
        super().__init__(spacing=10)
        self.kind = kind
        self.on_change = on_change
        self.loading = False
        self.muted = False
        self.pending = None

        self.icon = Icon("speaker" if kind == "sink" else "mic", 20)
        self.mute_button = Gtk.Button()
        self.mute_button.set_can_focus(False)
        add_class(self.mute_button, "row")
        self.mute_button.add(self.icon)
        self.mute_button.connect("clicked", lambda _b: self.toggle_mute())
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_scale)
        self.value = label("", "muted", xalign=1.0)
        self.value.set_width_chars(4)
        self.pack_start(self.mute_button, False, False, 0)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.value, False, False, 0)

    def set_state(self, volume, muted):
        self.loading = True
        self.muted = muted
        self.scale.set_value(volume)
        self.loading = False
        self.show_icon(volume)

    def show_icon(self, volume):
        self.value.set_text("Off" if self.muted else f"{int(volume)}%")
        if self.kind == "sink":
            level = 0 if volume == 0 else (1 if volume < 50 else 2)
            self.icon.update(muted=self.muted, level=level)
        else:
            self.icon.update(muted=self.muted)

    def on_scale(self, scale):
        volume = int(scale.get_value())
        if self.loading:
            return
        if self.muted:
            self.muted = False
            in_background(lambda: system.set_mute(self.kind, False))
        self.show_icon(volume)
        # Dragging fires many changes; send the latest one at most every 80 ms.
        if self.pending is None:
            self.pending = GLib.timeout_add(80, self.send)

    def send(self):
        self.pending = None
        volume = int(self.scale.get_value())
        in_background(lambda: system.set_volume(self.kind, volume), lambda *_: self.on_change())
        return False

    def toggle_mute(self):
        self.muted = not self.muted
        self.show_icon(self.scale.get_value())
        muted = self.muted
        in_background(lambda: system.set_mute(self.kind, muted), lambda *_: self.on_change())


class SoundMenu(Popup):
    title_text = "Sound"

    def __init__(self, panel):
        super().__init__(panel)
        on_change = lambda: self.panel.refresh("sound")  # noqa: E731
        self.speaker = VolumeRow("sink", on_change)
        self.outputs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.mic_title = section("Microphone")
        self.mic = VolumeRow("source", on_change)
        self.inputs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.message = label("", "muted", wrap=True)
        self.speaker_title = section("Speakers")
        for w in (self.speaker_title, self.speaker, self.outputs, self.mic_title, self.mic, self.inputs, self.message):
            self.body.pack_start(w, False, False, 0)

    def refresh(self):
        in_background(lambda: (system.audio_status(), system.audio_devices("sink"), system.audio_devices("source")),
                      self.show_result)

    def show_result(self, result, error):
        if error is not None:
            self.message.set_text(str(error))
            return
        status, sinks, sources = result
        self.speaker.set_state(status["volume"], status["muted"])
        self.mic.set_state(status["mic_volume"], status["mic_muted"])
        self.speaker.set_visible(status["available"])
        self.speaker_title.set_visible(status["available"])
        self.mic.set_visible(status["mic_available"])
        self.mic_title.set_visible(status["mic_available"])
        self.fill_choices(self.outputs, sinks, "sink")
        self.fill_choices(self.inputs, sources, "source")
        if not status["available"] and not status["mic_available"]:
            self.message.set_text("No sound device found.")
        elif not status["mic_available"]:
            self.message.set_text("No microphone found. Plug in a headset to use one.")
        else:
            self.message.set_text("")
        self.message.set_visible(bool(self.message.get_text()))

    def fill_choices(self, box, devices, kind):
        clear(box)
        if len(devices) < 2:
            box.set_visible(False)
            return
        group = None
        for dev in devices:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, dev["label"])
            radio.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            radio.set_active(dev["default"])
            group = group or radio
            radio.connect("toggled", self.on_choice, kind, dev["name"])
            box.pack_start(radio, False, False, 0)
        box.set_visible(True)
        box.show_all()

    def on_choice(self, radio, kind, name):
        if radio.get_active():
            in_background(lambda: system.set_default_device(kind, name),
                          lambda *_: (self.refresh(), self.panel.refresh("sound")))


# --------------------------------------------------- brightness, battery, clock

class BrightnessMenu(Popup):
    title_text = "Screen brightness"

    def __init__(self, panel):
        super().__init__(panel)
        self.loading = False
        self.pending = None
        row = Gtk.Box(spacing=10)
        row.pack_start(Icon("sun", 20), False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_scale)
        self.value = label("", "muted", xalign=1.0)
        self.value.set_width_chars(4)
        row.pack_start(self.scale, True, True, 0)
        row.pack_start(self.value, False, False, 0)
        self.body.pack_start(row, False, False, 0)

    def refresh(self):
        in_background(system.brightness, self.show_result)

    def show_result(self, value, error):
        if value is None:
            return
        self.loading = True
        self.scale.set_value(value)
        self.value.set_text(f"{value}%")
        self.loading = False

    def on_scale(self, scale):
        self.value.set_text(f"{int(scale.get_value())}%")
        if not self.loading and self.pending is None:
            self.pending = GLib.timeout_add(60, self.send)

    def send(self):
        self.pending = None
        value = int(self.scale.get_value())
        in_background(lambda: system.set_brightness(value))
        return False


def battery_color(bat):
    if bat["charging"] or bat["full"]:
        return theme.C["good"]
    if bat["percent"] <= 10:
        return theme.C["bad"]
    if bat["percent"] <= 20:
        return theme.C["warn"]
    return theme.C["accent"]


class Gauge(Gtk.DrawingArea):
    """A ring that fills clockwise, for the battery level."""

    def __init__(self, size=132, width=11):
        super().__init__()
        self.fraction = 0.0
        self.color = theme.C["accent"]
        self.width = width
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def set(self, fraction, color):
        self.fraction = max(0.0, min(1.0, fraction))
        self.color = color
        self.queue_draw()

    def _draw(self, widget, cr):
        import math
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        radius = min(w, h) / 2 - self.width / 2 - 1
        cx, cy = w / 2, h / 2
        cr.set_line_width(self.width)
        cr.set_line_cap(1)
        cr.set_source_rgb(*theme.rgb(theme.C["border"]))
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if self.fraction > 0:
            cr.set_source_rgb(*theme.rgb(self.color))
            start = -math.pi / 2
            cr.arc(cx, cy, radius, start, start + 2 * math.pi * self.fraction)
            cr.stroke()
        return False


def stat_tile(title):
    """A small rounded box: grey caption above a bold value."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_border_width(10)
    box.pack_start(label(title, "section"), False, False, 0)
    value = label("", "stat-value", ellipsize=True)
    box.pack_start(value, False, False, 0)
    frame = Gtk.EventBox()
    add_class(frame, "stat")
    frame.add(box)
    return frame, value


class BatteryMenu(Popup):
    title_text = "Battery"

    def __init__(self, panel):
        super().__init__(panel)
        self.loading = False
        self.pending = None

        top = Gtk.Box(spacing=18)
        overlay = Gtk.Overlay()
        self.gauge = Gauge()
        overlay.add(self.gauge)
        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        middle.set_halign(Gtk.Align.CENTER)
        middle.set_valign(Gtk.Align.CENTER)
        self.percent = label("", "gauge-percent", xalign=0.5)
        self.state_icon = Icon("battery", 18, percent=100)
        middle.pack_start(self.percent, False, False, 0)
        middle.pack_start(self.state_icon, False, False, 0)
        overlay.add_overlay(middle)
        top.pack_start(overlay, False, False, 0)

        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        facts.set_valign(Gtk.Align.CENTER)
        self.status_tile, self.status_value = stat_tile("Status")
        self.time_tile, self.time_value = stat_tile("Time")
        facts.pack_start(self.status_tile, False, False, 0)
        facts.pack_start(self.time_tile, False, False, 0)
        top.pack_start(facts, True, True, 0)
        self.body.pack_start(top, False, False, 0)

        self.hint = label("", "warn", wrap=True)
        self.body.pack_start(self.hint, False, False, 0)

        # Screen brightness lives here on laptops: the battery is what it saves.
        self.bright_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.bright_box.pack_start(Gtk.Separator(), False, False, 2)
        self.bright_box.pack_start(section("Screen brightness"), False, False, 0)
        row = Gtk.Box(spacing=10)
        row.pack_start(Icon("sun", 18), False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_scale)
        self.bright_value = label("", "muted", xalign=1.0)
        self.bright_value.set_width_chars(4)
        row.pack_start(self.scale, True, True, 0)
        row.pack_start(self.bright_value, False, False, 0)
        self.bright_box.pack_start(row, False, False, 0)
        self.body.pack_start(self.bright_box, False, False, 0)

    def refresh(self):
        self.update(self.panel.last.get("battery"))
        in_background(system.brightness, self.show_brightness)

    def after_show(self):
        self.bright_box.set_visible(self.panel.last.get("brightness") is not None)
        self.hint.set_visible(bool(self.hint.get_text()))

    def show_brightness(self, value, error):
        self.bright_box.set_visible(value is not None)
        if value is None:
            return
        self.loading = True
        self.scale.set_value(value)
        self.bright_value.set_text(f"{value}%")
        self.loading = False

    def on_scale(self, scale):
        self.bright_value.set_text(f"{int(scale.get_value())}%")
        if not self.loading and self.pending is None:
            self.pending = GLib.timeout_add(60, self.send)

    def send(self):
        self.pending = None
        value = int(self.scale.get_value())
        in_background(lambda: system.set_brightness(value))
        return False

    def update(self, bat):
        if not bat:
            self.percent.set_text("—")
            self.gauge.set(0, theme.C["border"])
            self.status_value.set_text("No battery")
            self.time_value.set_text("—")
            self.hint.set_text("")
            self.hint.set_visible(False)
            return
        self.percent.set_text(f"{bat['percent']}%")
        self.gauge.set(bat["percent"] / 100, battery_color(bat))
        self.state_icon.update("battery", percent=bat["percent"], charging=bat["charging"],
                               plugged=bat["plugged"])
        if bat["charging"]:
            status = "Charging"
            when = f"Full in {duration(bat['minutes'])}" if bat["minutes"] else "Working it out…"
        elif bat["full"]:
            status, when = "Fully charged", "Plugged in"
        elif bat["plugged"]:
            status, when = "Plugged in", "Not charging"
        else:
            status = "On battery"
            when = f"{duration(bat['minutes'])} left" if bat["minutes"] else "Working it out…"
        self.status_value.set_text(status)
        self.time_value.set_text(when)
        if bat["percent"] <= 20 and not bat["plugged"]:
            self.hint.set_text("Battery is low. Plug in the charger to keep working.")
        else:
            self.hint.set_text("")
        self.hint.set_visible(bool(self.hint.get_text()))


class ClockMenu(Popup):
    title_text = "Today"

    def __init__(self, panel):
        super().__init__(panel)
        self.time = label("", "clock-big")
        self.date = label("", "muted")
        self.calendar = Gtk.Calendar()
        for w in (self.time, self.date, self.calendar):
            self.body.pack_start(w, False, False, 0)

    def refresh(self):
        now = datetime.datetime.now()
        self.time.set_text(now.strftime("%-I:%M %p"))
        self.date.set_text(now.strftime("%A, %-d %B %Y"))
        self.calendar.select_month(now.month - 1, now.year)
        self.calendar.select_day(now.day)


# -------------------------------------------------------------- power, tabs

class SystemMenu(Popup):
    """Opened from the logo: memory, how powerful the computer is set to be,
    the way into Settings and, on the live USB, the way to install."""

    title_text = "This computer"
    title_icon = "logo"

    def __init__(self, panel):
        super().__init__(panel)

        if panel.live:
            self.body.pack_start(label("You are trying OnlyBrowserOS from a USB stick. "
                                       "Nothing is kept when the computer turns off.", "muted", wrap=True),
                                 False, False, 0)
            self.body.pack_start(button("Install OnlyBrowserOS on this computer", Icon("install", 16),
                                        classes="primary", on_click=self.install), False, False, 0)
            self.body.pack_start(Gtk.Separator(), False, False, 2)

        # Memory: the one number that decides how this computer feels.
        mem_head = Gtk.Box(spacing=8)
        mem_head.pack_start(section("Memory"), False, False, 0)
        self.mem_text = label("", "muted", xalign=1.0)
        mem_head.pack_end(self.mem_text, False, False, 0)
        self.body.pack_start(mem_head, False, False, 0)
        self.mem_bar = Gtk.LevelBar.new_for_interval(0, 1)
        self.mem_bar.add_offset_value("low", 0.70)
        self.mem_bar.add_offset_value("high", 0.88)
        self.mem_bar.add_offset_value("full", 1.0)
        self.body.pack_start(self.mem_bar, False, False, 0)

        self.body.pack_start(Gtk.Separator(), False, False, 2)

        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.level_name = label("", "stat-value")
        self.level_detail = label("", "muted")
        words.pack_start(self.level_name, False, False, 0)
        words.pack_start(self.level_detail, False, False, 0)
        self.body.pack_start(words, False, False, 0)

        # Every setting lives in one place: the settings page in the browser.
        self.body.pack_start(button("Open Settings", Icon("settings", 16), classes="primary",
                                    on_click=self.open_settings), False, False, 0)
        self.body.pack_start(label("How powerful this computer is, text size, time zone, keyboard "
                                   "and password.", "muted", wrap=True), False, False, 0)

    def refresh(self):
        state = system.machine_state()
        memory = state.get("memory_mb") or system.memory_mb()
        automatic = bool(state.get("limit_is_automatic", True))
        limit = int(state.get("tab_limit", 2))
        level = levels.level_for(limit, automatic, memory)
        tabs = levels.tabs_for(level, memory) if automatic else limit
        self.level_name.set_text(levels.LEVELS[level][0])
        self.level_detail.set_text(f"{levels.LEVELS[level][1]} · {levels.tabs_text(tabs)} at once")
        self.show_memory()

    def show_memory(self):
        total, available = system.memory_usage()
        if not total:
            return
        used = total - available
        self.mem_bar.set_value(max(0.0, min(1.0, used / total)))
        self.mem_text.set_text(f"{used / 1024:.1f} of {total / 1024:.1f} GB in use")

    def open_settings(self):
        self.close_menu()
        in_background(system.open_settings)

    def install(self):
        self.close_menu()
        in_background(system.start_installer)


class PowerMenu(Popup):
    title_text = "Power"

    def __init__(self, panel):
        super().__init__(panel)
        grid = Gtk.Box(spacing=8, homogeneous=True)
        for text, icon, action, classes in (("Sleep", "moon", "suspend", "action"),
                                            ("Restart", "restart", "reboot", "action"),
                                            ("Shut down", "power", "poweroff", "action shutdown")):
            grid.pack_start(button(text, Icon(icon, 22), classes=classes, vertical=True,
                                   on_click=lambda a=action: self.power(a)), True, True, 0)
        self.body.pack_start(grid, False, False, 0)
        self.message = label("", "error", wrap=True)
        self.body.pack_start(self.message, False, False, 0)

    def after_show(self):
        self.message.set_visible(False)

    def power(self, action):
        def done(result, error):
            ok, msg = result if result else (False, str(error))
            if not ok:
                self.message.set_text(msg or "The computer refused.")
                self.message.set_visible(True)
        in_background(lambda: system.power(action), done)


# -------------------------------------------------------------------- panel

class BatteryAlert(Gtk.Window):
    """A battery warning in the middle of the screen. When the battery is
    nearly empty it counts down to a clean shutdown, so the browser saves the
    tabs instead of losing them when the power cuts out. Plugging in the
    charger closes it."""

    def __init__(self, panel):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.panel = panel
        self.countdown = None
        self.seconds = 0
        self.set_title("Battery")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER)
        add_class(self, "alert")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(28)
        box.set_size_request(420, -1)
        self.icon = Icon("battery", 56, percent=5)
        self.title = label("", "alert-title", xalign=0.5)
        self.text = label("", "muted", xalign=0.5, wrap=True)
        self.text.set_justify(Gtk.Justification.CENTER)
        buttons = Gtk.Box(spacing=10)
        buttons.set_halign(Gtk.Align.CENTER)
        self.ok_button = button("OK", classes="primary", on_click=self.dismiss)
        self.keep_button = button("Keep working", on_click=self.keep_working)
        self.shutdown_button = button("Shut down now", classes="danger", on_click=self.shut_down)
        for b in (self.keep_button, self.shutdown_button, self.ok_button):
            buttons.pack_start(b, False, False, 0)
        for w in (self.icon, self.title, self.text, buttons):
            box.pack_start(w, False, False, 0)
        self.add(box)
        self.connect("delete-event", lambda *_: self.dismiss() or True)

    def _show(self, ok, keep, shutdown):
        self.show_all()
        self.ok_button.set_visible(ok)
        self.keep_button.set_visible(keep)
        self.shutdown_button.set_visible(shutdown)
        self.present()

    def warn_low(self, percent):
        self.stop_countdown()
        self.icon.update("battery", percent=percent)
        self.title.set_text("Battery low")
        self.text.set_text(f"{percent}% left. Plug in the charger soon.")
        self._show(ok=True, keep=False, shutdown=False)

    def warn_critical(self, percent, can_postpone):
        self.icon.update("battery", percent=percent)
        self.title.set_text("Battery almost empty")
        self.seconds = SHUTDOWN_SECONDS
        self.show_countdown()
        self._show(ok=False, keep=can_postpone, shutdown=True)
        if self.countdown is None:
            self.countdown = GLib.timeout_add_seconds(1, self.tick)

    def show_countdown(self):
        self.text.set_text("Plug in the charger now. To keep your tabs safe, the computer "
                           f"will shut down in {self.seconds} seconds.")

    def tick(self):
        self.seconds -= 1
        if self.seconds <= 0:
            self.countdown = None
            self.shut_down()
            return False
        self.show_countdown()
        return True

    def stop_countdown(self):
        if self.countdown is not None:
            GLib.source_remove(self.countdown)
            self.countdown = None

    def dismiss(self):
        self.stop_countdown()
        self.hide()

    def keep_working(self):
        self.dismiss()

    def shut_down(self):
        self.stop_countdown()
        self.text.set_text("Shutting down…")
        self.keep_button.set_visible(False)
        self.shutdown_button.set_visible(False)
        in_background(lambda: system.power("poweroff"))


class DiskAlert(Gtk.Window):
    """Space for downloads is nearly gone. Shown once each time it runs low:
    with a full disk the browser can no longer save pages, passwords or tabs."""

    def __init__(self, panel):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.panel = panel
        self.set_title("Space")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER)
        add_class(self, "alert")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(28)
        box.set_size_request(420, -1)
        self.title = label("This computer is almost full", "alert-title", xalign=0.5)
        self.text = label("", "muted", xalign=0.5, wrap=True)
        self.text.set_justify(Gtk.Justification.CENTER)
        buttons = Gtk.Box(spacing=10)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.pack_start(button("Later", on_click=self.hide), False, False, 0)
        buttons.pack_start(button("Open Downloads", classes="primary", on_click=self.open_downloads), False, False, 0)
        icon = Icon("install", 48)
        icon.set_halign(Gtk.Align.CENTER)
        for w in (icon, self.title, self.text, buttons):
            box.pack_start(w, False, False, 0)
        self.add(box)
        self.connect("delete-event", lambda *_: self.hide() or True)

    def warn(self, free_mb):
        where = "memory" if self.panel.live else "space"
        self.text.set_text(f"Only {free_mb} MB of {where} is left. Delete downloads you no longer "
                           "need, so the browser can keep saving your tabs and passwords.")
        self.show_all()
        self.present()

    def open_downloads(self):
        self.hide()
        in_background(lambda: system.open_in_browser(system.DOWNLOADS_URL))


class LevelOSD(Gtk.Window):
    """The level of volume or brightness, shown above the taskbar for a moment
    after a laptop key changed it (the keys run /usr/lib/onlybrowseros/media-key)."""

    HIDE_AFTER_MS = 1500

    def __init__(self, panel):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.panel = panel
        self.hide_timer = None
        add_class(self, "osd")
        box = Gtk.Box(spacing=12)
        box.set_border_width(14)
        self.icon = Icon("speaker", 20, level=2)
        self.bar = Gtk.LevelBar()
        self.bar.set_min_value(0)
        self.bar.set_max_value(100)
        self.bar.set_valign(Gtk.Align.CENTER)
        self.bar.set_size_request(180, -1)
        self.value = label("", "osd-value", xalign=1.0)
        self.value.set_width_chars(4)
        box.pack_start(self.icon, False, False, 0)
        box.pack_start(self.bar, True, True, 0)
        box.pack_start(self.value, False, False, 0)
        self.add(box)

    def show_level(self, kind, level, muted):
        level = max(0, min(100, level))
        if kind == "brightness":
            self.icon.update("sun")
        elif kind == "microphone":
            self.icon.update("mic", muted=muted)
        else:
            self.icon.update("speaker", level=0 if level == 0 else (1 if level < 50 else 2), muted=muted)
        self.bar.set_value(0 if muted else level)
        self.value.set_text("Off" if muted else f"{level}%")
        self.show_all()
        geo = self.panel.monitor_geometry()
        width, height = self.get_size()
        self.move(geo.x + (geo.width - width) // 2, geo.y + geo.height - PANEL_HEIGHT - height - 24)
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
        self.hide_timer = GLib.timeout_add(self.HIDE_AFTER_MS, self._hide)

    def _hide(self):
        self.hide_timer = None
        self.hide()
        return False


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("OnlyBrowserOS taskbar")
        self.set_decorated(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # Clicking the bar must not take focus from an open menu, or the menu
        # would close before the click could toggle it.
        self.set_accept_focus(False)
        add_class(self, "panel")

        self.live = system.is_live()
        self.menus = {}
        self.last = {}
        self.inflight = set()
        self.again = set()
        self.debounce = {}
        self.battery_alert = None
        self.battery_stage = None   # None, "low", "critical" or "last"
        self.battery_ticks = 0

        bar = Gtk.Box(spacing=2)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        self.add(bar)

        left = Gtk.Box(spacing=6)
        bar.pack_start(left, False, False, 0)
        self.logo_button = self.tray_button(left, theme.brand(24, 11), "This computer: memory and tabs", SystemMenu)
        add_class(self.logo_button, "logo")
        if self.live:
            left.pack_start(button("Install OnlyBrowserOS", Icon("install", 16), classes="install",
                                   on_click=lambda: in_background(system.start_installer),
                                   tooltip="Put OnlyBrowserOS on this computer's disk"), False, False, 0)

        right = Gtk.Box(spacing=4)
        bar.pack_end(right, False, False, 0)

        # Status icons share one rounded tray, the way phones group them.
        tray = Gtk.Box(spacing=0)
        add_class(tray, "tray")
        right.pack_start(tray, False, False, 0)

        self.net_icon = Icon("wifi", 18, level=0)
        self.net_button = self.tray_button(tray, self.net_icon, "Network", NetworkMenu)

        self.bt_icon = Icon("bluetooth", 17, on=False)
        self.bt_button = self.tray_button(tray, self.bt_icon, "Bluetooth", BluetoothMenu, hidden=True)

        self.sound_icon = Icon("speaker", 18, level=2)
        self.sound_button = self.tray_button(tray, self.sound_icon, "Sound", SoundMenu)

        # A backlight without a battery (an all-in-one PC); laptops get the
        # slider inside the battery menu instead.
        self.bright_button = self.tray_button(tray, Icon("sun", 18), "Screen brightness", BrightnessMenu, hidden=True)

        self.battery_icon = Icon("battery", 24, percent=100)
        self.battery_label = label("", "battery-text")
        self.battery_button = self.tray_button(tray, self.battery_icon, "Battery", BatteryMenu,
                                               text=self.battery_label, hidden=True)

        self.clock_label = label("", "clock-time", xalign=1.0)
        self.clock_button = self.tray_button(right, None, "Calendar", ClockMenu, text=self.clock_label)

        self.power_button = self.tray_button(right, Icon("power", 18), "Sleep, restart or shut down", PowerMenu)

        screen = self.get_screen()
        screen.connect("size-changed", lambda *_: self.place())
        screen.connect("monitors-changed", lambda *_: self.place())

    def tray_button(self, box, icon, tooltip, menu_class, text=None, hidden=False):
        b = Gtk.Button()
        b.set_can_focus(False)
        inner = Gtk.Box(spacing=6)
        if icon is not None:
            inner.pack_start(icon, False, False, 0)
        if text is not None:
            inner.pack_start(text, False, False, 0)
        b.add(inner)
        b.set_tooltip_text(tooltip)
        b.connect("clicked", lambda _b: self.toggle(menu_class, b))
        if hidden:
            b.set_no_show_all(True)
            inner.show_all()
        box.pack_start(b, False, False, 0)
        return b

    def toggle(self, menu_class, anchor):
        menu = self.menus.get(menu_class)
        if menu is None:
            menu = self.menus[menu_class] = menu_class(self)
        for other in self.menus.values():
            if other is not menu and other.get_visible():
                other.close_menu()
        if menu.get_visible():
            menu.close_menu()
        else:
            menu.open(anchor)

    def monitor_geometry(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_geometry()

    def place(self):
        geo = self.monitor_geometry()
        self.set_size_request(geo.width, PANEL_HEIGHT)
        self.resize(geo.width, PANEL_HEIGHT)
        self.move(geo.x, geo.y + geo.height - PANEL_HEIGHT)
        return False

    def start(self):
        self.place()
        self.show_all()
        self.place()
        self.tick_clock()
        for what in ("network", "sound", "bluetooth", "battery", "brightness"):
            self.refresh(what)
        GLib.timeout_add_seconds(30, self.poll)
        GLib.timeout_add_seconds(15, self.poll_battery)
        self.disk_alert = None
        self.disk_warned = False
        GLib.timeout_add_seconds(60, lambda: self.check_space() and False)
        GLib.timeout_add_seconds(600, self.check_space)

        system.watch(["nmcli", "monitor"], lambda _line: self.soon("network"))
        self.watch_osd()
        self.watch_screens()

        def on_audio_event(line):
            # Only device changes; our own pactl calls show up as client events.
            if " on sink" in line or " on source" in line or " on server" in line:
                self.soon("sound")
        system.watch(["pactl", "subscribe"], on_audio_event)

    def watch_osd(self):
        path = system.runtime_dir() / "osd"
        self.osd = None
        self.osd_monitor = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)

        def changed(_monitor, _file, _other, event):
            if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
                return
            try:
                kind, level, muted = path.read_text().split()
                level, muted = int(level), muted == "1"
            except (OSError, ValueError):
                return
            if self.osd is None:
                self.osd = LevelOSD(self)
            self.osd.show_level(kind, level, muted)
            self.refresh("brightness" if kind == "brightness" else "sound")

        self.osd_monitor.connect("changed", changed)

    def watch_screens(self):
        """A TV or projector plugged in shows the same picture (udev touches
        the file; see 90-onlybrowseros-display.rules)."""
        in_background(lambda: system.arrange_screens(only_if_needed=True))
        self.screen_timer = None
        self.screen_monitor = Gio.File.new_for_path("/run/onlybrowseros/display-changed").monitor_file(
            Gio.FileMonitorFlags.NONE, None)

        def arrange():
            self.screen_timer = None
            in_background(system.arrange_screens)
            return False

        def changed(*_):
            # A plug sends several events; act once the screen has settled.
            if self.screen_timer is None:
                self.screen_timer = GLib.timeout_add(1500, arrange)

        self.screen_monitor.connect("changed", changed)

    def soon(self, what):
        """Called from watcher threads: refresh once things settle."""
        def schedule():
            if what not in self.debounce:
                self.debounce[what] = GLib.timeout_add(400, fire)
            return False

        def fire():
            self.debounce.pop(what, None)
            self.refresh(what)
            return False

        GLib.idle_add(schedule)

    def poll(self):
        # Network and sound changes arrive from their watchers straight away;
        # asking again only every few minutes catches a watcher that died.
        # Bluetooth has no watcher.
        self.poll_ticks = getattr(self, "poll_ticks", 0) + 1
        self.refresh("bluetooth")
        if self.poll_ticks % 6 == 0:
            self.refresh("network")
            self.refresh("sound")
        return True

    def poll_battery(self):
        # Every minute, or every 15 seconds once the battery runs low.
        self.battery_ticks += 1
        last = self.last.get("battery")
        running_low = last is not None and not last["plugged"] and last["percent"] <= LOW_BATTERY + 5
        if running_low or self.battery_ticks % 4 == 0:
            self.refresh("battery")
        return True

    LOW_SPACE_MB = 400      # warn below this much free space
    SPACE_OK_MB = 1024      # and again only after it has been above this

    def check_space(self):
        def done(free, error):
            if free is None:
                return
            if free >= self.SPACE_OK_MB:
                self.disk_warned = False
            elif free < self.LOW_SPACE_MB and not self.disk_warned:
                self.disk_warned = True
                if self.disk_alert is None:
                    self.disk_alert = DiskAlert(self)
                self.disk_alert.warn(free)
        in_background(system.free_space_mb, done)
        return True

    def check_battery(self, b):
        if b is None or b["plugged"] or b["charging"]:
            self.battery_stage = None
            if self.battery_alert is not None and self.battery_alert.get_visible():
                self.battery_alert.dismiss()
            return
        if self.battery_alert is None:
            self.battery_alert = BatteryAlert(self)
        percent = b["percent"]
        if percent <= LAST_CHANCE_BATTERY and self.battery_stage != "last":
            self.battery_stage = "last"
            self.battery_alert.warn_critical(percent, can_postpone=False)
        elif percent <= CRITICAL_BATTERY and self.battery_stage not in ("critical", "last"):
            self.battery_stage = "critical"
            self.battery_alert.warn_critical(percent, can_postpone=True)
        elif percent <= LOW_BATTERY and self.battery_stage is None:
            self.battery_stage = "low"
            self.battery_alert.warn_low(percent)

    def refresh(self, what):
        if what in self.inflight:
            self.again.add(what)
            return
        self.inflight.add(what)
        work = {
            "network": system.network_status,
            "sound": system.audio_status,
            "bluetooth": system.bt_status,
            "battery": system.battery,
            "brightness": system.brightness,
        }[what]

        def done(result, error):
            self.inflight.discard(what)
            if error is None:
                self.last[what] = result
                getattr(self, "show_" + what)(result)
            else:
                print(f"taskbar: {what}: {error}", file=sys.stderr)
            if what in self.again:
                self.again.discard(what)
                self.refresh(what)

        in_background(work, done)

    # --- showing state on the bar

    def show_network(self, s):
        if s["kind"] == "ethernet" and s["connected"]:
            self.net_icon.update("ethernet")
            tip = "Connected with a network cable"
        elif s["kind"] == "wifi" and s["connected"]:
            self.net_icon.update("wifi", level=wifi_bars(s["signal"]))
            tip = f"Wi-Fi: {s['ssid']}"
        elif s["connecting"]:
            self.net_icon.update("wifi" if s["kind"] == "wifi" else "ethernet", connecting=True, dim=True)
            tip = "Connecting…"
        elif s["has_wifi"] and not s["wifi_enabled"]:
            self.net_icon.update("wifi", off=True)
            tip = "Wi-Fi is off"
        elif s["has_wifi"]:
            self.net_icon.update("wifi", level=0)
            tip = "Not connected. Click to choose a Wi-Fi network."
        else:
            self.net_icon.update("ethernet", off=True)
            tip = "Not connected"
        self.net_button.set_tooltip_text(tip)
        menu = self.menus.get(NetworkMenu)
        if menu is not None:
            menu.status_changed()

    def show_sound(self, s):
        if not s["available"]:
            self.sound_icon.update("speaker", muted=True)
            self.sound_button.set_tooltip_text("No sound device")
            return
        level = 0 if s["volume"] == 0 else (1 if s["volume"] < 50 else 2)
        self.sound_icon.update("speaker", level=level, muted=s["muted"])
        self.sound_button.set_tooltip_text("Sound off" if s["muted"] else f"Volume {s['volume']}%")

    def show_bluetooth(self, s):
        self.bt_button.set_visible(s["available"])
        if not s["available"]:
            return
        self.bt_icon.update("bluetooth", on=s["powered"], connected=bool(s["connected"]))
        if not s["powered"]:
            tip = "Bluetooth is off"
        elif s["connected"]:
            tip = "Bluetooth: " + ", ".join(s["connected"])
        else:
            tip = "Bluetooth is on"
        self.bt_button.set_tooltip_text(tip)

    def show_battery(self, b):
        self.battery_button.set_visible(b is not None)
        self.bright_button.set_visible(b is None and self.last.get("brightness") is not None)
        self.check_battery(b)
        if b is None:
            return
        self.battery_icon.update("battery", percent=b["percent"], charging=b["charging"], plugged=b["plugged"])
        self.battery_label.set_text(f"{b['percent']}%")
        ctx = self.battery_label.get_style_context()
        ctx.remove_class("critical")
        ctx.remove_class("low")
        if not b["plugged"] and b["percent"] <= 10:
            ctx.add_class("critical")
        elif not b["plugged"] and b["percent"] <= 20:
            ctx.add_class("low")
        tip = f"Battery {b['percent']}%"
        if b["charging"]:
            tip += ", charging"
        elif b["minutes"] and not b["plugged"]:
            tip += f", about {duration(b['minutes'])} left"
        self.battery_button.set_tooltip_text(tip)
        menu = self.menus.get(BatteryMenu)
        if menu is not None and menu.get_visible():
            menu.update(b)

    def show_brightness(self, value):
        self.bright_button.set_visible(value is not None and self.last.get("battery") is None)

    def tick_clock(self):
        time.tzset()  # the installer or a time zone change may have moved /etc/localtime
        now = datetime.datetime.now()
        self.clock_label.set_text(now.strftime("%-I:%M %p"))
        self.clock_button.set_tooltip_text(now.strftime("%A, %-d %B %Y"))
        GLib.timeout_add_seconds(max(1, 60 - now.second), self.tick_clock)
        return False


def main():
    set_process_name("obos-panel")
    theme.apply(CSS)
    panel = Panel()
    panel.start()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
