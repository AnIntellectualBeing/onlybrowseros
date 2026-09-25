# How I Built It — From Prototype to v1.2

The project in order, and the problems that were hardest to solve. Each
problem lists the symptom, the cause and the fix, and names the file that
holds the fix.

## Timeline

| When (2026) | What happened |
|---|---|
| First | **WebOS prototype** (`github/legacy/`): a desktop made of web pages (file explorer, text editor, terminal, task manager, settings, installer) running in a Chromium kiosk, with a Python "system bridge" server on localhost giving those pages access to the computer. |
| Sep 13 | **Pivot to OnlyBrowserOS.** First Debian-based ISO builds (debootstrap → squashfs → ISO), first automated QEMU tests: live boot, BIOS install, install on a 1 GB VM. |
| Sep 14 | First full UI (taskbar, installer, home screen) — a dark theme. Fixes from the first test rounds. |
| Sep 15 | **Light redesign** to match my reference mockups (landscape, white cards, blue accent, round globe logo). Tab limit presented as Low-end / Mid-range / High-end PC. One Settings page inside the browser. Battery warnings. |
| Sep 16 | Downloads limited to files the browser can open, the Downloads page, lock-down of Firefox menus, printing. OnlyBrowserOS turned into one `.deb` package; signed update repository. **Secure Boot support.** Released **v1.1**. |
| Sep 25 | **v1.2**: Bluetooth audio and pairing codes, more laptop firmware, volume/brightness overlay, HDMI mirroring, screen power saving, power-button sleep, self-restarting screen session, low-space warning, Intel RST hint in the installer. **Memory work** with a new measurement bench (see `08-memory.md`). |

## Why I dropped the web-page desktop

The prototype recreated a desktop (files, editor, terminal) as web pages. Two
problems:

1. **Security.** To let web pages read files and run commands, the bridge
   exposed a powerful API on `127.0.0.1`. Every website the user visits runs
   in the same browser and can reach loopback. I protected it with a token and
   by never answering CORS preflights, but a local server that can run a shell
   is exactly what a hostile page wants to find.
2. **It missed the point.** The people I built this for don't need a file
   manager or a terminal; they need the web. Every extra app was something to
   learn and something to break.

So the new design has **no desktop at all**: the browser is the whole screen.
The few system features left (Wi-Fi, sound, battery) live in a native
taskbar, and the one settings page talks to the system through Firefox
**native messaging**, which only my extension can use and which starts a
helper per request instead of running a server (`04-decisions-and-why.md`).

## The hardest problems

### 1. Secure Boot: "Access Denied" on shop-bought laptops
- **Symptom:** with Secure Boot on (the default on almost every laptop since
  ~2012), the firmware refused to start the USB stick.
- **Cause:** I built the ISO with `grub-mkrescue`, which creates its own
  **unsigned** GRUB. Secure Boot only runs code signed by keys in the
  firmware (Microsoft's).
- **Fix:** assemble the ISO by hand: Microsoft-signed `shim` as
  `\EFI\BOOT\BOOTX64.EFI`, Debian-signed GRUB next to it, and a tiny
  `\EFI\debian\grub.cfg` (the only place signed GRUB looks) that finds the ISO
  and loads the real menu. Then Debian's signed kernel. Tested in QEMU with
  OVMF firmware that has Microsoft's keys enrolled and enforcement on.
  (`build/build-iso.sh`, stage `iso`; `06-build-from-scratch.md` Part 9)

### 2. Firefox refused my own extension
- **Symptom:** the tab-limit extension installed by policy was rejected as
  unsigned, even though I set `xpinstall.signatures.required = false`.
- **Cause:** preference files are read in order. Mine was in
  `/usr/lib/firefox-esr/defaults/pref/`, which is read **before** Firefox's
  built-in defaults, and those set the value back to `true`.
- **Fix:** write the preferences to `/etc/firefox-esr/`, which Debian's
  Firefox reads after its defaults. (`src/system/tune`, docstring)

### 3. Nothing on the screen could be clicked
- **Symptom:** the browser appeared but ignored every mouse click.
- **Cause:** in openbox's config I bound a plain left click on the `Frame`
  context. Frame covers the window's contents too, and openbox *consumes*
  clicks bound there instead of passing them on.
- **Fix:** bind focus-on-click only on the `Client` context, whose clicks
  openbox passes through. (`build/overlay/etc/onlybrowseros/openbox/rc.xml`)

### 4. The installer could not rename the account
- **Symptom:** installing failed at "Setting up your account".
- **Cause:** `usermod -l` refuses to rename a user who has running processes,
  and inside the target it saw the live session's processes (same user)
  through the bind-mounted `/proc`.
- **Fix:** do all account and file edits **before** binding `/proc` into the
  target, and only then run the boot-loader steps that need it.
  (`src/installer/install-helper`, `configure_system`)

### 5. After installing, the computer booted the USB stick again
- **Symptom:** people leave the stick in; the restart after installing landed
  in the live system with its "Install" button again.
- **Fix:** the ISO's boot menu looks for `/etc/onlybrowseros/installed` on
  any disk, and if it finds one, its first entry starts the installed system.
  (`build/build-iso.sh`, `grub.cfg`)

### 6. A web page that crashes Firefox, forever
- **Risk:** session restore reopens the page that
  crashed Firefox, so it would crash again on every start.
- **Fix:** the `browser` loop counts quick crashes, clears stale locks, and
  after four in a row sets the saved session aside and starts clean.
  (`src/session/browser`)

### 7. Tab limit vs. session restore and "Sign in with Google"
- Closing tabs as the browser restores them would lose people's tabs, so the
  first 10 seconds after start are left alone and only *new* tabs are
  limited. A tab a page opens for itself (a login or payment step) gets one
  extra slot, or signing in would be impossible at the limit.
  (`src/firefox/tablimit/background.js`)

### 8. The laptop's RAM is less than the sticker says
- `MemTotal` reports less than the installed RAM (firmware and integrated
  graphics take a share: a 2 GB laptop shows ~1.8 GB). Thresholds such as
  "under 3000 MB = low tier" sit *between* common sizes so a machine never
  lands in the wrong tier. (`src/system/tune`)

### 9. Bluetooth headphones connected but silent (v1.2)
- **Cause:** I install packages without "Recommends" to stay small, and
  PipeWire's Bluetooth support (`libspa-0.2-bluetooth`) is only a
  recommendation. Pairing worked; audio had nowhere to go.
- **Fix:** name the package explicitly. Lesson: with `--no-install-recommends`,
  check each feature end to end, not just that its service starts.
  (`build/config.sh`, `PKGS_AUDIO`)

### 10. Keyboards and phones could not pair (v1.2)
- **Cause:** keyboards ask you to type a code; phones ask to confirm one. The
  pairing code read `bluetoothctl`'s output **line by line**, but its
  questions are prompts *without* a line ending, so the program waited forever.
- **Fix:** read raw chunks, recognise "Confirm passkey", "Passkey: N" and
  "Enter PIN code", answer them, and show the code in the Bluetooth menu.
  Tested against a fake `bluetoothctl` script that plays each device type.
  (`src/panel/system.py`, `bt_pair`)

### 11. The screen could not turn off without cutting into films (v1.2)
- Screen blanking had been switched off entirely, because blanking in the
  middle of a video is worse than a battery drain.
- Looking inside Firefox (`strings libxul.so`) showed it **loads
  `libXss.so.1` at runtime** to hold the screen on while video plays, and that
  library was not installed. With `libxss1` added, the screen turns off after
  10 idle minutes and never during a video.
  (`build/config.sh`, `src/session/onlybrowseros-session`)

### 12. Real laptops hide their disk (v1.2)
- Many Dell/HP/Lenovo laptops ship with storage in "RAID / Intel RST" mode,
  which Linux cannot see, so the installer said "no disk". It now detects an
  Intel RAID controller (PCI class `0x0104`) and explains the one firmware
  setting to change. (`src/installer/installer.py`, `raid_controller`)

### 13. Measuring memory honestly (v1.2)
- In a software-emulated VM, the same image measured ±30 MB apart between
  runs, too noisy to judge a setting. I built a bench that runs the image's
  own Firefox natively (overlay on the build folder, virtual X display), asks
  Firefox itself to free memory before measuring, and lists what each process
  holds. Repeat runs then agree within 1 MB, and it immediately showed a 35 MB
  Firefox process holding no page at all. Details in `08-memory.md`.

## What I would do differently

- Write the measurement bench on day one: several memory settings I had
  chosen by reasoning turned out to make no difference once measured.
- Test on real hardware earlier; QEMU proves the logic, not the drivers.
