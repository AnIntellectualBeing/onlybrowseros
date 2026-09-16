# How It Works — Technical Architecture

This is the file to read before an interview. It explains the whole system,
piece by piece, in the order the computer actually touches them: power on →
kernel → login → browser on screen.

## The base: Debian, not "from scratch"

OnlyBrowserOS is **not** a Linux distro built from source (that would be a
Linux-From-Scratch project, months of work). It's **Debian 13 "trixie"**,
installed via `debootstrap` into a folder (a "chroot"), with unwanted packages
left out and OnlyBrowserOS's own files added on top. This is the same
technique Ubuntu, Kali, and most "custom Linux distro" projects use.

Why Debian specifically, over Alpine or Ubuntu:
- **Alpine** uses musl libc instead of glibc, and Widevine (Netflix, Spotify
  DRM) and some WebRTC codecs need glibc.
- **Ubuntu** ships Firefox and other browsers as Snap packages, which don't
  install cleanly into a chroot the way `.deb` packages do.
- **Debian** avoids both problems and has the most stable, longest-supported
  package set of the three.

## Boot sequence, step by step

1. **GRUB** (BIOS or UEFI) loads the Linux kernel and initramfs from the
   squashfs image (or, once installed, from the hard disk).
2. **systemd** starts as PID 1, brings up the usual services (NetworkManager,
   D-Bus, PipeWire for audio, etc.).
3. **Auto-login** on tty1 — no password prompt (an override for
   `getty@tty1.service`, written into `/etc/systemd/system/getty@tty1.service.d/`)
   — logs straight into the shell.
4. **`.bash_profile`** (from `build/overlay/etc/skel/.bash_profile`) detects
   it's on tty1 with no `$DISPLAY`, and runs `startx onlybrowseros-session`.
5. **`onlybrowseros-session`** (`src/session/onlybrowseros-session`) sets up
   the X server basics (screen blanking off, cursor, keyboard layout, text
   size via `xrdb`), then runs **openbox** as the window manager, pointed at
   a custom config (`build/overlay/etc/onlybrowseros/openbox/rc.xml`) and an
   autostart script.
6. **`autostart`** (`src/session/autostart`) launches two things in a
   restart-loop:
   - the **taskbar** (`src/panel/panel.py`)
   - either the **installer's welcome screen** (only on the live USB, when
     booted with `boot=live`) or straight into the **browser** script.
7. **`browser`** (`src/session/browser`) is a shell loop that runs
   `firefox-esr` and watches its exit code:
   - exit 0 or 143 (closed on purpose / asked to stop) → show the **home
     screen** (`src/home/home.py`) with an "Open the browser" button.
   - any other exit code (a crash) → restart Firefox, with escalating
     backoff and, after repeated crashes, clearing the corrupted session
     first.
8. **openbox's window rules** (in `rc.xml`) force Firefox, the installer, and
   the home screen to be borderless and maximized, and reserve 44px at the
   bottom of the screen for the taskbar (so nothing ever overlaps it).

## The taskbar (`src/panel/panel.py`, ~1500 lines)

A GTK 3 window docked to the bottom of the screen. Built with Python + PyGObject
rather than a heavier desktop environment's panel, to keep memory use low
(~30-60MB). Structure:

- **`Panel`** — the bar itself: logo/name button (left), install button on
  the live USB, then a tray of icons (network, Bluetooth, sound, brightness,
  battery, clock, power) on the right.
- **`Popup`** — a base class for the small windows that appear above each
  tray icon when clicked (undecorated, auto-positioned, closes on click-away
  or Escape).
- Each icon has its own `Popup` subclass: `NetworkMenu`, `BluetoothMenu`,
  `SoundMenu`, `BrightnessMenu`, `BatteryMenu`, `ClockMenu`, `SystemMenu`
  (the logo popup — memory usage + "Open Settings"), `PowerMenu`
  (sleep/restart/shut down).
- **`BatteryAlert`** — a separate always-on-top window that appears at 10%
  battery (a warning) and again at 5%/3% (a countdown to a clean shutdown, so
  the browser gets a chance to save open tabs before the battery dies).
- All the actual system calls (reading Wi-Fi status, connecting to a network,
  setting volume, reading battery state) live in **`src/panel/system.py`** —
  a thin wrapper around command-line tools (`nmcli`, `bluetoothctl`, `pactl`,
  `brightnessctl`, `/sys/class/power_supply`), always run on a background
  thread so the UI never freezes waiting on them.
- **`src/panel/icons.py`** draws every icon by hand with Cairo (vector paths
  on a 24-unit grid) instead of loading an icon theme or image files — this
  keeps the whole taskbar to a handful of Python files with zero image
  assets, and icons stay crisp at any size/DPI.

## The installer (`src/installer/installer.py`, ~1100 lines)

A GTK 3 wizard, structured as a `Gtk.Stack` of named pages with Next/Back
buttons and a step indicator:

**welcome → disk → account → computer (power level) → confirm → progress → done/failed**

- Runs machine checks up front (memory, battery/AC status, available disks)
  and shows them as friendly pass/warn indicators before the user commits to
  anything.
- The actual disk work (partitioning, formatting, copying files, installing
  the bootloader) is **never done by the GTK process itself** — it shells out
  to a separate root-only script:

### `src/installer/install-helper` (~580 lines)

This is the security-sensitive half of the installer, and it's worth
understanding well for an interview:

- Runs as root via a **narrowly-scoped sudoers rule** — the desktop user can
  run *only this one script*, and only while running from the live USB (a
  separate sudoers file that gets deleted once installed, so an installed
  computer can never re-partition its own disk from user-space).
- Reads all its options as JSON on stdin (never as free-form shell
  arguments) and validates every field with a regex before touching disk —
  refuses reserved usernames, invalid hostnames, disks that are too small or
  already in use, etc.
- Emits machine-readable progress lines (`##{"phase": ..., "percent": ...}`)
  that the GTK installer parses to drive its progress bar.
- Sequence: wipe partition table → partition (GPT+ESP for UEFI, MBR for
  BIOS) → format → `rsync` the live filesystem to the new partition →
  create a swap file → write `/etc/fstab` → rename the live user account to
  the chosen username → set the password → install the bootloader (see
  below) → clean up.

## The browser lockdown (Firefox policies + a custom extension)

This is the part that turns "a Linux desktop with Firefox on it" into "an
appliance that can only browse."

### `src/system/tune` — written fresh at every boot

A Python script (systemd service `onlybrowseros-tune.service`) that runs
before login and writes two files based on how much RAM the machine has:

1. **`/usr/lib/firefox-esr/distribution/policies.json`** — Firefox's
   enterprise policy file. This is what actually disables private browsing,
   developer tools, add-on installation, Firefox's own settings pages, sets
   the download directory, and force-installs OnlyBrowserOS's extension.
2. **`/etc/firefox-esr/onlybrowseros.js`** — `pref()` lines tuned to the
   machine's memory tier (low/medium/high): fewer content processes on a
   1GB machine, smaller caches, disabled prefetching, etc.

Doing this at every boot (not once at install time) means a laptop that gets
a RAM upgrade automatically gets better settings on its next start.

### The browser extension (`src/firefox/tablimit/`)

A WebExtension, force-installed and un-removable via policy, that does
everything Firefox's policy system alone can't:

- **Tab limit enforcement** (`background.js`) — reads the limit from managed
  storage, and closes any new tab past the limit (with a grace period at
  startup so session-restore isn't fought, and one extra slot when a page
  opens a tab for itself, like a "Sign in with Google" popup).
- **One window only** — merges any second browser window's tabs back into
  the first, since the taskbar has no window switcher.
- **Download filtering** — checks every download's extension/MIME type
  against an allow-list (PDF, images, video, audio, plain text) and cancels
  anything else, with a notification explaining why.
- **The Settings page** (`settings.html`/`.js`) — a full page, in the
  browser, that reads and writes system settings by talking to a **native
  messaging host**.
- **The Downloads page** (`files-page.js` + `src/start/downloads.html`) —
  lists downloaded files and files on any plugged-in USB stick that the
  browser can open.

### Native messaging: crossing from the browser into the OS

Firefox extensions can't touch the filesystem or run system commands
directly — Mozilla's sandbox forbids it. The bridge is **native messaging**:
a manifest file (`src/firefox/native-host.json`, installed to
`/usr/lib/mozilla/native-messaging-hosts/`) tells Firefox it may spawn one
specific local program and exchange length-prefixed JSON messages with it
over stdin/stdout.

That program is **`src/system/settings-host`** — reads a request like
`{"cmd": "set-tabs", "value": "4"}`, validates it, and either changes things
directly (text size, via `xrdb`) or shells out to `sudo` for anything that
needs root (`src/system/set-tab-limit`, `src/system/system-setting` for time
zone/keyboard). Password changes go through `sudo chpasswd`, which itself
demands the *current* password — so getting into Settings doesn't require a
password, but changing the account password still does.

## Secure Boot

Real laptops made in roughly the last decade ship with Secure Boot **on** by
default, and most non-technical users will never find (or want to touch) the
firmware setting to turn it off. Getting a live USB to boot on such a machine
without asking the user to change anything requires the whole boot chain to
be **cryptographically signed** by a key Microsoft's Secure Boot database
already trusts.

The chain: **firmware → shim (Microsoft-signed) → GRUB (Debian-signed) →
Linux kernel (Debian-signed)**. OnlyBrowserOS doesn't sign anything itself —
it uses Debian's `shim-signed` and `grub-efi-amd64-signed` packages, which
are already trusted, and assembles a hybrid ISO by hand (see
[`03-how-it-was-built.md`](03-how-it-was-built.md)) instead of using the
default `grub-mkrescue` tool, because that tool bakes in an *unsigned* GRUB
binary.

## Updates

Two independent update channels:

1. **Debian's own security updates** (including Firefox) — `unattended-upgrades`
   is already configured and enabled; nothing custom here.
2. **OnlyBrowserOS's own code** (taskbar, installer, settings, etc.) —
   packaged as a single `.deb` and published to a **self-hosted signed apt
   repository** on GitHub Pages. See
   [`03-how-it-was-built.md`](03-how-it-was-built.md) for the publishing
   pipeline.

## File map (where to find things)

```
src/
  panel/       the taskbar (panel.py, system.py, icons.py)
  installer/   the GTK installer + the root install-helper
  home/        the "browser was closed" screen
  session/     boot-to-desktop glue scripts (shell)
  shared/      code shared across the GTK apps: theme.py (colors/CSS),
               landscape.py (the painted background, shared by start page
               and home screen), levels.py (the Low/Mid/High-end PC logic),
               keyboards.py
  system/      root-level helper scripts: tune, settings-host,
               system-setting, set-tab-limit, usb-mount, autotest
  firefox/     Firefox policy glue (autoconfig.js, onlybrowseros.cfg,
               native-host.json) + the tablimit/ extension
  start/       the new-tab start page and the Downloads page (plain HTML/CSS/JS)

build/
  config.sh          all the tunable settings: package lists, version, etc.
  build-iso.sh        the main build script (see next doc)
  make-package.sh     packages src/ + build/overlay/ into one .deb
  make-signing-key.sh one-time GPG key setup for update signing
  release.sh          publishes a new .deb to the update repo
  test-iso.sh         QEMU-based automated testing
  overlay/            static system config files copied verbatim into the image
                       (sudoers rules, polkit rules, systemd units, etc.)
```
