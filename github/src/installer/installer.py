#!/usr/bin/env python3
"""
OnlyBrowserOS installer.

A welcome screen, then three short steps: choose a disk, create the account,
check and install. Anything most people never need (keyboard layout, tab
limit, password at start-up, computer name) waits behind "Advanced options".
install-helper, run as root through sudo, then does the disk work while this
window shows progress.

    installer.py             opened from the taskbar
    installer.py --welcome   opened when the live USB starts: "Install" or "Try it first"
"""

import ctypes
import json
import math
import os
import re
import subprocess
import sys
import threading
import unicodedata
import urllib.request
from pathlib import Path

from gi.repository import GLib

GLib.set_prgname("obos-installer")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "panel"))
import levels  # noqa: E402
import theme  # noqa: E402
from keyboards import KEYBOARDS  # noqa: E402
from icons import Icon  # noqa: E402
from theme import C, add_class  # noqa: E402

LIB = "/usr/lib/onlybrowseros"
HELPER = f"{LIB}/install-helper"
MIN_DISK = 8 * 1024 ** 3
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "onlybrowseros"

RESERVED = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news",
    "uucp", "proxy", "www-data", "backup", "list", "irc", "nobody", "messagebus",
    "polkitd", "obos", "sudo", "audio", "video", "netdev", "plugdev", "bluetooth",
    "input", "render",
}

TIPS = [
    "Everything happens in the browser: mail, video calls, films and documents.",
    "OnlyBrowserOS keeps only as many tabs open as this computer can handle.",
    "Security updates install by themselves in the background.",
    "Wi-Fi, sound, battery and power are always in the bar at the bottom of the screen.",
]

WIZARD = ["disk", "account", "computer", "confirm"]
ORDER = ["welcome"] + WIZARD

CSS = """
window.installer { background-color: {bg}; color: {text}; }
.installer .hero-title { font-size: 40px; font-weight: 800; color: {text}; }
.installer .page-title { font-size: 30px; font-weight: 800; color: {text}; }
.installer .lead { font-size: 16px; color: {muted}; }
.installer .feature-title { font-weight: 700; font-size: 15px; color: {text}; }
.installer .feature-text { color: {muted}; font-size: 12px; }
.installer .step-count { color: {faint}; font-weight: 600; }
.installer .field { background-color: {surface}; border: 1px solid {border}; border-radius: 14px; }
.installer .field.focused { border-color: {accent}; box-shadow: 0 0 0 3px {accent_soft}; }
.installer .field entry {
  border: none; box-shadow: none; background: transparent; padding: 0; min-height: 24px; font-size: 15px;
}
.installer .field-label { color: {muted}; font-size: 12px; }
.installer .field-icon { color: {muted}; }
.installer button.disk { background-color: {surface}; border: 1px solid {border}; border-radius: 16px; padding: 14px 18px; }
.installer button.disk:hover { background-color: #fafcff; border-color: #b9cdf0; }
.installer button.disk.selected { border: 2px solid {accent}; background-color: #f5f9ff; padding: 13px 17px; }
.installer button.disk:disabled { background-color: {bg}; }
.installer button.disk:disabled label { color: {faint}; }
.installer .disk-title { font-weight: 700; font-size: 15px; }
.installer .chip.recommended { background-color: #e3f5ea; color: {good_text}; }
.installer .status-line { font-size: 14px; color: {muted}; }
.installer .advanced { background-color: {surface}; border: 1px solid {border}; border-radius: 16px; }
.installer .summary-value { font-weight: 600; }
.installer button.next { border-radius: 999px; padding: 10px 28px; font-size: 15px; }
.installer button.back { padding: 6px 10px; color: {muted}; font-weight: 600; }
.installer button.back:hover { color: {text}; }
"""


# ------------------------------------------------------------ machine facts

def memory_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return 2048


def power_state():
    """'battery', 'plugged' or 'desktop'."""
    root = Path("/sys/class/power_supply")
    has_battery = False
    try:
        for dev in root.iterdir():
            kind = (dev / "type").read_text().strip()
            if kind == "Battery" and not (dev / "scope").exists():
                has_battery = True
                if (dev / "status").read_text().strip() == "Discharging":
                    return "battery"
    except OSError:
        pass
    return "plugged" if has_battery else "desktop"


def timezones():
    regions = {}
    try:
        from zoneinfo import available_timezones
        names = available_timezones()
    except ImportError:
        names = set()
    for name in names:
        m = re.fullmatch(r"(Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific)/([A-Za-z0-9_+/-]+)", name)
        if m:
            regions.setdefault(m.group(1), []).append(m.group(2))
    for cities in regions.values():
        cities.sort()
    return regions


def current_timezone():
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def detect_timezone():
    """Ask the same look-up service Ubuntu's installer uses. Only works online;
    returns None otherwise."""
    try:
        with urllib.request.urlopen("https://geoip.ubuntu.com/lookup", timeout=5) as r:
            text = r.read(4096).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    m = re.search(r"<TimeZone>([A-Za-z0-9_+/-]+)</TimeZone>", text)
    return m.group(1) if m else None


def human_size(n):
    # Decimal gigabytes, the way disks are sold.
    return f"{n / 1e9:.0f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def raid_controller():
    """An Intel storage controller in RAID (RST) mode hides its disks from
    Linux; the firmware setting has to go back to AHCI."""
    for dev in Path("/sys/bus/pci/devices").glob("*"):
        try:
            if (dev / "class").read_text().startswith("0x0104") and \
                    (dev / "vendor").read_text().strip() == "0x8086":
                return True
        except OSError:
            continue
    return False


def list_disks():
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RO,FSTYPE,LABEL,MOUNTPOINTS"],
            capture_output=True, text=True, timeout=10).stdout
        data = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []

    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk" or dev.get("ro") in (True, 1, "1"):
            continue
        if dev["name"].startswith(("zram", "loop", "sr", "ram", "fd")):
            continue
        parts = dev.get("children") or []
        everything = [dev] + parts
        mounts = [m for d in everything for m in (d.get("mountpoints") or []) if m]
        fstypes = {(d.get("fstype") or "").lower() for d in everything}
        labels = {(d.get("label") or "") for d in everything}
        size = int(dev.get("size") or 0)

        reason = ""
        if "ONLYBROWSEROS" in labels or any(m.startswith("/run/live") for m in mounts):
            reason = "This is the USB stick OnlyBrowserOS is running from."
        elif size < MIN_DISK:
            reason = "Too small: OnlyBrowserOS needs at least 8 GB."
        elif any(not m.startswith("/media/") and m != "[SWAP]" for m in mounts):
            reason = "In use."

        if "ntfs" in fstypes or "bitlocker" in fstypes:
            contents, windows = "Has Windows or Windows files on it", True
        elif "onlybrowseros" in labels:
            contents, windows = "Has OnlyBrowserOS on it", False
        elif fstypes & {"ext4", "ext3", "btrfs", "xfs"}:
            contents, windows = "Has Linux on it", False
        elif fstypes & {"vfat", "exfat"}:
            contents, windows = "Has files on it", False
        elif parts:
            contents, windows = "Has partitions on it", False
        else:
            contents, windows = "Empty", False

        transport = (dev.get("tran") or "").lower()
        kind = {"usb": "USB", "mmc": "Memory card"}.get(transport, "Internal")
        model = (dev.get("model") or "").strip() or ("USB drive" if kind == "USB" else "Disk")
        disks.append({
            "path": dev["path"],
            "title": f"{human_size(size)} disk",
            "model": model,
            "kind": kind,
            "detail": contents,
            "short": f"the {human_size(size)} disk ({model})",
            "size": size,
            "windows": windows,
            "reason": reason,
        })
    return disks


def username_from(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = ascii_name.split()
    candidate = re.sub(r"[^a-z0-9]", "", words[0]) if words else ""
    if not candidate or not candidate[0].isalpha():
        candidate = "user"
    candidate = candidate[:30]
    if candidate in RESERVED:
        candidate += "1"
    return candidate


def valid_hostname(name):
    return re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name) is not None


def set_process_name(name):
    try:
        ctypes.CDLL("libc.so.6").prctl(15, name.encode()[:15] + b"\0", 0, 0, 0)
    except (OSError, AttributeError):
        pass


# ----------------------------------------------------------------- widgets

def label(text="", classes="", wrap=True, xalign=0.0, selectable=False):
    widget = Gtk.Label(label=text, xalign=xalign)
    if classes:
        add_class(widget, classes)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_max_width_chars(64)
    if xalign == 0.5:
        widget.set_justify(Gtk.Justification.CENTER)
    widget.set_selectable(selectable)
    return widget


class Glyph(Gtk.DrawingArea):
    """A symbol in a circle. style "soft": pale circle, coloured symbol;
    "solid": coloured circle, white symbol; "plain": the symbol alone."""

    def __init__(self, kind, size=24, color="accent", style="soft"):
        super().__init__()
        self.kind, self.color, self.style = kind, color, style
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_kind(self, kind, color=None):
        self.kind = kind
        self.color = color or self.color
        self.queue_draw()

    def _draw(self, widget, cr):
        side = min(widget.get_allocated_width(), widget.get_allocated_height())
        cr.translate((widget.get_allocated_width() - side) / 2, (widget.get_allocated_height() - side) / 2)
        cr.scale(side / 24, side / 24)
        r, g, b = theme.rgb(C.get(self.color, self.color))
        cr.set_line_cap(1)
        cr.set_line_join(1)
        if self.style != "plain":
            cr.arc(12, 12, 12, 0, 2 * math.pi)
            if self.style == "solid":
                cr.set_source_rgb(r, g, b)
            else:
                cr.set_source_rgba(r, g, b, 0.14)
            cr.fill()
            # The symbol fills the middle half of the circle.
            cr.translate(12, 12)
            cr.scale(0.5, 0.5)
            cr.translate(-12, -12)
        if self.style == "solid":
            cr.set_source_rgb(1, 1, 1)
        else:
            cr.set_source_rgb(r, g, b)
        GLYPHS.get(self.kind, _glyph_warn)(cr)
        return False


def _glyph_good(cr):
    cr.set_line_width(3)
    cr.move_to(5, 12.5)
    cr.line_to(10, 17.5)
    cr.line_to(19.5, 7)
    cr.stroke()


def _glyph_warn(cr):
    cr.set_line_width(3)
    cr.move_to(12, 4.5)
    cr.line_to(12, 13.5)
    cr.stroke()
    cr.arc(12, 19, 1.9, 0, 2 * math.pi)
    cr.fill()


def _glyph_bad(cr):
    cr.set_line_width(3)
    cr.move_to(6, 6)
    cr.line_to(18, 18)
    cr.move_to(18, 6)
    cr.line_to(6, 18)
    cr.stroke()


def _glyph_disk(cr):
    theme.rounded_rect(cr, 2.5, 4.5, 19, 15, 3)
    cr.fill()
    cr.save()
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(2.5, 12.8, 19, 1.4)
    cr.fill()
    for x in (15.5, 18.5):
        cr.arc(x, 16.6, 1.2, 0, 2 * math.pi)
        cr.fill()
    cr.restore()


def _glyph_user(cr):
    cr.arc(12, 7.5, 5, 0, 2 * math.pi)
    cr.fill()
    cr.arc(12, 23, 10, math.pi, 2 * math.pi)
    cr.fill()


def _glyph_download(cr):
    cr.set_line_width(2.8)
    cr.move_to(12, 2.5)
    cr.line_to(12, 15)
    cr.move_to(6.5, 9.5)
    cr.line_to(12, 15)
    cr.line_to(17.5, 9.5)
    cr.move_to(4, 20.5)
    cr.line_to(20, 20.5)
    cr.stroke()


def _glyph_bolt(cr):
    cr.move_to(13.5, 2)
    cr.line_to(5, 13.5)
    cr.line_to(11, 13.5)
    cr.line_to(9.5, 22)
    cr.line_to(19, 10)
    cr.line_to(13, 10)
    cr.close_path()
    cr.fill()


def _glyph_shield(cr):
    cr.set_line_width(2.4)
    cr.move_to(12, 2.5)
    cr.line_to(20, 5.5)
    cr.curve_to(20, 14, 16.5, 19, 12, 21.5)
    cr.curve_to(7.5, 19, 4, 14, 4, 5.5)
    cr.close_path()
    cr.stroke()
    cr.move_to(8.3, 11.8)
    cr.line_to(11, 14.5)
    cr.line_to(15.8, 9.3)
    cr.stroke()


def _glyph_smile(cr):
    cr.set_line_width(2.4)
    cr.arc(12, 12, 9.5, 0, 2 * math.pi)
    cr.stroke()
    for x in (8.7, 15.3):
        cr.arc(x, 9.5, 1.5, 0, 2 * math.pi)
        cr.fill()
    cr.arc(12, 12.5, 5, math.radians(25), math.radians(155))
    cr.stroke()


def _glyph_gauge(level):
    """A speedometer whose needle points left, up or right."""
    angle = math.radians({"low": 205, "mid": 270, "high": 335}[level])

    def draw(cr):
        cr.set_line_width(2.6)
        cr.arc(12, 14.5, 9.5, math.radians(160), math.radians(380))
        cr.stroke()
        cr.move_to(12, 14.5)
        cr.line_to(12 + 7 * math.cos(angle), 14.5 + 7 * math.sin(angle))
        cr.stroke()
        cr.arc(12, 14.5, 2.3, 0, 2 * math.pi)
        cr.fill()
    return draw


GLYPHS = {
    "good": _glyph_good, "warn": _glyph_warn, "bad": _glyph_bad, "disk": _glyph_disk,
    "user": _glyph_user, "download": _glyph_download, "bolt": _glyph_bolt,
    "shield": _glyph_shield, "smile": _glyph_smile,
    "gauge-low": _glyph_gauge("low"), "gauge-mid": _glyph_gauge("mid"), "gauge-high": _glyph_gauge("high"),
}


class SelectDot(Gtk.DrawingArea):
    """The round tick at the start of a disk card."""

    def __init__(self, size=24):
        super().__init__()
        self.selected = False
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_selected(self, selected):
        self.selected = selected
        self.queue_draw()

    def _draw(self, widget, cr):
        side = min(widget.get_allocated_width(), widget.get_allocated_height())
        cr.scale(side / 24, side / 24)
        if self.selected:
            cr.arc(12, 12, 11, 0, 2 * math.pi)
            cr.set_source_rgb(*theme.rgb(C["accent"]))
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(2.6)
            cr.set_line_cap(1)
            cr.set_line_join(1)
            cr.move_to(7, 12.3)
            cr.line_to(10.5, 15.8)
            cr.line_to(17, 8.8)
            cr.stroke()
        else:
            cr.arc(12, 12, 10, 0, 2 * math.pi)
            cr.set_source_rgb(*theme.rgb("#b9c3d3"))
            cr.set_line_width(2)
            cr.stroke()
        return False


class Illustration(Gtk.DrawingArea):
    """A laptop with the web on its screen, for the welcome page."""

    def __init__(self, width=300, height=150):
        super().__init__()
        self.set_size_request(width, height)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        scale = min(w / 320, h / 180)
        cr.translate((w - 320 * scale) / 2, (h - 180 * scale) / 2)
        cr.scale(scale, scale)
        cr.set_line_cap(1)

        cr.save()
        cr.translate(160, 160)
        cr.scale(1, 0.16)
        cr.arc(0, 0, 150, 0, 2 * math.pi)
        cr.restore()
        cr.set_source_rgb(*theme.rgb("#dfeafa"))
        cr.fill()

        cr.set_line_width(6)
        for (x1, y1, x2, y2), colour in (((52, 42, 72, 54), "#facc15"), ((42, 88, 66, 88), "#facc15"),
                                         ((52, 134, 72, 122), "#8bd37a"), ((268, 42, 248, 54), "#facc15"),
                                         ((278, 88, 254, 88), "#facc15"), ((268, 134, 248, 122), "#8bd37a")):
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.set_source_rgb(*theme.rgb(colour))
            cr.stroke()

        theme.rounded_rect(cr, 88, 18, 144, 106, 10)
        cr.set_source_rgb(*theme.rgb("#1e2a4a"))
        cr.fill()
        theme.rounded_rect(cr, 96, 26, 128, 90, 4)
        cr.set_source_rgb(*theme.rgb("#9cc6ff"))
        cr.fill()
        theme.rounded_rect(cr, 110, 38, 100, 66, 6)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        for i in range(3):
            cr.arc(118 + i * 7, 46, 2, 0, 2 * math.pi)
            cr.set_source_rgb(*theme.rgb("#9cc6ff"))
            cr.fill()

        cr.set_source_rgb(*theme.rgb(C["accent"]))
        cr.set_line_width(3.2)
        cr.arc(160, 76, 18, 0, 2 * math.pi)
        cr.stroke()
        cr.save()
        cr.translate(160, 76)
        cr.scale(0.44, 1)
        cr.arc(0, 0, 18, 0, 2 * math.pi)
        cr.restore()
        cr.stroke()
        cr.move_to(142, 76)
        cr.line_to(178, 76)
        cr.stroke()

        theme.rounded_rect(cr, 68, 124, 184, 12, 6)
        cr.set_source_rgb(*theme.rgb("#9aa6bd"))
        cr.fill()
        theme.rounded_rect(cr, 142, 124, 36, 4, 2)
        cr.set_source_rgb(*theme.rgb("#7f8aa3"))
        cr.fill()
        return False


def card(child, classes="card", padding=18):
    frame = Gtk.EventBox()
    add_class(frame, classes)
    child.set_border_width(padding)
    frame.add(child)
    return frame


def field(icon_name, title, entry):
    """An entry in a white box with an icon and a small caption above it."""
    frame = Gtk.EventBox()
    add_class(frame, "field")
    row = Gtk.Box(spacing=14)
    row.set_border_width(10)
    row.set_margin_start(8)
    icon = Icon(icon_name, 20)
    add_class(icon, "field-icon")
    row.pack_start(icon, False, False, 0)
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    col.pack_start(label(title, "field-label", wrap=False), False, False, 0)
    entry.set_hexpand(True)
    col.pack_start(entry, False, False, 0)
    row.pack_start(col, True, True, 0)
    frame.add(row)
    ctx = frame.get_style_context()
    entry.connect("focus-in-event", lambda *_: ctx.add_class("focused") or False)
    entry.connect("focus-out-event", lambda *_: ctx.remove_class("focused") or False)
    frame.connect("button-press-event", lambda *_: entry.grab_focus() or False)
    return frame


def summary_row(name, value):
    row = Gtk.Box(spacing=16)
    row.pack_start(label(name, "muted", wrap=False), False, False, 0)
    value_label = label(value, "summary-value", xalign=1.0)
    value_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    row.pack_end(value_label, True, True, 0)
    return row


def arrow(text):
    return f"{text}  →"


# ------------------------------------------------------------------ window

class Installer(Gtk.Window):
    def __init__(self, welcome_mode=False):
        super().__init__(title="Install OnlyBrowserOS")
        add_class(self, "installer")
        self.set_default_size(960, 680)
        self.connect("delete-event", self.on_close)

        self.welcome_mode = welcome_mode
        self.memory = memory_mb()
        self.level = levels.recommended_level(self.memory)
        self.level_buttons = []
        self.disks = []
        self.disk = None
        self.disk_buttons = []
        self.running = False
        self.last_percent = 0
        self.phase = ""
        self.error_text = ""
        self.log = Gtk.TextBuffer()
        self.timezone_touched = False
        self.hostname_touched = False
        self.tip_index = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        top = Gtk.Box(spacing=12)
        top.set_border_width(18)
        top.set_margin_start(14)
        top.set_margin_end(14)
        self.back_button = Gtk.Button(label="←  Back")
        add_class(self.back_button, "flat back")
        self.back_button.connect("clicked", lambda _b: self.step(-1))
        top.pack_start(self.back_button, False, False, 0)
        top.pack_end(theme.brand(28), False, False, 0)
        self.top = top
        root.pack_start(top, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)
        root.pack_start(self.stack, True, True, 0)

        bottom = Gtk.Box(spacing=10)
        bottom.set_border_width(22)
        bottom.set_margin_start(14)
        bottom.set_margin_end(14)
        self.quit_button = Gtk.Button(label="Cancel")
        add_class(self.quit_button, "link")
        self.quit_button.connect("clicked", lambda _b: self.close())
        self.step_label = label("", "step-count", wrap=False, xalign=0.5)
        self.next_button = Gtk.Button(label=arrow("Next"))
        add_class(self.next_button, "primary next")
        self.next_button.connect("clicked", lambda _b: self.step(+1))
        bottom.pack_start(self.quit_button, False, False, 0)
        bottom.set_center_widget(self.step_label)
        bottom.pack_end(self.next_button, False, False, 0)
        self.bottom = bottom
        root.pack_start(bottom, False, False, 0)

        self.build_welcome()
        self.build_disk()
        self.build_account()
        self.build_computer()
        self.build_confirm()
        self.build_progress()
        self.build_done()
        self.build_failed()

        threading.Thread(target=self.find_timezone, daemon=True).start()

    # --- page scaffolding

    def page(self, name, width=560, glyph=None, title=None, lead=None):
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        column.set_halign(Gtk.Align.CENTER)
        column.set_size_request(width, -1)
        column.set_margin_top(12)
        column.set_margin_bottom(24)
        column.set_margin_start(24)
        column.set_margin_end(24)
        if glyph:
            column.pack_start(glyph, False, False, 4)
        if title:
            column.pack_start(label(title, "page-title", xalign=0.5), False, False, 0)
        if lead:
            column.pack_start(label(lead, "lead", xalign=0.5), False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(column)
        self.stack.add_named(scroller, name)
        return column

    def current(self):
        return self.stack.get_visible_child_name()

    def go(self, name):
        self.stack.set_visible_child_name(name)
        in_wizard = name in WIZARD
        self.top.set_visible(in_wizard)
        self.bottom.set_visible(in_wizard)
        if in_wizard:
            self.step_label.set_text(f"Step {WIZARD.index(name) + 1} of {len(WIZARD)}")
        ctx = self.next_button.get_style_context()
        ctx.remove_class("danger")
        ctx.add_class("primary")
        if name == "confirm":
            self.next_button.set_label("Erase disk and install")
            ctx.remove_class("primary")
            ctx.add_class("danger")
        else:
            self.next_button.set_label(arrow("Next"))

        getattr(self, f"enter_{name}", lambda: None)()
        self.update_next()

    def step(self, delta):
        name = self.current()
        if delta > 0 and name == "confirm":
            self.start_install()
            return
        if delta > 0 and name == "welcome" and self.welcome_mode:
            # From here on this is the installer, not a greeting to dismiss.
            self.welcome_mode = False
            self.set_keep_above(False)
        index = max(0, min(len(ORDER) - 1, ORDER.index(name) + delta))
        self.go(ORDER[index])

    def update_next(self, *_):
        name = self.current()
        ok = True
        if name == "disk":
            ok = self.disk is not None
        elif name == "account":
            ok = self.account_valid()
        elif name == "confirm":
            ok = self.confirm_check.get_active()
        self.next_button.set_sensitive(ok)

    # --- welcome

    def build_welcome(self):
        col = self.page("welcome", width=600)
        col.set_valign(Gtk.Align.CENTER)
        col.set_margin_top(20)
        col.pack_start(theme.brand(40, 20), False, False, 0)
        col.pack_start(label("Welcome!", "hero-title", xalign=0.5), False, False, 2)
        col.pack_start(label("A simple operating system made for the web.", "lead", xalign=0.5), False, False, 0)
        # The picture is a nicety; on a netbook screen the buttons matter more.
        display = Gdk.Display.get_default()
        monitor = display and (display.get_primary_monitor() or display.get_monitor(0))
        if monitor is None or monitor.get_geometry().height >= 740:
            col.pack_start(Illustration(), False, False, 0)

        features = Gtk.Box(spacing=12, homogeneous=True)
        for kind, colour, title, text in (("bolt", "accent", "Fast", "Starts quickly and\nworks smoothly."),
                                          ("shield", "good", "Safe", "Updates itself and\nkeeps you safe online."),
                                          ("smile", "violet", "Simple", "Just a browser.\nNothing else to learn.")):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(Glyph(kind, 46, colour), False, False, 2)
            box.pack_start(label(title, "feature-title", wrap=False, xalign=0.5), False, False, 0)
            box.pack_start(label(text, "feature-text", wrap=False, xalign=0.5), False, False, 0)
            features.pack_start(box, True, True, 0)
        col.pack_start(features, False, False, 6)

        self.issues = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.issues_card = card(self.issues, "notice", padding=16)
        self.issues_card.set_no_show_all(True)
        col.pack_start(self.issues_card, False, False, 4)

        start = Gtk.Button(label=arrow("Install OnlyBrowserOS" if self.welcome_mode else "Get started"))
        add_class(start, "primary pill")
        start.set_halign(Gtk.Align.CENTER)
        start.set_size_request(300, -1)
        start.connect("clicked", lambda _b: self.step(+1))
        col.pack_start(start, False, False, 10)
        self.start_button = start

        later = Gtk.Button(label="Try OnlyBrowserOS first" if self.welcome_mode else "Not now")
        add_class(later, "link")
        later.set_halign(Gtk.Align.CENTER)
        later.connect("clicked", lambda _b: self.close())
        col.pack_start(later, False, False, 0)
        if self.welcome_mode:
            col.pack_start(label("Trying it changes nothing on this computer.", "faint", xalign=0.5),
                           False, False, 0)

    def enter_welcome(self):
        """Mention only what needs doing; a computer that is ready shows no list."""
        for child in self.issues.get_children():
            child.destroy()
        problems = []
        if self.memory < 900:
            problems.append(f"This computer has {self.memory / 1024:.1f} GB of memory. "
                            "Websites will be slow with less than 1 GB.")
        if power_state() == "battery":
            problems.append("The computer is running on battery. Plug in the charger before installing.")
        if not [d for d in list_disks() if not d["reason"]]:
            problems.append("No disk of 8 GB or more was found to install on.")
        for text in problems:
            row = Gtk.Box(spacing=12)
            row.pack_start(Glyph("warn", 22, "warn", "solid"), False, False, 0)
            row.pack_start(label(text), True, True, 0)
            self.issues.pack_start(row, False, False, 0)
        self.issues.show_all()
        self.issues_card.set_visible(bool(problems))

    # --- disk

    def build_disk(self):
        col = self.page("disk", glyph=Glyph("disk", 88, "accent"), title="Choose a disk",
                        lead="Select where to install OnlyBrowserOS.\n"
                             "Everything on the disk you choose will be erased.")
        self.disk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        col.pack_start(self.disk_box, False, False, 8)
        self.disk_warning = label("", "warn")
        self.disk_warning.set_no_show_all(True)
        col.pack_start(self.disk_warning, False, False, 0)
        again = Gtk.Button(label="Look for disks again")
        add_class(again, "link")
        again.set_halign(Gtk.Align.CENTER)
        again.connect("clicked", lambda _b: self.enter_disk())
        col.pack_start(again, False, False, 0)

    def enter_disk(self):
        for child in self.disk_box.get_children():
            child.destroy()
        self.disks = list_disks()
        usable = [d for d in self.disks if not d["reason"]]
        if self.disk and self.disk["path"] not in {d["path"] for d in usable}:
            self.disk = None
        if self.disk is None and len(usable) == 1:
            self.disk = usable[0]

        self.disk_buttons = []
        for d in self.disks:
            b = Gtk.Button()
            add_class(b, "disk")
            row = Gtk.Box(spacing=16)
            dot = SelectDot()
            row.pack_start(dot, False, False, 0)
            row.pack_start(Glyph("disk", 40, "accent" if not d["reason"] else "faint"), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            text.pack_start(label(d["title"], "disk-title", wrap=False), False, False, 0)
            text.pack_start(label(d["model"], "muted", wrap=False), False, False, 0)
            text.pack_start(label(d["reason"] or d["detail"], "warn" if d["reason"] else "faint"), False, False, 0)
            row.pack_start(text, True, True, 0)
            chip = label(d["kind"], "chip", wrap=False)
            chip.set_valign(Gtk.Align.CENTER)
            row.pack_end(chip, False, False, 0)
            b.add(row)
            b.set_sensitive(not d["reason"])
            b.connect("clicked", lambda _b, disk=d: self.choose_disk(disk))
            self.disk_buttons.append((b, d, dot))
            self.disk_box.pack_start(b, False, False, 0)

        if not usable:
            if raid_controller():
                text = ("No disk was found. This computer keeps its disk in \u201cRAID\u201d or "
                        "\u201cIntel RST\u201d mode, which OnlyBrowserOS cannot use. Restart, open the "
                        "computer\u2019s setup screen (often F2, F10 or Del while it starts), set "
                        "SATA or storage mode to AHCI, save and start from the USB stick again. "
                        "Windows on this disk will not start afterwards; installing replaces it anyway.")
            else:
                text = ("No disk of 8 GB or more was found. If this computer has one, check that it is "
                        "connected, then choose Look for disks again.")
            self.disk_box.pack_start(label(text, "error", xalign=0.5, wrap=True), False, False, 0)
        self.disk_box.show_all()
        self.show_disk_choice()

    def choose_disk(self, disk):
        self.disk = disk
        self.show_disk_choice()
        self.update_next()

    def show_disk_choice(self):
        for b, d, dot in self.disk_buttons:
            chosen = self.disk is not None and d["path"] == self.disk["path"]
            dot.set_selected(chosen)
            ctx = b.get_style_context()
            if chosen:
                ctx.add_class("selected")
            else:
                ctx.remove_class("selected")
        if self.disk and self.disk["windows"]:
            self.disk_warning.set_text("This disk has Windows on it. Windows and all its files will be erased.")
        else:
            self.disk_warning.set_text("")
        self.disk_warning.set_visible(bool(self.disk_warning.get_text()))

    # --- account

    def build_account(self):
        col = self.page("account", glyph=Glyph("user", 88, "violet"), title="Create your account",
                        lead="You will use this password to make changes to this computer.")

        self.name_entry = Gtk.Entry(placeholder_text="For example: Asha Kumar")
        self.name_entry.connect("changed", self.on_account_changed)
        self.password_entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                        placeholder_text="At least 4 characters")
        self.password_entry.connect("changed", self.on_account_changed)
        self.confirm_entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                       placeholder_text="Type the same password again")
        self.confirm_entry.connect("changed", self.on_account_changed)
        self.password_hint = label("", "muted")
        show = Gtk.CheckButton(label="Show password")
        show.connect("toggled", lambda c: (self.password_entry.set_visibility(c.get_active()),
                                            self.confirm_entry.set_visibility(c.get_active())))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(field("user", "Your name", self.name_entry), False, False, 0)
        box.pack_start(field("lock", "Password", self.password_entry), False, False, 0)
        box.pack_start(field("lock", "Confirm password", self.confirm_entry), False, False, 0)
        hint_row = Gtk.Box(spacing=10)
        hint_row.pack_start(self.password_hint, True, True, 0)
        hint_row.pack_end(show, False, False, 0)
        box.pack_start(hint_row, False, False, 0)

        box.pack_start(label("Time zone", "field-label", wrap=False), False, False, 6)
        self.zones = timezones()
        self.region_combo = Gtk.ComboBoxText()
        self.city_combo = Gtk.ComboBoxText()
        for region in sorted(self.zones):
            self.region_combo.append(region, region.replace("_", " "))
        self.region_combo.append("UTC", "UTC (no time zone)")
        self.region_combo.connect("changed", self.on_region_changed)
        self.city_combo.connect("changed", lambda _c: self.update_next())
        zone_row = Gtk.Box(spacing=10)
        zone_row.pack_start(self.region_combo, False, False, 0)
        zone_row.pack_start(self.city_combo, True, True, 0)
        box.pack_start(zone_row, False, False, 0)
        self.zone_hint = label("", "faint")
        box.pack_start(self.zone_hint, False, False, 0)
        col.pack_start(box, False, False, 8)

        tz = current_timezone()
        self.set_timezone(tz)
        # Set only after the programmatic change above.
        self.region_combo.connect("changed", self.on_zone_touched)
        self.city_combo.connect("changed", self.on_zone_touched)

        col.pack_start(self.build_advanced(), False, False, 4)

    def build_advanced(self):
        expander = Gtk.Expander(label="Advanced options")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        box.pack_start(label("Keyboard layout", "field-label", wrap=False), False, False, 0)
        kb_row = Gtk.Box(spacing=10, homogeneous=True)
        self.keyboard_combo = Gtk.ComboBoxText()
        for code, name in KEYBOARDS:
            self.keyboard_combo.append(code, name)
        self.keyboard_combo.set_active_id("us")
        self.keyboard_combo.connect("changed", self.on_keyboard_changed)
        kb_row.pack_start(self.keyboard_combo, True, True, 0)
        kb_row.pack_start(Gtk.Entry(placeholder_text="Type here to test it"), True, True, 0)
        box.pack_start(kb_row, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 8)
        self.password_at_start = Gtk.CheckButton(label="Ask for my password when the computer starts")
        box.pack_start(self.password_at_start, False, False, 0)
        box.pack_start(label("Otherwise the computer opens straight to the browser.", "faint"), False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 8)
        box.pack_start(label("Computer name", "field-label", wrap=False), False, False, 0)
        self.hostname_entry = Gtk.Entry(placeholder_text="Shown to other devices on the network")
        self.hostname_entry.connect("changed", self.on_hostname_changed)
        box.pack_start(self.hostname_entry, False, False, 0)
        self.hostname_hint = label("", "error")
        box.pack_start(self.hostname_hint, False, False, 0)

        expander.add(card(box, "advanced", padding=18))
        return expander

    def on_region_changed(self, combo):
        self.city_combo.remove_all()
        region = combo.get_active_id()
        for city in self.zones.get(region, []):
            self.city_combo.append(city, city.replace("_", " ").replace("/", " / "))
        self.city_combo.set_visible(region != "UTC")
        if region != "UTC":
            self.city_combo.set_active(0)

    def set_timezone(self, tz):
        region, _, city = tz.partition("/")
        if region in self.zones and city in self.zones[region]:
            self.region_combo.set_active_id(region)
            self.city_combo.set_active_id(city)
            return True
        self.region_combo.set_active_id("UTC")
        return False

    def on_zone_touched(self, *_):
        if not getattr(self, "_setting_zone", False):
            self.timezone_touched = True

    def find_timezone(self):
        tz = detect_timezone()
        if tz:
            GLib.idle_add(self.apply_detected_timezone, tz)

    def apply_detected_timezone(self, tz):
        if self.timezone_touched:
            return False
        self._setting_zone = True
        if self.set_timezone(tz):
            self.zone_hint.set_text("Found from your internet connection. Change it if it is wrong.")
        self._setting_zone = False
        return False

    def on_keyboard_changed(self, combo):
        # Switch now, so the password typed next is typed on the chosen layout.
        layout = combo.get_active_id() or "us"
        subprocess.run(["setxkbmap", layout], capture_output=True)

    def timezone(self):
        region = self.region_combo.get_active_id()
        city = self.city_combo.get_active_id()
        return f"{region}/{city}" if region and region != "UTC" and city else "UTC"

    def on_account_changed(self, *_):
        name = self.name_entry.get_text().strip()
        if not self.hostname_touched:
            self._setting_hostname = True
            self.hostname_entry.set_text(f"{username_from(name)}-pc"[:63] if name else "")
            self._setting_hostname = False
        pw, again = self.password_entry.get_text(), self.confirm_entry.get_text()
        ctx = self.password_hint.get_style_context()
        ctx.remove_class("error")
        ctx.remove_class("good")
        if pw and len(pw) < 4:
            self.password_hint.set_text("Use at least 4 characters.")
            ctx.add_class("error")
        elif again and pw != again:
            self.password_hint.set_text("The two passwords are different.")
            ctx.add_class("error")
        elif pw and again and pw == again:
            self.password_hint.set_text("Passwords match." if len(pw) >= 8 else "Passwords match. 8 or more characters is safer.")
            ctx.add_class("good")
        else:
            self.password_hint.set_text("")
        self.update_next()

    def on_hostname_changed(self, entry):
        if not getattr(self, "_setting_hostname", False):
            self.hostname_touched = True
        name = entry.get_text().strip()
        ok = not name or valid_hostname(name)
        self.hostname_hint.set_text("" if ok else "Use lowercase letters, numbers and dashes only.")
        self.hostname_hint.set_visible(not ok)
        self.update_next()

    def hostname(self):
        name = self.hostname_entry.get_text().strip()
        if name and valid_hostname(name):
            return name
        return f"{username_from(self.name_entry.get_text().strip())}-pc"[:63]

    def account_valid(self):
        name = self.name_entry.get_text().strip()
        pw = self.password_entry.get_text()
        host = self.hostname_entry.get_text().strip()
        return (0 < len(name) <= 64 and not any(c in name for c in ":,=")
                and len(pw) >= 4 and pw == self.confirm_entry.get_text()
                and (not host or valid_hostname(host)))

    def enter_account(self):
        # show_all() on the window shows the city list even for UTC.
        self.city_combo.set_visible(self.region_combo.get_active_id() != "UTC")
        GLib.idle_add(lambda: self.name_entry.grab_focus() and False)

    # --- computer: how many tabs stay open, in words people know

    def build_computer(self):
        recommended = levels.recommended_level(self.memory)
        col = self.page("computer", glyph=Glyph("gauge-" + recommended, 88, "accent"),
                        title="How powerful is this computer?",
                        lead="This decides how many tabs can stay open at once, so websites never "
                             "run out of memory. You can change it later in the settings.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for key in levels.ORDER:
            name, text = levels.LEVELS[key]
            b = Gtk.Button()
            add_class(b, "disk")
            row = Gtk.Box(spacing=16)
            dot = SelectDot()
            row.pack_start(dot, False, False, 0)
            row.pack_start(Glyph("gauge-" + key, 40, "accent"), False, False, 0)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            words.pack_start(label(name, "disk-title", wrap=False), False, False, 0)
            tabs = levels.tabs_text(levels.tabs_for(key, self.memory))
            words.pack_start(label(f"{text} · {tabs} at once", "muted", wrap=False), False, False, 0)
            row.pack_start(words, True, True, 0)
            if key == recommended:
                chip = label("Recommended", "chip recommended", wrap=False)
                chip.set_valign(Gtk.Align.CENTER)
                row.pack_end(chip, False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _b, k=key: self.choose_level(k))
            self.level_buttons.append((b, key, dot))
            box.pack_start(b, False, False, 0)
        col.pack_start(box, False, False, 8)
        self.level_note = label("", "warn", xalign=0.5)
        self.level_note.set_no_show_all(True)
        col.pack_start(self.level_note, False, False, 0)
        col.pack_start(label(f"This computer has {self.memory / 1024:.1f} GB of memory.", "faint", xalign=0.5),
                       False, False, 0)
        self.show_level()

    def choose_level(self, key):
        self.level = key
        self.show_level()

    def show_level(self):
        for b, key, dot in self.level_buttons:
            dot.set_selected(key == self.level)
            ctx = b.get_style_context()
            if key == self.level:
                ctx.add_class("selected")
            else:
                ctx.remove_class("selected")
        recommended = levels.recommended_level(self.memory)
        if levels.ORDER.index(self.level) > levels.ORDER.index(recommended):
            self.level_note.set_text("With this much memory, websites may be slow at this level, "
                                     "and tabs may close by themselves when memory runs out.")
        else:
            self.level_note.set_text("")
        self.level_note.set_visible(bool(self.level_note.get_text()))

    # --- confirm

    def build_confirm(self):
        col = self.page("confirm", glyph=Glyph("good", 88, "accent"), title="Ready to install",
                        lead="Check that everything looks right.")
        self.summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        col.pack_start(card(self.summary, padding=20), False, False, 8)
        warning = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        head = Gtk.Box(spacing=12)
        head.pack_start(Glyph("warn", 26, "warn", "solid"), False, False, 0)
        self.erase_label = label("")
        head.pack_start(self.erase_label, True, True, 0)
        warning.pack_start(head, False, False, 0)
        self.confirm_check = Gtk.CheckButton(label="I understand that this disk will be erased")
        self.confirm_check.connect("toggled", self.update_next)
        warning.pack_start(self.confirm_check, False, False, 0)
        col.pack_start(card(warning, "notice", padding=18), False, False, 0)

    def enter_confirm(self):
        for child in self.summary.get_children():
            child.destroy()
        name = self.name_entry.get_text().strip()
        rows = [
            ("Disk", self.disk["title"] + f" · {self.disk['model']}" if self.disk else "—"),
            ("Name", name),
            ("Account", username_from(name)),
            ("Time zone", self.timezone().replace("_", " ")),
            ("Computer", f"{levels.LEVELS[self.level][0]} · "
                         f"{levels.tabs_text(levels.tabs_for(self.level, self.memory))}"),
        ]
        keyboard = self.keyboard_combo.get_active_id() or "us"
        if keyboard != "us":
            rows.append(("Keyboard", self.keyboard_combo.get_active_text()))
        if self.password_at_start.get_active():
            rows.append(("At start-up", "Asks for your password"))
        for title, value in rows:
            self.summary.pack_start(summary_row(title, value), False, False, 0)
        self.summary.show_all()
        if self.disk:
            extra = " including Windows" if self.disk["windows"] else ""
            self.erase_label.set_text(f"Everything on {self.disk['short']} will be erased{extra}: "
                                      "files, programs and any other operating system.")
        self.confirm_check.set_active(False)

    # --- progress, done, failed

    def build_progress(self):
        col = self.page("progress", width=520, glyph=Glyph("download", 96, "accent"),
                        title="Installing OnlyBrowserOS",
                        lead="This will take a few minutes. Please don't turn off your computer "
                             "or remove the USB stick.")
        col.set_valign(Gtk.Align.CENTER)
        self.progress = Gtk.ProgressBar()
        col.pack_start(self.progress, False, False, 18)
        self.status_label = label("Starting…", "status-line", xalign=0.5)
        col.pack_start(self.status_label, False, False, 0)

        tip = Gtk.Box(spacing=10)
        tip.set_halign(Gtk.Align.CENTER)
        tip.pack_start(Glyph("smile", 22, "accent", "plain"), False, False, 0)
        self.tip_label = label("", "lead")
        self.tip_label.set_max_width_chars(48)
        tip.pack_start(self.tip_label, False, False, 0)
        col.pack_start(tip, False, False, 22)
        col.pack_start(self.details_view("Show details"), False, False, 0)

    def rotate_tip(self):
        if self.current() != "progress":
            return False
        if self.last_percent >= 85:
            self.tip_label.set_text("Almost there!")
        else:
            self.tip_label.set_text(TIPS[self.tip_index % len(TIPS)])
            self.tip_index += 1
        return True

    def details_view(self, title):
        expander = Gtk.Expander(label=title)
        view = Gtk.TextView(buffer=self.log, editable=False, cursor_visible=False,
                            wrap_mode=Gtk.WrapMode.CHAR, monospace=True)
        view.set_left_margin(10)
        view.set_top_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(200)
        scroller.add(view)
        expander.add(scroller)
        return expander

    def build_done(self):
        col = self.page("done", width=520, glyph=Glyph("good", 96, "good", "solid"),
                        title="Installation complete!",
                        lead="Your computer is ready to go.\nRestart to start using OnlyBrowserOS.")
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(label("When the screen goes dark, take out the USB stick.", "muted", xalign=0.5),
                       False, False, 0)
        restart = Gtk.Button(label="Restart now")
        add_class(restart, "success pill")
        restart.set_halign(Gtk.Align.CENTER)
        restart.set_size_request(260, -1)
        restart.connect("clicked", lambda _b: subprocess.Popen(["systemctl", "reboot"]))
        col.pack_start(restart, False, False, 14)
        later = Gtk.Button(label="Restart later")
        add_class(later, "link")
        later.set_halign(Gtk.Align.CENTER)
        later.connect("clicked", lambda _b: self.destroy())
        col.pack_start(later, False, False, 0)
        footer = theme.brand(26)
        footer.set_halign(Gtk.Align.CENTER)
        col.pack_start(footer, False, False, 36)

    def build_failed(self):
        col = self.page("failed", width=580, glyph=Glyph("bad", 88, "bad", "solid"),
                        title="The installation stopped")
        col.set_valign(Gtk.Align.CENTER)
        self.failed_reason = label("", "error", selectable=True, xalign=0.5)
        self.failed_note = label("", "lead", xalign=0.5)
        col.pack_start(self.failed_reason, False, False, 0)
        col.pack_start(self.failed_note, False, False, 0)
        buttons = Gtk.Box(spacing=10)
        buttons.set_halign(Gtk.Align.CENTER)
        again = Gtk.Button(label="Try again")
        add_class(again, "primary pill")
        again.connect("clicked", lambda _b: self.go("disk"))
        close = Gtk.Button(label="Close")
        add_class(close, "pill")
        close.connect("clicked", lambda _b: self.destroy())
        buttons.pack_start(close, False, False, 0)
        buttons.pack_start(again, False, False, 0)
        col.pack_start(buttons, False, False, 14)
        col.pack_start(self.details_view("What happened"), False, False, 0)

    # --- running the helper

    def start_install(self):
        if self.running or not self.disk:
            return
        name = self.name_entry.get_text().strip()
        username = username_from(name)
        options = {
            "disk": self.disk["path"],
            "fullname": name,
            "username": username,
            "hostname": self.hostname(),
            "password": self.password_entry.get_text(),
            "timezone": self.timezone(),
            "keyboard": self.keyboard_combo.get_active_id() or "us",
            "autologin": not self.password_at_start.get_active(),
            "tab_limit": levels.setting_for(self.level, self.memory),
        }
        self.running = True
        self.error_text = ""
        self.last_percent = 0
        self.phase = "Starting"
        self.log.set_text("")
        self.progress.set_fraction(0)
        self.show_status()
        self.go("progress")
        self.rotate_tip()
        GLib.timeout_add_seconds(9, self.rotate_tip)
        threading.Thread(target=self.run_helper, args=(options,), daemon=True).start()

    def run_helper(self, options):
        helper = ["sudo", "-n", HELPER, "install"]
        # Keep the laptop awake with the lid closed while the disk is written.
        inhibit = ["systemd-inhibit", "--what=sleep:idle:handle-lid-switch",
                   "--who=OnlyBrowserOS installer", "--why=Installing to disk", "--mode=block"]
        code = self.run_command(inhibit + helper, options)
        if code is not None and code != 0 and "Failed to inhibit" in self.log_text():
            code = self.run_command(helper, options)
        GLib.idle_add(self.finished, code if code is not None else 1)

    def run_command(self, command, options):
        try:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as exc:
            GLib.idle_add(self.on_line, f"error: {exc}\n")
            return 1
        try:
            proc.stdin.write(json.dumps(options))
            proc.stdin.close()
        except OSError:
            pass
        for line in proc.stdout:
            GLib.idle_add(self.on_line, line)
        return proc.wait()

    def log_text(self):
        return self.log.get_text(self.log.get_start_iter(), self.log.get_end_iter(), False)

    def show_status(self):
        self.status_label.set_text(f"{self.phase}… {self.last_percent}%")

    def on_line(self, line):
        if line.startswith("##"):
            try:
                data = json.loads(line[2:])
            except ValueError:
                return False
            if "phase" in data:
                self.phase = data["phase"]
            if "percent" in data:
                self.last_percent = int(data["percent"])
                self.progress.set_fraction(self.last_percent / 100)
            self.show_status()
            return False
        if line.startswith("error:"):
            self.error_text = line[len("error:"):].strip()
        self.log.insert(self.log.get_end_iter(), line)
        return False

    def finished(self, code):
        self.running = False
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            (STATE / "install-log.txt").write_text(self.log_text())
        except OSError:
            pass
        if code == 0:
            self.go("done")
            return False
        log = self.log_text()
        if "a password is required" in log:
            self.error_text = "The installer is not allowed to change disks on this system."
        elif not self.error_text:
            # The helper never started (sudo said why), so there is no error: line.
            lines = [line.strip() for line in log.splitlines() if line.strip()]
            self.error_text = lines[-1] if lines else ""
        self.failed_reason.set_text(self.error_text or "The installer stopped without saying why.")
        if self.last_percent < 6:
            self.failed_note.set_text("Nothing on the disk was changed.")
        else:
            self.failed_note.set_text("The disk was partly written, so it will not start on its own. "
                                      "Choose Try again, or pick a different disk.")
        self.go("failed")
        return False

    def on_close(self, *_):
        if self.running:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                       buttons=Gtk.ButtonsType.OK,
                                       text="OnlyBrowserOS is being installed")
            dialog.format_secondary_text("Stopping now would leave the disk unusable. Wait until it finishes.")
            dialog.run()
            dialog.destroy()
            return True
        return False


def main():
    set_process_name("obos-installer")
    theme.apply(CSS)
    welcome = "--welcome" in sys.argv[1:]
    window = Installer(welcome_mode=welcome)
    if welcome:
        # Opened at start-up: stay in front of the browser while it starts.
        window.set_keep_above(True)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    window.go("welcome")
    Gtk.main()


if __name__ == "__main__":
    main()
