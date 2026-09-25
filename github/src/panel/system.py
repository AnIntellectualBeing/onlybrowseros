"""
What the taskbar reads from, and changes on, the computer.

Every function here may block for a moment (most run a command), so the
taskbar calls them from worker threads, never from the GTK main loop.
Functions that change something return (ok, message).
"""

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

LIB = "/usr/lib/onlybrowseros"
ENV = dict(os.environ, LC_ALL="C", LANG="C")


def run(args, timeout=10, input_text=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           input=input_text, env=ENV)
    except FileNotFoundError:
        return 127, "", f"{args[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "took too long"
    return p.returncode, p.stdout, p.stderr


def last_line(*texts):
    for text in texts:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def watch(args, on_line):
    """Run a monitor command (nmcli monitor, pactl subscribe) for as long as the
    taskbar lives, calling on_line(line) from its thread for every line."""
    def loop():
        while True:
            try:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, env=ENV)
            except FileNotFoundError:
                return
            for line in p.stdout:
                on_line(line)
            p.wait()
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------------ network

def terse_fields(line):
    """Split one line of `nmcli -t` output. Fields are separated by ':'; a ':'
    or '\\' inside a field is escaped with a backslash."""
    fields, current, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    fields.append("".join(current))
    return fields


def nm_devices():
    code, out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=6)
    devices = []
    if code != 0:
        return devices
    for line in out.splitlines():
        f = terse_fields(line)
        if len(f) >= 4 and f[1] in ("wifi", "ethernet"):
            devices.append({"name": f[0], "type": f[1], "state": f[2], "connection": f[3]})
    return devices


def wifi_enabled():
    code, out, _ = run(["nmcli", "radio", "wifi"], timeout=5)
    return code == 0 and out.strip() == "enabled"


def active_wifi_signal():
    code, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SIGNAL", "device", "wifi", "list", "--rescan", "no"],
                       timeout=6)
    for line in out.splitlines():
        f = terse_fields(line)
        if len(f) >= 2 and f[0].strip() == "*":
            try:
                return int(f[1])
            except ValueError:
                return 0
    return 0


def network_status():
    """What the taskbar icon shows."""
    devices = nm_devices()
    wifi = next((d for d in devices if d["type"] == "wifi"), None)
    wired = [d for d in devices if d["type"] == "ethernet"]
    status = {
        "has_wifi": wifi is not None,
        "has_ethernet": bool(wired),
        "wifi_enabled": wifi_enabled() if wifi else False,
        "kind": "none",
        "connected": False,
        "connecting": False,
        "ssid": "",
        "signal": 0,
    }
    for d in wired:
        if d["state"] == "connected":
            status.update(kind="ethernet", connected=True)
            return status
    if wifi and wifi["state"] == "connected":
        status.update(kind="wifi", connected=True, ssid=wifi["connection"], signal=active_wifi_signal())
    elif wifi and wifi["state"].startswith("connecting"):
        status.update(kind="wifi", connecting=True, ssid=wifi["connection"])
    elif any(d["state"].startswith("connecting") for d in wired):
        status.update(kind="ethernet", connecting=True)
    return status


def device_ip(name):
    code, out, _ = run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", name], timeout=6)
    for line in out.splitlines():
        key, _, value = line.partition(":")
        if key.startswith("IP4.ADDRESS") and value:
            return value.split("/")[0]
    return ""


def ethernet_details():
    details = []
    for d in nm_devices():
        if d["type"] != "ethernet":
            continue
        info = {"name": d["name"], "state": d["state"], "ip": "", "speed": ""}
        if d["state"] == "connected":
            info["ip"] = device_ip(d["name"])
            try:
                speed = int(Path(f"/sys/class/net/{d['name']}/speed").read_text())
                if speed > 0:
                    info["speed"] = f"{speed} Mb/s" if speed < 1000 else f"{speed // 1000} Gb/s"
            except (OSError, ValueError):
                pass
        details.append(info)
    return details


def saved_wifi():
    code, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], timeout=6)
    names = set()
    for line in out.splitlines():
        f = terse_fields(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            names.add(f[0])
    return names


def wifi_networks(rescan=False):
    args = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
            "--rescan", "yes" if rescan else "auto"]
    code, out, err = run(args, timeout=30)
    if code != 0 and rescan:
        # NetworkManager refuses a scan right after another one; show what it has.
        code, out, err = run(args[:-1] + ["auto"], timeout=30)
    if code != 0:
        raise RuntimeError(clean_error(err or out) or "Could not look for Wi-Fi networks.")

    saved = saved_wifi()
    best = {}
    for line in out.splitlines():
        f = terse_fields(line)
        if len(f) < 4 or not f[1]:
            continue  # hidden networks have no name to show
        try:
            signal = int(f[2])
        except ValueError:
            signal = 0
        security = f[3].strip()
        net = {
            "ssid": f[1],
            "signal": signal,
            "secure": security not in ("", "--"),
            "enterprise": "802.1X" in security,
            "active": f[0].strip() == "*",
            "saved": f[1] in saved,
        }
        # One entry per name: the same network shows once per band and access point.
        prev = best.get(net["ssid"])
        if prev is None or net["active"] or (not prev["active"] and signal > prev["signal"]):
            best[net["ssid"]] = net
    return sorted(best.values(), key=lambda n: (not n["active"], not n["saved"], -n["signal"]))


def clean_error(text):
    return re.sub(r"^Error:\s*", "", last_line(text))


def wifi_connect(ssid, password=None):
    """Returns (ok, message, needs_password)."""
    saved = ssid in saved_wifi()
    if password is None and saved:
        code, out, err = run(["nmcli", "connection", "up", "id", ssid], timeout=60)
    else:
        args = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        code, out, err = run(args, timeout=60)
        if code != 0 and not saved:
            # A failed first attempt leaves a half-made profile behind; without
            # this the next try would reuse the wrong password.
            run(["nmcli", "connection", "delete", "id", ssid], timeout=10)
    if code == 0:
        return True, f"Connected to {ssid}.", False

    text = (err or out).lower()
    if any(k in text for k in ("secrets were required", "psk", "no secrets", "802-1x", "invalid passphrase")):
        return False, "Wrong password. Try again.", True
    if "no network with ssid" in text:
        return False, f"“{ssid}” is out of range.", False
    if "took too long" in text or "timeout" in text:
        return False, "The network did not answer. Move closer to the router and try again.", False
    return False, clean_error(err or out) or "Could not connect.", False


def wifi_disconnect():
    for d in nm_devices():
        if d["type"] == "wifi":
            code, out, err = run(["nmcli", "device", "disconnect", d["name"]], timeout=20)
            return code == 0, clean_error(err or out)
    return False, "No Wi-Fi adapter."


def wifi_forget(ssid):
    code, out, err = run(["nmcli", "connection", "delete", "id", ssid], timeout=15)
    return code == 0, clean_error(err or out)


def set_wifi_enabled(on):
    code, out, err = run(["nmcli", "radio", "wifi", "on" if on else "off"], timeout=15)
    return code == 0, clean_error(err or out)


# ---------------------------------------------------------------- bluetooth

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x01\x02\r]")
MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def btctl(*args, timeout=10):
    code, out, err = run(["bluetoothctl", *args], timeout=timeout)
    return code, ANSI.sub("", out), ANSI.sub("", err)


def bt_available():
    root = Path("/sys/class/bluetooth")
    return root.is_dir() and any(root.glob("hci*"))


def _parse_devices(text):
    devices = []
    for line in text.splitlines():
        m = re.match(r"^\s*Device\s+([0-9A-F:]{17})\s*(.*)$", line.strip())
        if m:
            name = m.group(2).strip()
            devices.append({"mac": m.group(1), "name": name})
    return devices


def _unnamed(device):
    # BlueZ uses the address, dashed, as the name of a device that sent none.
    return not device["name"] or device["name"].replace("-", ":") == device["mac"]


def bt_status():
    if not bt_available():
        return {"available": False, "powered": False, "connected": []}
    _, out, _ = btctl("show", timeout=6)
    powered = re.search(r"^\s*Powered:\s*yes", out, re.M) is not None
    connected = []
    if powered:
        _, out, _ = btctl("devices", "Connected", timeout=6)
        connected = [d["name"] for d in _parse_devices(out)]
    return {"available": True, "powered": powered, "connected": connected}


def bt_devices():
    _, paired_out, _ = btctl("devices", "Paired", timeout=6)
    _, connected_out, _ = btctl("devices", "Connected", timeout=6)
    connected = {d["mac"] for d in _parse_devices(connected_out)}
    devices = _parse_devices(paired_out)
    for d in devices:
        d["connected"] = d["mac"] in connected
        if _unnamed(d):
            d["name"] = "Unnamed device"
    return sorted(devices, key=lambda d: (not d["connected"], d["name"].lower()))


def bt_set_powered(on):
    if on:
        run(["rfkill", "unblock", "bluetooth"], timeout=5)
        time.sleep(0.6)
    code, out, err = btctl("power", "on" if on else "off", timeout=10)
    if "succeeded" in out.lower() or code == 0:
        return True, ""
    if "blocked" in (out + err).lower():
        return False, "Bluetooth is switched off by a key or switch on this laptop."
    return False, last_line(err, out) or "Could not change Bluetooth."


def bt_scan(seconds=12):
    """Look for nearby devices that are ready to pair."""
    btctl("--timeout", str(seconds), "scan", "on", timeout=seconds + 8)
    _, out, _ = btctl("devices", timeout=6)
    paired = {d["mac"] for d in bt_devices()}
    return [d for d in _parse_devices(out) if d["mac"] not in paired and not _unnamed(d)]


def bt_pair(mac, on_code=None):
    """Pair, trust and connect. Talks to one bluetoothctl session, because
    pairing needs an agent registered in the same process.

    Headphones, speakers and mice pair without a code. A keyboard shows a code
    to type on it, and a phone or computer shows one to confirm; on_code(text)
    is then called (from this thread) with what to tell the user."""
    if not MAC.match(mac):
        return False, "Unknown device."
    try:
        proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=ENV)
    except FileNotFoundError:
        return False, "Bluetooth tools are not installed."

    # The agent's questions are prompts without a line ending, so read what
    # arrives rather than whole lines.
    chunks = queue.Queue()

    def reader():
        fd = proc.stdout.fileno()
        while True:
            try:
                data = os.read(fd, 4096)
            except OSError:
                data = b""
            if not data:
                break
            chunks.put(ANSI.sub("", data.decode("utf-8", "replace")))
        chunks.put(None)

    threading.Thread(target=reader, daemon=True).start()
    seen = [""]

    def send(command):
        try:
            proc.stdin.write((command + "\n").encode())
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def tell(text):
        if on_code:
            try:
                on_code(text)
            except Exception:  # noqa: BLE001 - the UI's problem, not pairing's
                pass

    def answer_agent():
        """Answer whatever the agent asked since the last call."""
        text = seen[0]
        m = re.search(r"Confirm passkey (\d+)", text)
        if m:
            seen[0] = text[m.end():]
            send("yes")
            tell(f"If the device shows {m.group(1)}, confirm it there.")
            return
        m = re.search(r"(?:Passkey|PIN code):\s*(\d+)", text)
        if m:
            seen[0] = text[m.end():]
            tell(f"On the device, type {m.group(1)} and press Enter.")
            return
        m = re.search(r"Enter (?:PIN code|passkey)", text)
        if m:
            seen[0] = text[m.end():]
            # os.urandom rather than the secrets module, which loads OpenSSL
            # (several MB) into the taskbar for one number.
            code = f"{int.from_bytes(os.urandom(4), 'big') % 1000000:06d}"
            send(code)
            tell(f"On the device, type {code} and press Enter.")
            return
        m = re.search(r"Authorize service|Accept pairing \(yes/no\)", text)
        if m:
            seen[0] = text[m.end():]
            send("yes")

    def wait_for(outcomes, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = chunks.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None:
                return None
            seen[0] = (seen[0] + chunk)[-4000:]
            answer_agent()
            for key, text in outcomes:
                if text in seen[0]:
                    seen[0] = seen[0][seen[0].index(text) + len(text):]
                    return key
        return "timeout"

    try:
        # KeyboardDisplay: the agent can show a code and accept one, which is
        # what keyboards and phones ask for; headphones still need nothing.
        send("agent KeyboardDisplay")
        send("default-agent")
        send("scan on")
        time.sleep(2)
        send(f"pair {mac}")
        # Long enough to type a code on a keyboard.
        result = wait_for([("ok", "Pairing successful"), ("ok", "AlreadyExists"),
                           ("auth", "AuthenticationFailed"), ("auth", "AuthenticationRejected"),
                           ("auth", "AuthenticationCanceled"), ("auth", "AuthenticationTimeout"),
                           ("fail", "Failed to pair"), ("gone", "not available")], 75)
        if result == "gone":
            return False, "The device went out of range. Put it in pairing mode and search again."
        if result == "auth":
            return False, "The code was not accepted in time. Choose the device to try again."
        if result != "ok":
            return False, "Pairing did not work. Put the device in pairing mode and try again."
        send(f"trust {mac}")
        wait_for([("ok", "trust succeeded")], 6)
        send("scan off")
        send(f"connect {mac}")
        result = wait_for([("ok", "Connection successful"), ("fail", "Failed to connect")], 30)
        if result == "ok":
            return True, "Connected."
        return True, "Paired. If it does not work yet, choose it and then Connect."
    finally:
        send("quit")
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def bt_connect(mac):
    if not MAC.match(mac):
        return False, "Unknown device."
    code, out, err = btctl("--timeout", "25", "connect", mac, timeout=35)
    if "Connection successful" in out:
        return True, "Connected."
    return False, "Could not connect. Make sure the device is on and nearby."


def bt_disconnect(mac):
    if not MAC.match(mac):
        return False, "Unknown device."
    code, out, err = btctl("disconnect", mac, timeout=15)
    return "Successful disconnected" in out or code == 0, ""


def bt_forget(mac):
    if not MAC.match(mac):
        return False, "Unknown device."
    code, out, err = btctl("remove", mac, timeout=15)
    return code == 0, ""


# -------------------------------------------------------------------- sound

def _percent(text):
    m = re.search(r"(\d+)%", text)
    return int(m.group(1)) if m else 0


def audio_status():
    code, out, _ = run(["pactl", "get-default-sink"], timeout=5)
    sink = out.strip()
    if code != 0 or not sink or sink == "auto_null":
        status = {"available": False, "volume": 0, "muted": True}
    else:
        _, vol, _ = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=5)
        _, mute, _ = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=5)
        status = {"available": True, "volume": _percent(vol), "muted": "yes" in mute}

    code, out, _ = run(["pactl", "get-default-source"], timeout=5)
    source = out.strip()
    if code != 0 or not source or source.endswith(".monitor"):
        status.update(mic_available=False, mic_volume=0, mic_muted=True)
    else:
        _, vol, _ = run(["pactl", "get-source-volume", "@DEFAULT_SOURCE@"], timeout=5)
        _, mute, _ = run(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"], timeout=5)
        status.update(mic_available=True, mic_volume=_percent(vol), mic_muted="yes" in mute)
    return status


def audio_devices(kind):
    """Speakers ('sink') or microphones ('source') the user can choose between."""
    code, out, _ = run(["pactl", "--format=json", "list", kind + "s"], timeout=6)
    _, default, _ = run(["pactl", f"get-default-{kind}"], timeout=5)
    default = default.strip()
    try:
        items = json.loads(out) if code == 0 else []
    except json.JSONDecodeError:
        items = []
    devices = []
    for item in items:
        name = item.get("name", "")
        if not name or name == "auto_null" or name.endswith(".monitor"):
            continue
        devices.append({
            "name": name,
            "label": item.get("description") or name,
            "default": name == default,
        })
    return devices


def set_volume(kind, percent):
    percent = max(0, min(100, int(percent)))
    target = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
    code, _, err = run(["pactl", f"set-{kind}-volume", target, f"{percent}%"], timeout=5)
    return code == 0, last_line(err)


def set_mute(kind, muted):
    target = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
    code, _, err = run(["pactl", f"set-{kind}-mute", target, "1" if muted else "0"], timeout=5)
    return code == 0, last_line(err)


def set_default_device(kind, name):
    code, _, err = run(["pactl", f"set-default-{kind}", name], timeout=5)
    return code == 0, last_line(err)


# --------------------------------------------------------------- brightness

def brightness():
    """Screen brightness in percent, or None when the screen has no backlight
    control (desktop monitors, most virtual machines)."""
    root = Path("/sys/class/backlight")
    if not root.is_dir() or not any(root.iterdir()):
        return None
    code, out, _ = run(["brightnessctl", "-m", "-c", "backlight", "info"], timeout=5)
    parts = out.strip().split(",")
    if code != 0 or len(parts) < 4:
        return None
    try:
        return int(parts[3].rstrip("%"))
    except ValueError:
        return None


def set_brightness(percent):
    percent = max(5, min(100, int(percent)))
    code, _, err = run(["brightnessctl", "-q", "-c", "backlight", "set", f"{percent}%"], timeout=5)
    return code == 0, last_line(err)


# ------------------------------------------------------------------ battery

def _read(path, cast=str):
    try:
        return cast(path.read_text().strip())
    except (OSError, ValueError):
        return None


def battery():
    """None on a computer without a battery."""
    root = Path("/sys/class/power_supply")
    if not root.is_dir():
        return None

    now = full = rate = 0
    percents, statuses, plugged, found = [], [], False, False
    for dev in root.iterdir():
        kind = _read(dev / "type")
        if kind == "Mains" and _read(dev / "online") == "1":
            plugged = True
        if kind != "Battery" or _read(dev / "scope") == "Device" or _read(dev / "present") == "0":
            continue  # a wireless mouse's battery is not the laptop's
        found = True
        capacity = _read(dev / "capacity", int)
        if capacity is not None:
            percents.append(capacity)
        statuses.append(_read(dev / "status") or "")
        for prefix, rate_name in (("energy", "power_now"), ("charge", "current_now")):
            n = _read(dev / f"{prefix}_now", int)
            f = _read(dev / f"{prefix}_full", int)
            if n is not None and f:
                now += n
                full += f
                rate += abs(_read(dev / rate_name, int) or 0)
                break

    if not found:
        return None

    percent = round(100 * now / full) if full else (round(sum(percents) / len(percents)) if percents else 0)
    percent = max(0, min(100, percent))
    charging = "Charging" in statuses
    discharging = "Discharging" in statuses
    minutes = None
    if rate > 0 and charging:
        minutes = int((full - now) / rate * 60)
    elif rate > 0 and discharging:
        minutes = int(now / rate * 60)
    if minutes is not None and not 0 < minutes < 48 * 60:
        minutes = None
    return {
        "percent": percent,
        "charging": charging,
        "plugged": plugged or charging or not discharging,
        "full": not charging and not discharging and percent >= 95,
        "minutes": minutes,
    }


# ------------------------------------------------------------------ screens

INTERNAL_SCREEN = re.compile(r"^(eDP|LVDS|DSI)", re.I)


def parse_xrandr(text):
    """[{name, connected, active, preferred}] from `xrandr --query`."""
    outputs = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)(?: primary)?(?: (\d+x\d+)\+\d+\+\d+)?", line)
        if m:
            outputs.append({"name": m.group(1), "connected": m.group(2) == "connected",
                            "active": m.group(3) is not None, "preferred": None, "first": None})
            continue
        m = re.match(r"^\s+(\d+x\d+)\S*\s+(.*)$", line)
        if m and outputs:
            out = outputs[-1]
            out["first"] = out["first"] or m.group(1)
            if "+" in m.group(2) and not out["preferred"]:
                out["preferred"] = m.group(1)
    for out in outputs:
        out["preferred"] = out["preferred"] or out["first"]
    return outputs


def mirror_command(outputs):
    """The xrandr command that shows the same picture on every connected
    screen: the laptop's own screen at its best size, and each other screen
    scaled to match, so nothing (the taskbar least of all) is cut off. There is
    one browser window, so a second desktop would only be somewhere to lose
    the mouse."""
    connected = [o for o in outputs if o["connected"] and o["preferred"]]
    if not connected:
        return None
    main = next((o for o in connected if INTERNAL_SCREEN.match(o["name"])), connected[0])
    args = ["xrandr", "--output", main["name"], "--mode", main["preferred"], "--pos", "0x0",
            "--primary", "--scale", "1x1"]
    for o in connected:
        if o is not main:
            args += ["--output", o["name"], "--auto", "--same-as", main["name"],
                     "--scale-from", main["preferred"]]
    for o in outputs:
        if not o["connected"] and o["active"]:
            args += ["--output", o["name"], "--off"]
    return args


def arrange_screens(only_if_needed=False):
    code, out, _ = run(["xrandr", "--query"], timeout=10)
    if code != 0:
        return False, "xrandr failed"
    outputs = parse_xrandr(out)
    if only_if_needed:
        connected = [o for o in outputs if o["connected"]]
        stale = [o for o in outputs if o["active"] and not o["connected"]]
        if len(connected) <= 1 and not stale:
            return True, ""   # one screen, already showing: leave it as it started
    args = mirror_command(outputs)
    if not args:
        return False, "no screen"
    code, out, err = run(args, timeout=15)
    return code == 0, last_line(err, out)


# ---------------------------------------------------------- power, session

def power(action):
    commands = {"suspend": ["systemctl", "suspend"],
                "reboot": ["systemctl", "reboot"],
                "poweroff": ["systemctl", "poweroff"]}
    code, out, err = run(commands[action], timeout=20)
    return code == 0, last_line(err, out)


def is_live():
    try:
        return "boot=live" in Path("/proc/cmdline").read_text().split()
    except OSError:
        return False


def memory_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return 2048


def memory_usage():
    """(total MB, available MB) from the kernel; (0, 0) if unreadable."""
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        return 0, 0
    return values.get("MemTotal", 0), values.get("MemAvailable", 0)


def free_space_mb(path=None):
    """Free space where downloads and the browser's data are kept. On the USB
    stick that is memory, so it runs out sooner."""
    try:
        st = os.statvfs(path or str(Path.home()))
    except OSError:
        return None
    return st.f_bavail * st.f_frsize // (1024 * 1024)


DOWNLOADS_URL = "file:///usr/share/onlybrowseros/start/downloads.html"


def open_in_browser(url):
    """A new tab in the running browser. With the browser closed (the home
    screen shows), nothing: its button brings the browser back."""
    code, _, _ = run(["pgrep", "-x", "firefox-esr"], timeout=5)
    if code != 0:
        return
    subprocess.Popen(["firefox-esr", "--new-tab", url], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/onlybrowseros-{os.getuid()}"
    path = Path(base) / "onlybrowseros"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_state():
    try:
        return json.loads(Path("/run/onlybrowseros/state.json").read_text())
    except (OSError, ValueError):
        return {}


def set_tab_limit(value):
    code, out, err = run(["sudo", "-n", f"{LIB}/set-tab-limit", str(value)], timeout=30)
    return code == 0, last_line(err, out)


def restart_browser():
    # The flag tells /usr/lib/onlybrowseros/browser to start Firefox again
    # straight away instead of showing the home screen.
    try:
        (runtime_dir() / "restart-browser").touch()
    except OSError:
        pass
    code, _, _ = run(["pkill", "-TERM", "-x", "firefox-esr"], timeout=5)
    return code == 0, ""


# The extension's address is fixed by /usr/lib/onlybrowseros/tune.
SETTINGS_URL = "moz-extension://7f3c2a10-4b6e-4d1a-9c2f-0b5e8d7a6c31/settings.html"


def open_settings():
    """Open the settings page in the browser; when the browser is closed (the
    home screen shows), start it with the settings page."""
    code, _, _ = run(["pgrep", "-x", "firefox-esr"], timeout=5)
    if code == 0:
        subprocess.Popen(["firefox-esr", "--new-tab", SETTINGS_URL], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True, ""
    try:
        (runtime_dir() / "open-settings").touch()
    except OSError as exc:
        return False, str(exc)
    run(["pkill", "-x", "obos-home"], timeout=5)
    return True, ""


def start_installer():
    code, _, _ = run(["pgrep", "-x", "obos-installer"], timeout=5)
    if code == 0:
        return
    log = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "onlybrowseros" / "installer.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as out:
        subprocess.Popen(["python3", f"{LIB}/installer/installer.py"], stdout=out,
                         stderr=subprocess.STDOUT, start_new_session=True)
