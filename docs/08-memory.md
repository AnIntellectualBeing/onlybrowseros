# Memory — Where the RAM Goes and How I Brought It Down

OnlyBrowserOS has to run on laptops with 1 GB of RAM. This file explains how
memory is used, how I measure it, and what each setting really saves.

## Two numbers that matter

- **In use** = `MemTotal − MemAvailable` from `/proc/meminfo`. What the
  kernel cannot hand to the next tab without swapping. This is the number I
  track as "the system's baseline".
- **PSS** (proportional set size) per process, from
  `/proc/<pid>/smaps_rollup`. Memory shared by several processes (like
  Firefox's 100+ MB `libxul.so`) is split between them, so PSS values add up
  correctly. I also record **anonymous** memory: the part that is not backed
  by a file and can only go to swap. File-backed pages (program code, fonts)
  can be dropped under pressure and read again from disk.

`free -m` shows neither directly; my self-test prints both
(`memory_breakdown` in `github/src/system/autotest`).

## Where it goes (1 GB, installed, start page open)

RESULTS_TABLE

The web page dominates everything else. Measured with the same Firefox and
settings:

| Open in the browser | Firefox PSS | of which anonymous |
|---|---|---|
| Start page only | 363 MB | 148 MB |
| Wikipedia article | 354 MB | 182 MB |
| YouTube front page | 528 MB | 293 MB |

No operating system can make YouTube smaller; it can only keep everything
*around* the browser small and make sure a heavy page never freezes the
laptop.

## What keeps a 1 GB laptop usable

1. **zram**: compressed swap in RAM (`etc/systemd/zram-generator.conf`).
   Browser memory compresses to about a third, so idle tabs' memory shrinks
   instead of hitting a slow disk. `vm.swappiness=150` and `page-cluster=0`
   (`etc/sysctl.d/90-onlybrowseros.conf`) tell the kernel that swapping to
   zram is cheap.
2. **earlyoom**: when RAM and swap are both almost gone, it closes the
   heaviest *tab's* process (the tab shows "crashed", one click reloads it)
   instead of the kernel freezing the whole machine for minutes. The browser
   window, taskbar and screen are on its "avoid" list.
3. **Tab limit**: 1 tab on a 1 GB laptop, 2 on 2 GB, and so on
   (`src/shared/levels.py`). Background tabs are unloaded early
   (`browser.tabs.unloadOnLowMemory`, 20% threshold on the low tier).
4. **Firefox tuned per machine at every boot** (`src/system/tune`): on the low
   tier, no site isolation (Fission) and at most 2 page processes, smaller
   caches, no prefetching, networking and extensions inside the main process.
5. **No "Recommends"** when installing packages, and no desktop environment,
   display manager, file indexer, notification daemon or update applet.
6. **On-demand services**: printing (CUPS) starts only when something prints;
   the apt update timers are delayed and low priority.

## How I measure a Firefox setting

A virtual machine without hardware acceleration was too noisy: the same image
measured ±30 MB apart between runs. So I built a bench:

1. An **overlay** mount on top of the build's `chroot/` folder: the image's
   exact Firefox, extension and settings, with every change thrown away
   afterwards.
2. A virtual screen (`Xvfb`) and Firefox started inside the overlay with
   `chroot`, **offline** (`unshare --net`) so background downloads don't add
   noise.
3. Firefox's remote-control protocol (Marionette) asks Firefox itself which
   process holds which page (`ChromeUtils.requestProcInfo`) and to free
   memory (`minimizeMemoryUsage`, the same as a low-memory event) before
   measuring.
4. PSS and anonymous memory summed per process from `/proc`.

The scripts are in `github/build/bench/` (`setup.sh`, `run.sh`,
`measure.py`). Repeat runs then agree within 1–2 MB. Always measure a baseline next to each
change: one early "−53 MB" result disappeared when re-run beside a fresh
baseline.

## What I measured (start page, low tier)

| Setting | Result | Decision |
|---|---|---|
| `dom.ipc.keepProcessesAlive.privilegedabout = 0` | −14 MB: removes a process kept alive for Firefox's own new-tab page, which holds no page | **kept** (all tiers) |
| `media.rdd-process.enabled = false` (no separate video decoder) | −11 MB anonymous | rejected: hardware video decoding runs in that process; without it, video is decoded by the CPU, which lags on old laptops |
| Separate file:// and "privileged" process off | no change: the process is only renamed | rejected (and it weakens isolation) |
| Accessibility engine off | no change | rejected |
| Safe browsing off | no change | rejected (it protects people from phishing) |
| Form autofill, reader view, translations, thumbnails off | no change | rejected |
| `dom.ipc.processCount = 1` | no change with one tab | kept at 2 |
| Extensions in their own process | +12 MB anonymous (+15 MB PSS) | kept in the main process |

## Ideas not done yet, with estimates

- **Taskbar in C instead of Python + GTK**: roughly 25–40 MB → 8–10 MB.
  The biggest remaining item outside Firefox; a rewrite of ~2,000 lines.
- **Wayland kiosk (cage) instead of Xorg + openbox**: maybe 10–20 MB, but the
  taskbar and popups would need rewriting for Wayland.
- **Alpine Linux instead of Debian**: I estimate 20–40 MB (OpenRC instead of
  systemd, musl instead of glibc). It costs Secure Boot (Alpine has no
  Microsoft-signed boot chain), and Netflix/Spotify only work through a
  patched, unsandboxed Widevine. Not worth it: Firefox is 70%+ of the memory
  on any distribution.
