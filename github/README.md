# OnlyBrowserOS

An operating system for old laptops that starts straight into the internet.
Turn the computer on and it opens Firefox, full screen, with a small taskbar
along the bottom. Nothing else to learn.

- Runs on laptops with **1 GB of RAM or more** and a **64-bit** processor
- Tries from a USB stick, then **installs to the disk** from a welcome screen and
  three steps (disk, account, install); keyboard, tab limit and similar settings
  wait under "Advanced options"
- A light, friendly look throughout: a painted mountain-lake landscape, white
  cards and one blue accent (see `refeence_images/` one folder up)
- A start page on every new tab: a search box that also takes website addresses,
  and big website buttons; "Add site" adds your own, × removes one
- Closing the browser shows a home screen with an "Open the browser" button
  instead of leaving a blank screen; crashes restart the browser by themselves
- Taskbar: Wi-Fi, network cable (LAN), Bluetooth, sound and microphone, screen
  brightness, battery, clock, memory use, power
- **How powerful is this computer?** Low-end PC (up to 2 tabs, 1 on a 1 GB
  laptop), Mid-range PC (4) or High-end PC (8). The level that fits the memory is
  recommended. Chosen in the installer, changed later in Settings, where it
  applies at once
- **Settings** in one place, inside the browser: how powerful the computer is,
  text size, time zone, keyboard layout and password. Opened from "Open Settings"
  under the OnlyBrowserOS name on the taskbar, the OnlyBrowserOS button next to
  the address bar, or by typing *settings* on the start page. The power button
  holds only Sleep, Restart and Shut down
- **Downloads only of files the browser can open:** PDFs, pictures, videos,
  music and plain text. Installers, archives and office documents are stopped as
  they start, with a message saying why
- **A Downloads page** (the first tile on the start page, or type *downloads*):
  open or delete what you saved, and open PDFs, pictures, videos, music and text
  from a plugged-in USB stick
- **No file system to get lost in:** downloads save straight to Downloads; the
  browser opens local files only from Downloads and USB sticks; upload and save
  dialogs offer just those two places
- **Only the browser window:** no add-ons, private windows, developer tools or
  Firefox's own settings menu; closing the last tab leaves the start page open;
  no switching to text consoles
- **Printing** to Wi-Fi and modern USB printers without drivers or set-up
  (driverless IPP Everywhere / AirPrint); the print service starts only when
  something is printed
- **Secure Boot can stay on** (Microsoft-signed shim, Debian-signed GRUB and kernel)
- **Battery warnings:** a message at 10%; at 5% a 60-second countdown to a clean
  shutdown so tabs are saved (can be put off once), at 3% without; plugging in
  the charger cancels it
- Leaving the USB stick in after installing is harmless: its boot menu starts the
  installed system first
- Video calls (camera, microphone, screen sharing), YouTube, Netflix and Spotify
- Security updates install automatically

## How it is put together

| Part | What it is | Where |
|---|---|---|
| Base | Debian 13 "trixie", cut down | `build/config.sh` |
| Browser | Firefox ESR, tuned for low memory at every boot | `src/system/tune` |
| Tab limit and settings | The OnlyBrowserOS Firefox extension, installed by policy: the tab limit, the settings page and its toolbar button. The settings page saves through a native-messaging helper; levels live in `src/shared/levels.py` | `src/firefox/tablimit/`, `src/system/settings-host` |
| Look | Shared light colours, widget styles, the logo and the wordmark for every screen | `src/shared/theme.py` |
| Landscape | Vector mountain lake behind the start page and home screen, drawn from one description (cairo and SVG) | `src/shared/landscape.py` |
| Taskbar | Python + GTK 3, ~30 MB | `src/panel/` |
| Home screen | Shown after the browser is closed on purpose | `src/home/` |
| Start page | One local HTML file, the landscape added by the build; new tabs via Firefox autoconfig, home page via policy | `src/start/`, `src/firefox/` |
| Installer | Python + GTK 3 screens, and a root helper that does the disk work | `src/installer/` |
| Session | Auto-login → X → openbox → taskbar + Firefox | `src/session/`, `build/overlay/` |
| Memory safety | zram (compressed RAM swap) and earlyoom (closes the heaviest tab before the laptop freezes) | `build/overlay/etc/` |

The old web-page shell from the WebOS prototype is kept in `legacy/` for
reference; the build does not use it.

## Build the ISO

On any Debian or Ubuntu machine (a VM is fine) with 12 GB free:

```sh
cd build
sudo ./build-iso.sh
```

Nothing is compiled. The build downloads ready-made Debian packages into a
folder, adds OnlyBrowserOS, and packs everything into one bootable file:
`build/out/onlybrowseros-1.0-amd64.iso` (about 800 MB). The first build takes
30–60 minutes, mostly downloading. After changing anything in `src/` or
`build/overlay/`, rebuild in a couple of minutes with:

```sh
sudo ./build-iso.sh --from overlay
```

For quick test builds, `sudo OBOS_COMPRESSION_LEVEL=3 ./build-iso.sh --from overlay`
compresses less and finishes faster.

## Test it

**VirtualBox:** create a VM of type *Linux / Debian (64-bit)*, give it 1–2 GB of
RAM and a 20 GB disk, attach the ISO and start it. Choose **Install
OnlyBrowserOS** on the taskbar to try the installer.

**QEMU, automatically** (from `build/`):

```sh
./test-iso.sh --auto-live               # boot the ISO, check the desktop, test the tab limit
./test-iso.sh --auto-install            # install onto an empty disk, boot it, same checks
./test-iso.sh --auto-install --uefi     # the same with UEFI firmware
./test-iso.sh --auto-install --secureboot  # UEFI with Secure Boot enforced (Microsoft keys)
./test-iso.sh --auto-live --ram 1024    # how a 1 GB laptop fares
```

Each run prints a health report (memory per part, services, tab-limit result)
and saves a screenshot in `build/test/`.

## Put it on a USB stick

- **Windows:** [Rufus](https://rufus.ie) (choose *DD image mode* when asked) or
  [balenaEtcher](https://etcher.balena.io).
- **Linux:** `sudo dd if=build/out/onlybrowseros-1.0-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync`
  (replace `sdX` with the USB stick; everything on it is erased).

Then start the laptop from the USB stick (usually F12, F9 or Esc at power-on).
Secure Boot can stay on: the stick and installed computers start through
Microsoft-signed shim and Debian's signed GRUB and kernel.

## Updates

**Debian security fixes** (Firefox included) install by themselves every day;
nothing to do.

**OnlyBrowserOS's own updates** (taskbar, installer, settings, start page,
system configuration) are one Debian package, `onlybrowseros`, published to a
signed package repository on GitHub Pages. Every computer checks it daily and
installs new versions silently, the same way as security fixes.

One-time setup:

1. Create the signing key, as yourself (not sudo), and back it up as the script
   explains. Losing it means no more updates for computers already sold;
   leaking it lets someone else push to all of them.
   ```sh
   cd build && ./make-signing-key.sh you@example.com
   ```
2. Create the public GitHub repository `onlybrowseros-updates` and turn on
   GitHub Pages for it (Settings → Pages → Deploy from branch → `main`, `/ (root)`):
   ```sh
   gh repo create AnIntellectualBeing/onlybrowseros-updates --public --add-readme
   ```
3. Build the ISO (`sudo ./build-iso.sh --from overlay`). It now carries the
   public key and the update address; ISOs built before step 1 get security
   fixes only.

Each release:

```sh
cd build && ./release.sh            # or --no-push to look before publishing
```

The address and repository are `OBOS_UPDATE_URL` and `OBOS_UPDATE_REPO` in
`build/config.sh`; change them when the project moves to its own website.
Updated files take effect at the next browser start or restart.

## Known limits

- 64-bit processors only; no modern browser supports 32-bit any more.
- Work or school Wi-Fi that needs a user name (802.1X) cannot be joined yet.
- Bluetooth devices that ask for a pairing code (some keyboards) cannot be paired
  yet; headphones, speakers and mice work.
- Chinese, Japanese and Korean fonts are not included, to keep the image small.
