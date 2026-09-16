#!/usr/bin/env python3
"""
WebOS system bridge.

Serves the WebOS shell and exposes the host to it over a small JSON API.

Security model
--------------
The API can start a shell, read and write files, and reformat a disk, so the
threat is not a remote attacker but the arbitrary web pages the OS is designed
to load in its own tabs. Those pages run in the same browser and can address
loopback. Three things keep them out:

  * the socket binds to 127.0.0.1 only, so nothing off the machine can reach it;
  * every /api call must carry X-WebOS-Token, and a cross-origin request cannot
    set a custom header without a CORS preflight, which this server never
    answers -- so a hostile page cannot forge a call even from inside the
    browser;
  * no Access-Control-Allow-* header is ever sent, so a hostile page cannot
    read a response either.

The token is minted at startup and injected into each HTML document the bridge
serves. Only same-origin documents can read it.

The bridge runs as the unprivileged desktop user. File and process access are
therefore bounded by ordinary Unix permissions, not by checks in this file.
Genuinely privileged work (installing to disk) is handed to a helper over sudo.
"""

import codecs
import errno
import fcntl
import json
import os
import pty
import pwd
import re
import secrets
import select
import shutil
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 9999
ORIGIN = f"http://{HOST}:{PORT}"

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "ui"
APPS_DIR = BASE_DIR / "apps"

HELPER = "/usr/lib/webos/webos-helper"
RELEASE_FILE = Path("/etc/webos-release")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "webos"
CONFIG_FILE = CONFIG_DIR / "settings.json"

TOKEN = secrets.token_urlsafe(32)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

log_lock = threading.Lock()


def log(*parts):
    with log_lock:
        print("[webos-bridge]", *parts, flush=True)


# --------------------------------------------------------------------------
# command helpers
# --------------------------------------------------------------------------

def run(args, timeout=15, input_text=None):
    """Run a command, never raise. Returns (code, stdout, stderr)."""
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{args[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except Exception as exc:  # noqa: BLE001 - a bridge call must not kill the server
        return 1, "", str(exc)


def have(cmd):
    return shutil.which(cmd) is not None


def run_privileged(args, timeout=20):
    """Try unprivileged first; fall back to sudo, which is configured NOPASSWD
    for exactly this short list of commands."""
    code, out, err = run(args, timeout=timeout)
    if code == 0:
        return code, out, err
    if have("sudo"):
        return run(["sudo", "-n"] + args, timeout=timeout)
    return code, out, err


# --------------------------------------------------------------------------
# system facts
# --------------------------------------------------------------------------

def read_release():
    info = {"version": "unknown", "base": "unknown", "name": "WebOS"}
    try:
        for line in RELEASE_FILE.read_text().splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            info[k.strip().lower()] = v.strip().strip('"')
    except OSError:
        pass
    return info


RELEASE = read_release()


def is_live():
    if Path("/run/live/medium").is_dir():
        return True
    try:
        return "boot=live" in Path("/proc/cmdline").read_text()
    except OSError:
        return False


def cpu_model():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "Unknown CPU"


CPU_MODEL = cpu_model()
CPU_CORES = os.cpu_count() or 1


def uptime_text():
    try:
        secs = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return "unknown"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def mem_info():
    vals = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, rest = line.partition(":")
            vals[k] = int(rest.strip().split()[0])  # kB
    except (OSError, ValueError, IndexError):
        return {"total_mb": 0, "used_mb": 0, "percent": 0,
                "swap_total_mb": 0, "swap_used_mb": 0}

    total = vals.get("MemTotal", 0)
    avail = vals.get("MemAvailable", vals.get("MemFree", 0))
    used = max(0, total - avail)
    swap_total = vals.get("SwapTotal", 0)
    swap_used = max(0, swap_total - vals.get("SwapFree", 0))
    return {
        "total_mb": total // 1024,
        "used_mb": used // 1024,
        "percent": round(used / total * 100, 1) if total else 0,
        "swap_total_mb": swap_total // 1024,
        "swap_used_mb": swap_used // 1024,
    }


def disk_info():
    try:
        u = shutil.disk_usage("/")
        return {
            "total_gb": round(u.total / 1024 ** 3, 1),
            "used_gb": round(u.used / 1024 ** 3, 1),
            "free_gb": round(u.free / 1024 ** 3, 1),
            "percent": round(u.used / u.total * 100, 1) if u.total else 0,
        }
    except OSError:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}


def battery_info():
    root = Path("/sys/class/power_supply")
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            try:
                if (entry / "type").read_text().strip() != "Battery":
                    continue
                cap = int((entry / "capacity").read_text().strip())
                status = (entry / "status").read_text().strip()
                return {"present": True, "percent": cap, "status": status}
            except (OSError, ValueError):
                continue
    return {"present": False, "percent": 100, "status": "AC power"}


def load_avg():
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return [0, 0, 0]


def primary_ip():
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("192.0.2.1", 80))  # TEST-NET-1: routed nowhere, never sends
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        if s:
            s.close()


# --------------------------------------------------------------------------
# background sampler: keeps /api/status cheap
# --------------------------------------------------------------------------

class Sampler(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="sampler")
        self.lock = threading.Lock()
        self.cpu_percent = 0.0
        self.network = {"connected": False, "ssid": None, "ip": None}
        self.volume = {"level": 0, "muted": False, "available": False}
        self._prev = None
        self._slow_at = 0.0

    def run(self):
        while True:
            try:
                self._sample_cpu()
                now = time.time()
                if now - self._slow_at > 5:
                    self._slow_at = now
                    net = probe_network()
                    vol = get_volume()
                    with self.lock:
                        self.network = net
                        self.volume = vol
            except Exception as exc:  # noqa: BLE001
                log("sampler error:", exc)
            time.sleep(1.0)

    def _sample_cpu(self):
        try:
            fields = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
            vals = [int(x) for x in fields]
        except (OSError, ValueError):
            return
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        if self._prev:
            dt = total - self._prev[0]
            di = idle - self._prev[1]
            if dt > 0:
                with self.lock:
                    self.cpu_percent = round(max(0.0, min(100.0, (1 - di / dt) * 100)), 1)
        self._prev = (total, idle)

    def snapshot(self):
        with self.lock:
            return self.cpu_percent, dict(self.network), dict(self.volume)


def probe_network():
    ip = primary_ip()
    ssid = None
    if have("nmcli"):
        code, out, _ = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"], timeout=5)
        if code == 0:
            for line in out.splitlines():
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1] or None
                    break
    return {"connected": ip is not None, "ssid": ssid, "ip": ip}


# --------------------------------------------------------------------------
# audio / backlight
# --------------------------------------------------------------------------

def get_volume():
    if have("wpctl"):
        code, out, _ = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=5)
        if code == 0:
            m = re.search(r"([\d.]+)", out)
            if m:
                return {
                    "level": int(round(float(m.group(1)) * 100)),
                    "muted": "MUTED" in out.upper(),
                    "available": True,
                }
    if have("pactl"):
        code, out, _ = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=5)
        if code == 0:
            m = re.search(r"(\d+)%", out)
            if m:
                mcode, mout, _ = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=5)
                return {
                    "level": int(m.group(1)),
                    "muted": "yes" in mout.lower(),
                    "available": True,
                }
    if have("amixer"):
        code, out, _ = run(["amixer", "sget", "Master"], timeout=5)
        if code == 0:
            m = re.search(r"\[(\d+)%\]", out)
            if m:
                return {
                    "level": int(m.group(1)),
                    "muted": "[off]" in out,
                    "available": True,
                }
    return {"level": 0, "muted": False, "available": False}


def set_volume(level):
    level = max(0, min(100, int(level)))
    if have("wpctl"):
        code, _, err = run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"])
        if code == 0:
            return {"success": True, "level": level}
    if have("pactl"):
        code, _, err = run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
        if code == 0:
            return {"success": True, "level": level}
    if have("amixer"):
        code, _, err = run(["amixer", "-q", "sset", "Master", f"{level}%"])
        if code == 0:
            return {"success": True, "level": level}
    return {"success": False, "level": level, "error": "no mixer available"}


def set_mute(muted):
    flag = "1" if muted else "0"
    if have("wpctl"):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", flag])
    elif have("pactl"):
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", flag])
    elif have("amixer"):
        run(["amixer", "-q", "sset", "Master", "mute" if muted else "unmute"])
    return {"success": True, "muted": bool(muted)}


def backlight_dir():
    root = Path("/sys/class/backlight")
    if not root.is_dir():
        return None
    entries = sorted(root.iterdir())
    return entries[0] if entries else None


def get_brightness():
    bl = backlight_dir()
    if bl:
        try:
            cur = int((bl / "brightness").read_text().strip())
            mx = int((bl / "max_brightness").read_text().strip())
            if mx > 0:
                return {"available": True, "level": max(1, int(cur / mx * 100))}
        except (OSError, ValueError):
            pass
    if have("brightnessctl"):
        code, out, _ = run(["brightnessctl", "-m", "g"])
        if code == 0:
            m = re.search(r"(\d+)%", out)
            if m:
                return {"available": True, "level": int(m.group(1))}
    return {"available": False, "level": 100}


def set_brightness(level):
    level = max(1, min(100, int(level)))
    if have("brightnessctl"):
        code, _, err = run_privileged(["brightnessctl", "-q", "s", f"{level}%"])
        if code == 0:
            return {"success": True, "level": level}
    bl = backlight_dir()
    if bl:
        try:
            mx = int((bl / "max_brightness").read_text().strip())
            (bl / "brightness").write_text(str(max(1, int(mx * level / 100))))
            return {"success": True, "level": level}
        except (OSError, ValueError) as exc:
            return {"success": False, "level": level, "error": str(exc)}
    return {"success": False, "level": level, "error": "no backlight device"}


# --------------------------------------------------------------------------
# wifi
# --------------------------------------------------------------------------

def wifi_list(rescan=False):
    if not have("nmcli"):
        return {"available": False, "networks": [], "device": "NetworkManager not installed"}

    code, out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"], timeout=8)
    wifi_dev = None
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "wifi":
            wifi_dev = parts[0]
            break
    if not wifi_dev:
        return {"available": False, "networks": [], "device": "No Wi-Fi adapter detected"}

    if rescan:
        run(["nmcli", "dev", "wifi", "rescan"], timeout=25)
        time.sleep(1.5)

    saved = set()
    code, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"], timeout=8)
    if code == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and "wireless" in parts[1]:
                saved.add(parts[0])

    # -t escapes embedded colons as "\:", so split on unescaped colons only.
    code, out, err = run(
        ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
        timeout=20,
    )
    if code != 0:
        return {"available": True, "networks": [], "device": wifi_dev,
                "error": err.strip() or "scan failed"}

    seen = {}
    for line in out.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 4:
            continue
        in_use, ssid, signal_s, security = (p.replace("\\:", ":") for p in parts[:4])
        ssid = ssid.strip()
        if not ssid:
            continue
        try:
            strength = int(signal_s)
        except ValueError:
            strength = 0
        entry = {
            "ssid": ssid,
            "signal": strength,
            "security": security.strip() or "Open",
            "active": in_use.strip() == "*",
            "saved": ssid in saved,
        }
        # The same SSID appears once per band and per AP; keep the strongest.
        if ssid not in seen or strength > seen[ssid]["signal"] or entry["active"]:
            seen[ssid] = entry

    networks = sorted(seen.values(), key=lambda n: (not n["active"], -n["signal"]))
    return {"available": True, "networks": networks, "device": wifi_dev}


def wifi_connect(ssid, password):
    if not have("nmcli"):
        return {"success": False, "message": "NetworkManager is not installed"}

    if password:
        args = ["nmcli", "dev", "wifi", "connect", ssid, "password", password]
    else:
        args = ["nmcli", "dev", "wifi", "connect", ssid]

    code, out, err = run_privileged(args, timeout=50)
    if code == 0:
        return {"success": True, "message": f"Connected to {ssid}"}

    detail = (err or out).strip().splitlines()
    message = detail[-1] if detail else "Connection failed"
    message = re.sub(r"^Error:\s*", "", message)
    return {"success": False, "message": message}


def wifi_disconnect():
    code, out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"], timeout=8)
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            run_privileged(["nmcli", "dev", "disconnect", parts[0]], timeout=20)
            return {"success": True}
    return {"success": False, "message": "No Wi-Fi device"}


# --------------------------------------------------------------------------
# processes
# --------------------------------------------------------------------------

_proc_prev = {}
_proc_prev_at = 0.0
_proc_lock = threading.Lock()
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def list_processes():
    global _proc_prev, _proc_prev_at

    now = time.time()
    current = {}
    rows = []

    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            with open(f"/proc/{pid}/stat", "r") as fh:
                raw = fh.read()
            # comm can contain spaces and parentheses; it is the only field
            # between the first "(" and the last ")".
            lp, rp = raw.index("("), raw.rindex(")")
            name = raw[lp + 1:rp]
            fields = raw[rp + 2:].split()
            utime, stime = int(fields[11]), int(fields[12])
            rss_pages = int(fields[21])

            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()

            uid = os.stat(f"/proc/{pid}").st_uid
        except (OSError, ValueError, IndexError):
            continue  # process exited while we were reading it

        ticks = utime + stime
        current[pid] = ticks

        cpu = 0.0
        with _proc_lock:
            prev_ticks = _proc_prev.get(pid)
            elapsed = now - _proc_prev_at if _proc_prev_at else 0
        if prev_ticks is not None and elapsed > 0:
            cpu = max(0.0, (ticks - prev_ticks) / CLK_TCK / elapsed * 100)

        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)

        rows.append({
            "pid": pid,
            "name": name,
            "user": user,
            "cpu": round(cpu, 1),
            "rss": rss_pages * PAGE_SIZE,
            "cmd": cmd or f"[{name}]",
        })

    with _proc_lock:
        _proc_prev = current
        _proc_prev_at = now

    return {"processes": rows}


def kill_process(pid, sig_name):
    sig = {"TERM": signal.SIGTERM, "KILL": signal.SIGKILL,
           "HUP": signal.SIGHUP, "INT": signal.SIGINT}.get(str(sig_name).upper())
    if sig is None:
        raise ApiError("Unsupported signal", 400)
    try:
        os.kill(int(pid), sig)
    except ProcessLookupError:
        raise ApiError("No such process", 404)
    except PermissionError:
        raise ApiError("That process belongs to another user", 403)
    except (ValueError, OverflowError):
        raise ApiError("Invalid PID", 400)
    return {"success": True}


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------

MAX_TEXT_BYTES = 4 * 1024 * 1024


def resolve_path(raw, must_exist=False):
    if raw is None or raw == "":
        raw = "~"
    p = Path(os.path.expanduser(str(raw)))
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        raise ApiError("Invalid path", 400)
    if must_exist and not p.exists():
        raise ApiError("No such file or directory", 404)
    return p


def mode_string(st):
    bits = ""
    perms = st.st_mode & 0o777
    for who in (6, 3, 0):
        bits += "r" if perms & (0o4 << who) else "-"
        bits += "w" if perms & (0o2 << who) else "-"
        bits += "x" if perms & (0o1 << who) else "-"
    return bits


def list_files(raw):
    p = resolve_path(raw)
    if not p.is_dir():
        p = p.parent if p.parent.is_dir() else Path.home()

    items = []
    error = None
    try:
        entries = list(os.scandir(p))
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)

    for entry in entries:
        try:
            st = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=True)
            items.append({
                "name": entry.name,
                "path": str(p / entry.name),
                "is_dir": is_dir,
                "is_link": entry.is_symlink(),
                "size": 0 if is_dir else st.st_size,
                "mtime": int(st.st_mtime),
                "mode": ("d" if is_dir else "-") + mode_string(st),
                "executable": bool(st.st_mode & 0o111) and not is_dir,
            })
        except OSError:
            continue

    items.sort(key=lambda i: (not i["is_dir"], i["name"].lower()))

    try:
        free = shutil.disk_usage(p).free
    except OSError:
        free = None

    return {
        "current": str(p),
        "parent": str(p.parent),
        "items": items,
        "free": free,
        "error": error,
    }


def read_file(raw):
    p = resolve_path(raw, must_exist=True)
    if p.is_dir():
        raise ApiError("That is a directory", 400)
    size = p.stat().st_size
    if size > MAX_TEXT_BYTES:
        return {"path": str(p), "binary": True, "size": size,
                "content": "", "readonly": True}
    try:
        data = p.read_bytes()
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)

    if b"\x00" in data[:8192]:
        return {"path": str(p), "binary": True, "size": size,
                "content": "", "readonly": True}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": str(p), "binary": True, "size": size,
                "content": "", "readonly": True}

    return {
        "path": str(p),
        "binary": False,
        "size": size,
        "content": text,
        "readonly": not os.access(p, os.W_OK),
    }


def write_file(raw, content):
    p = resolve_path(raw)
    if p.is_dir():
        raise ApiError("That is a directory", 400)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temporary file in the same directory so a failure part way
        # through does not truncate the original.
        tmp = p.with_name(p.name + ".webos-tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, p)
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)
    return {"success": True, "path": str(p)}


def make_dir(raw):
    p = resolve_path(raw)
    try:
        p.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ApiError("Already exists", 409)
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)
    return {"success": True, "path": str(p)}


PROTECTED = {Path("/"), Path("/etc"), Path("/usr"), Path("/bin"), Path("/sbin"),
             Path("/boot"), Path("/var"), Path("/proc"), Path("/sys"), Path("/dev"),
             Path.home()}


def delete_path(raw):
    p = resolve_path(raw, must_exist=True)
    if p in PROTECTED:
        raise ApiError(f"Refusing to delete {p}", 403)
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)
    return {"success": True}


def rename_path(raw, new_name):
    p = resolve_path(raw, must_exist=True)
    if not new_name or "/" in new_name or new_name in (".", ".."):
        raise ApiError("Invalid name", 400)
    target = p.parent / new_name
    if target.exists():
        raise ApiError("A file with that name already exists", 409)
    try:
        p.rename(target)
    except PermissionError:
        raise ApiError(f"Permission denied: {p}", 403)
    except OSError as exc:
        raise ApiError(str(exc), 400)
    return {"success": True, "path": str(target)}


# --------------------------------------------------------------------------
# terminal sessions
# --------------------------------------------------------------------------

class PtySession:
    """A login shell on a pty, drained by a reader thread into a buffer that
    the HTTP long-poll hands to the browser."""

    IDLE_TIMEOUT = 15 * 60

    def __init__(self, cols, rows):
        self.id = secrets.token_urlsafe(12)
        self.cols = max(20, min(500, int(cols)))
        self.rows = max(5, min(200, int(rows)))
        self.buffer = deque()
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.exited = False
        self.exit_code = None
        self.touched = time.time()

        shell = pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
        if not os.path.exists(shell):
            shell = "/bin/sh"

        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            # Child. Only async-signal-safe-ish work here, then exec.
            try:
                os.environ["TERM"] = "xterm-256color"
                os.environ["COLORTERM"] = "truecolor"
                os.environ["LINES"] = str(self.rows)
                os.environ["COLUMNS"] = str(self.cols)
                os.chdir(os.path.expanduser("~"))
                os.execvp(shell, [os.path.basename(shell), "-l"])
            except Exception:
                os._exit(127)

        self.set_size(self.cols, self.rows)
        # Output arrives in arbitrary chunks, so a multi-byte character can be
        # split across two reads; an incremental decoder stitches them back.
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.reader = threading.Thread(target=self._read_loop, daemon=True,
                                       name=f"pty-{self.id}")
        self.reader.start()

    def set_size(self, cols, rows):
        self.cols = max(20, min(500, int(cols)))
        self.rows = max(5, min(200, int(rows)))
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", self.rows, self.cols, 0, 0))
        except OSError:
            pass

    def _read_loop(self):
        while True:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                break  # EIO: the child closed the pty
            if not chunk:
                break
            text = self.decoder.decode(chunk)
            if text:
                with self.lock:
                    self.buffer.append(text)
                self.event.set()

        self.exited = True
        try:
            _, status = os.waitpid(self.pid, 0)
            self.exit_code = os.waitstatus_to_exitcode(status)
        except (ChildProcessError, OSError, ValueError):
            self.exit_code = None
        self.event.set()

    def read(self, timeout=10.0):
        """Long poll: return as soon as there is output, or after `timeout`."""
        self.touched = time.time()
        deadline = time.time() + timeout
        while True:
            with self.lock:
                if self.buffer:
                    data = "".join(self.buffer)
                    self.buffer.clear()
                    self.event.clear()
                    return {"data": data, "exited": False}
            if self.exited:
                return {"data": "", "exited": True, "code": self.exit_code}
            remaining = deadline - time.time()
            if remaining <= 0:
                return {"data": "", "exited": False}
            self.event.wait(min(remaining, 1.0))
            self.event.clear()

    def write(self, data):
        self.touched = time.time()
        if self.exited:
            return
        try:
            os.write(self.fd, data.encode("utf-8"))
        except OSError:
            self.exited = True
            self.event.set()

    def close(self):
        if not self.exited:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGHUP)
            except OSError:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.exited = True
        self.event.set()


class SessionRegistry:
    MAX_SESSIONS = 8

    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reaper, daemon=True, name="pty-reaper").start()

    def open(self, cols, rows):
        with self.lock:
            if len(self.sessions) >= self.MAX_SESSIONS:
                raise ApiError("Too many terminal sessions are open", 429)
            s = PtySession(cols, rows)
            self.sessions[s.id] = s
            return s

    def get(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
        if s is None:
            raise ApiError("No such terminal session", 404)
        return s

    def close(self, sid):
        with self.lock:
            s = self.sessions.pop(sid, None)
        if s:
            s.close()
        return {"success": True}

    def _reaper(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self.lock:
                dead = [sid for sid, s in self.sessions.items()
                        if s.exited or now - s.touched > PtySession.IDLE_TIMEOUT]
                for sid in dead:
                    s = self.sessions.pop(sid)
                    s.close()


SESSIONS = SessionRegistry()


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

_config_lock = threading.Lock()


def read_config():
    with _config_lock:
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            return {}


def write_config(patch):
    with _config_lock:
        try:
            current = json.loads(CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            current = {}

        if patch.get("__reset"):
            current = {}
        else:
            current.update({k: v for k, v in patch.items() if not k.startswith("__")})

        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, indent=2))
            os.replace(tmp, CONFIG_FILE)
        except OSError as exc:
            raise ApiError(f"Could not save settings: {exc}", 500)
        return current


# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------

def power(action):
    verb = {"poweroff": "poweroff", "reboot": "reboot"}[action]
    code, _, err = run(["systemctl", verb], timeout=10)
    if code == 0:
        return {"success": True}
    code, _, err = run(["sudo", "-n", "systemctl", verb], timeout=10)
    if code == 0:
        return {"success": True}
    raise ApiError(f"Could not {verb}: {err.strip() or 'permission denied'}", 500)


# --------------------------------------------------------------------------
# installer
# --------------------------------------------------------------------------

class Installer:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"      # idle | running | done | error
        self.phase = ""
        self.percent = 0
        self.log = []
        self.error = None
        self.disk = None
        self.proc = None

    def status(self):
        with self.lock:
            return {
                "state": self.state,
                "phase": self.phase,
                "percent": self.percent,
                "log": list(self.log),
                "error": self.error,
                "disk": self.disk,
            }

    def start(self, opts):
        with self.lock:
            if self.state == "running":
                raise ApiError("An installation is already running", 409)
            self.state = "running"
            self.phase = "Starting"
            self.percent = 0
            self.log = []
            self.error = None
            self.disk = opts.get("disk")

        threading.Thread(target=self._run, args=(opts,), daemon=True,
                         name="installer").start()
        return {"started": True}

    def _append(self, line):
        with self.lock:
            self.log.append(line)
            if len(self.log) > 2000:
                del self.log[:500]

    def _run(self, opts):
        if not os.path.exists(HELPER):
            with self.lock:
                self.state = "error"
                self.error = f"Installer helper is missing ({HELPER})"
            self._append("error: " + self.error)
            return

        payload = json.dumps(opts)
        cmd = ["sudo", "-n", HELPER, "install"]
        self._append("$ sudo webos-helper install")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            with self.lock:
                self.state = "error"
                self.error = str(exc)
            self._append("error: " + str(exc))
            return

        self.proc = proc
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            if line.startswith("##"):
                # Structured progress: ##{"phase": "...", "percent": 40}
                try:
                    upd = json.loads(line[2:])
                except json.JSONDecodeError:
                    self._append(line)
                    continue
                with self.lock:
                    if "phase" in upd:
                        self.phase = upd["phase"]
                    if "percent" in upd:
                        self.percent = int(upd["percent"])
                if upd.get("phase"):
                    self._append("→ " + upd["phase"])
                continue
            self._append(line)

        code = proc.wait()
        with self.lock:
            if code == 0:
                self.state = "done"
                self.phase = "Complete"
                self.percent = 100
            else:
                self.state = "error"
                self.error = f"Installer exited with status {code}"
        self._append("done" if code == 0 else f"error: exit status {code}")


INSTALLER = Installer()


def list_disks():
    if not have("lsblk"):
        raise ApiError("lsblk is not available", 500)

    code, out, err = run(
        ["lsblk", "-J", "-b", "-o",
         "NAME,PATH,SIZE,TYPE,RM,ROTA,MODEL,MOUNTPOINT,FSTYPE,LABEL"],
        timeout=15,
    )
    if code != 0:
        raise ApiError(f"Could not list disks: {err.strip()}", 500)

    try:
        tree = json.loads(out)
    except json.JSONDecodeError:
        raise ApiError("Could not parse lsblk output", 500)

    # Any disk carrying a filesystem that is currently mounted by the running
    # system -- including the live medium -- must not be reformatted.
    busy_mounts = {"/", "/run/live/medium", "/cdrom", "/lib/live/mount/medium",
                   "/run/live/rootfs", "/boot", "/boot/efi"}

    disks = []
    for dev in tree.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        name = dev.get("name", "")
        if name.startswith(("loop", "ram", "sr", "zram")):
            continue

        children = dev.get("children") or []
        mounts = []

        def collect(node):
            mp = node.get("mountpoint")
            if mp:
                mounts.append(mp)
            for kid in node.get("children") or []:
                collect(kid)

        collect(dev)

        blocked = None
        for mp in mounts:
            if mp in busy_mounts or mp.startswith("/run/live"):
                blocked = "In use by the running system"
                break

        size = int(dev.get("size") or 0)
        if size < 8 * 1024 ** 3:
            blocked = blocked or "Too small (8 GB minimum)"

        contents = ", ".join(
            sorted({c.get("fstype") or "" for c in children if c.get("fstype")})
        )

        disks.append({
            "path": dev.get("path") or f"/dev/{name}",
            "model": (dev.get("model") or "").strip(),
            "size": size,
            "size_h": human_size(size),
            "removable": str(dev.get("rm")).lower() in ("1", "true"),
            "rotational": str(dev.get("rota")).lower() in ("1", "true"),
            "partitions": len(children),
            "contents": contents,
            "blocked": bool(blocked),
            "blocked_reason": blocked or "",
        })

    return {
        "disks": disks,
        "firmware": "uefi" if Path("/sys/firmware/efi").is_dir() else "bios",
    }


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


TOKEN_SCRIPT = '<script>window.WEBOS_TOKEN=%s;</script>'


class Handler(BaseHTTPRequestHandler):
    server_version = "WebOSBridge/2.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing

    def log_message(self, fmt, *args):
        pass  # the access log is noise on a kiosk

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8",
              extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, data, status=200):
        self._send(status, json.dumps(data).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, message, status=400):
        self._json({"error": message}, status)

    def _authorised(self):
        # A cross-origin page cannot set this header without a preflight, and
        # this server answers none.
        if self.headers.get("X-WebOS-Token") != TOKEN:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != ORIGIN:
            return False
        return True

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0 or length > 32 * 1024 * 1024:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}

    # ------------------------------------------------------------- methods

    def do_OPTIONS(self):
        # Deliberately unhelpful: no CORS headers, so a preflight always fails
        # and cross-origin JavaScript can never reach the API.
        self._send(405)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            if not self._authorised():
                return self._error("Unauthorised", 401)
            try:
                return self._api_get(path, query)
            except ApiError as exc:
                return self._error(exc.message, exc.status)
            except Exception as exc:  # noqa: BLE001
                log("GET", path, "failed:", exc)
                return self._error(str(exc), 500)

        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if not path.startswith("/api/"):
            return self._error("Not found", 404)
        if not self._authorised():
            return self._error("Unauthorised", 401)

        body = self._body()
        try:
            return self._api_post(path, body)
        except ApiError as exc:
            return self._error(exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001
            log("POST", path, "failed:", exc)
            return self._error(str(exc), 500)

    # -------------------------------------------------------------- static

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"

        if path.startswith("/apps/"):
            root, rel = APPS_DIR, path[len("/apps/"):]
        else:
            root, rel = UI_DIR, path.lstrip("/")

        # Resolve and confirm the result is still inside the served root, so
        # "../" and symlinks cannot escape it.
        try:
            target = (root / rel).resolve()
            root_resolved = root.resolve()
            if not (target == root_resolved or root_resolved in target.parents):
                return self._send(403, b"Forbidden")
        except (OSError, RuntimeError, ValueError):
            return self._send(400, b"Bad path")

        if not target.is_file():
            return self._send(404, b"Not found")

        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        try:
            data = target.read_bytes()
        except OSError:
            return self._send(404, b"Not found")

        # Give every served document the API token. Only same-origin scripts
        # can read it back out.
        if target.suffix.lower() == ".html":
            script = (TOKEN_SCRIPT % json.dumps(TOKEN)).encode("utf-8")
            lowered = data.lower()
            idx = lowered.find(b"<head>")
            if idx != -1:
                data = data[:idx + 6] + script + data[idx + 6:]
            else:
                data = script + data

        return self._send(200, data, ctype)

    # ----------------------------------------------------------- api: GET

    def _api_get(self, path, query):
        one = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731

        if path == "/api/status":
            cpu, network, volume = SAMPLER.snapshot()
            return self._json({
                "hostname": os.uname().nodename,
                "kernel": os.uname().release,
                "version": RELEASE.get("version"),
                "base": RELEASE.get("base"),
                "uptime": uptime_text(),
                "live": is_live(),
                "load": load_avg(),
                "cpu": {"percent": cpu, "cores": CPU_CORES, "model": CPU_MODEL},
                "ram": mem_info(),
                "disk": disk_info(),
                "battery": battery_info(),
                "network": network,
                "volume": volume,
            })

        if path == "/api/processes":
            return self._json(list_processes())

        if path == "/api/wifi/list":
            return self._json(wifi_list(rescan=one("rescan") == "1"))

        if path == "/api/volume":
            return self._json(get_volume())

        if path == "/api/brightness":
            return self._json(get_brightness())

        if path == "/api/files":
            return self._json(list_files(one("path")))

        if path == "/api/files/read":
            return self._json(read_file(one("path")))

        if path == "/api/terminal/read":
            session = SESSIONS.get(one("id"))
            return self._json(session.read())

        if path == "/api/config":
            return self._json(read_config())

        if path == "/api/install/disks":
            return self._json(list_disks())

        if path == "/api/install/status":
            return self._json(INSTALLER.status())

        return self._error("Unknown endpoint", 404)

    # ---------------------------------------------------------- api: POST

    def _api_post(self, path, body):
        if path == "/api/wifi/connect":
            ssid = (body.get("ssid") or "").strip()
            if not ssid:
                raise ApiError("SSID is required", 400)
            return self._json(wifi_connect(ssid, body.get("password") or ""))

        if path == "/api/wifi/disconnect":
            return self._json(wifi_disconnect())

        if path == "/api/volume/set":
            return self._json(set_volume(body.get("level", 50)))

        if path == "/api/volume/mute":
            return self._json(set_mute(bool(body.get("muted"))))

        if path == "/api/brightness/set":
            return self._json(set_brightness(body.get("level", 80)))

        if path == "/api/processes/kill":
            return self._json(kill_process(body.get("pid"), body.get("signal", "TERM")))

        if path == "/api/files/write":
            return self._json(write_file(body.get("path"), body.get("content", "")))

        if path == "/api/files/mkdir":
            return self._json(make_dir(body.get("path")))

        if path == "/api/files/delete":
            return self._json(delete_path(body.get("path")))

        if path == "/api/files/rename":
            return self._json(rename_path(body.get("path"), body.get("name")))

        if path == "/api/terminal/open":
            session = SESSIONS.open(body.get("cols", 80), body.get("rows", 24))
            return self._json({"id": session.id, "cols": session.cols,
                               "rows": session.rows})

        if path == "/api/terminal/write":
            session = SESSIONS.get(body.get("id"))
            session.write(str(body.get("data", "")))
            return self._json({"ok": True})

        if path == "/api/terminal/resize":
            session = SESSIONS.get(body.get("id"))
            session.set_size(body.get("cols", 80), body.get("rows", 24))
            return self._json({"ok": True})

        if path == "/api/terminal/close":
            return self._json(SESSIONS.close(body.get("id")))

        if path == "/api/config":
            return self._json(write_config(body if isinstance(body, dict) else {}))

        if path == "/api/power/shutdown":
            return self._json(power("poweroff"))

        if path == "/api/power/reboot":
            return self._json(power("reboot"))

        if path == "/api/install/start":
            return self._json(INSTALLER.start(body))

        return self._error("Unknown endpoint", 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


SAMPLER = Sampler()


def main():
    # The token is how the session's browser proves it is the browser. Anyone
    # who can read this file can use the API, so keep it to the owner.
    token_path = None
    for candidate in (Path("/run/webos"), Path.home() / ".cache" / "webos"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            token_path = candidate / "token"
            token_path.write_text(TOKEN)
            os.chmod(token_path, 0o600)
            break
        except OSError:
            token_path = None
    if token_path:
        log("token written to", token_path)

    SAMPLER.start()

    server = Server((HOST, PORT), Handler)
    log(f"serving {UI_DIR} on http://{HOST}:{PORT}")
    log(f"release {RELEASE.get('version')} ({RELEASE.get('base')}), live={is_live()}")

    def shutdown(signum, frame):
        log("shutting down")
        server.shutdown()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    finally:
        for sid in list(SESSIONS.sessions):
            SESSIONS.close(sid)
        server.server_close()


if __name__ == "__main__":
    main()
