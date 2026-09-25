#!/usr/bin/env python3
"""Measure Firefox's memory in the bench (see setup.sh and docs/08-memory.md).

    sudo ./run.sh NAME '{"pref": value}' [URL]     offline (run.sh), or
    sudo python3 measure.py NAME '{...}' [URL]      online

1. Writes the policies and the low-tier preferences exactly as
   /usr/lib/onlybrowseros/tune does on a 1 GB laptop, plus the extra prefs.
2. Starts Firefox once with a fresh profile (creates it, installs the
   extension), stops it, starts it again on the start page or URL.
3. After SETTLE seconds (default 60) asks Firefox, over Marionette, which
   process holds which page, and to minimise its memory (NOMIN=1 skips it).
4. Prints PSS / anonymous MB per process. SHOWPROCS=1 also lists the pages.
"""
import json, os, signal, subprocess, sys, time
from importlib.machinery import SourceFileLoader
from pathlib import Path

B = Path(__file__).parent
R = B / "root"
name, extra = sys.argv[1], json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
url = sys.argv[3] if len(sys.argv) > 3 else None
tune = SourceFileLoader("tune", str(R / "usr/lib/onlybrowseros/tune")).load_module()

prefs = {**tune.COMMON_PREFS, **tune.TIER_PREFS["low"], **extra}
prefs = {k: v for k, v in prefs.items() if v is not None}
(R / "usr/lib/firefox-esr/distribution").mkdir(parents=True, exist_ok=True)
(R / "usr/lib/firefox-esr/distribution/policies.json").write_text(json.dumps(tune.policies(1, "low")))
(R / "etc/firefox-esr/onlybrowseros.js").write_text(tune.prefs_js(prefs))

def ours():
    pids = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if os.readlink(p / "root") == str(R) and "firefox" in (p / "cmdline").read_text(errors="ignore"):
                    pids.append(int(p.name))
            except OSError:
                pass
    return pids

def stop():
    for pid in ours():
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass
    for _ in range(40):
        if not ours(): return
        time.sleep(0.5)
    for pid in ours():
        try: os.kill(pid, signal.SIGKILL)
        except OSError: pass
    time.sleep(1)

def start(args=()):
    return subprocess.Popen((["unshare", "--net"] if os.environ.get("OFFLINE") else []) + ["chroot", "--userspec=1000:1000", str(R), "/usr/bin/env", "-i",
        "HOME=/home/user", "DISPLAY=:90", "PATH=/usr/bin:/bin", "LANG=en_US.UTF-8", "NO_AT_BRIDGE=1",
        "firefox-esr", "--marionette", "-remote-allow-system-access", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def pss(pid):
    try:
        for line in open(f"/proc/{pid}/smaps_rollup"):
            if line.startswith("Pss:"): return int(line.split()[1]) // 1024
    except OSError: return 0
    return 0

stop()
subprocess.run(["rm", "-rf", str(R / "home/user/.mozilla"), str(R / "home/user/.cache/mozilla")])
start(); time.sleep(40); stop()          # first start: profile + extension
start([url] if url else []); time.sleep(int(os.environ.get('SETTLE', '60')))
sys.path.insert(0, str(B))
from marionette import Marionette, PROCS, MINIMIZE
procs = []
try:
    m = Marionette()
    procs = m.js(PROCS)
    if not os.environ.get("NOMIN"):
        m.js(MINIMIZE); time.sleep(3); m.js(MINIMIZE); time.sleep(3)
except Exception as exc:
    print("marionette:", exc, file=sys.stderr)
def anon(pid):
    try:
        for line in open(f"/proc/{pid}/smaps_rollup"):
            if line.startswith("Anonymous:"): return int(line.split()[1]) // 1024
    except OSError: return 0
    return 0
rows = []
for pid in ours():
    comm = Path(f"/proc/{pid}/comm").read_text().strip()
    rows.append((pss(pid), anon(pid), comm, pid))
stop()
total = sum(r[0] for r in rows); tanon = sum(r[1] for r in rows)
detail = ", ".join(f"{c} {m}/{a}" for m, a, c, _ in sorted(rows, reverse=True) if m)
print(f"{name:24s} PSS {total:4d} MB  anon {tanon:4d} MB  [{detail}]", flush=True)
if os.environ.get("SHOWPROCS"):
    for p in procs: print("   ", p, flush=True)
