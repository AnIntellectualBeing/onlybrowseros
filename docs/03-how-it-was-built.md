# How It Was Built — Build System, Testing, Updates

## The ISO build (`build/build-iso.sh`)

A staged bash script (`deps → bootstrap → apt → overlay → configure →
cleanup → squashfs → iso`). Each stage is stamped once it succeeds, so a
re-run skips finished stages — and `--from overlay` lets you rebuild in
~2 minutes after only touching `src/`, instead of redoing the whole
~30-minute Debian bootstrap.

1. **`deps`** — checks the host has `debootstrap`, `squashfs-tools`,
   `xorriso`, etc., and at least 12GB free.
2. **`bootstrap`** — `debootstrap` downloads a minimal Debian trixie system
   into `build/work/chroot/` (~100MB download).
3. **`apt`** — installs every package OnlyBrowserOS needs, grouped by
   purpose in `build/config.sh` (`PKGS_CORE`, `PKGS_NETWORK`,
   `PKGS_GRAPHICS`, `PKGS_BROWSER`, `PKGS_AUDIO`, `PKGS_SHELL`,
   `PKGS_PRINTING`, `PKGS_MEMORY`, `PKGS_INSTALLER`, `PKGS_EXTRA`). Every
   package name is checked to exist *before* installing anything, so a typo
   fails fast instead of an hour into the build. Best-effort groups
   (`PKGS_FIRMWARE`, `PKGS_VM`) are allowed to fail package-by-package,
   since not every laptop's Wi-Fi/graphics firmware exists for every
   architecture.
4. **`overlay`** — this is where OnlyBrowserOS actually gets installed. It works by **building the real `.deb` package
   (`make-package.sh`) and installing it with `dpkg -i` inside the chroot** —
   the same package that gets published as an update later, so there's only
   one definition of "what OnlyBrowserOS consists of," not two.
5. **`configure`** — locale, the live user account, auto-login, enabling
   systemd services, rebuilding the initramfs.
6. **`cleanup`** — strips apt caches, logs, machine-id, anything that
   shouldn't be identical across every installed copy.
7. **`squashfs`** — compresses the whole chroot into one file
   (`filesystem.squashfs`) with `zstd` (chosen over `xz`: bigger file, but
   several times faster to *decompress*, which matters more on an old
   laptop's slow disk than the extra download size).
8. **`iso`** — assembles the final bootable ISO (see below — this is
   hand-built, not the default `grub-mkrescue`).

### Why the ISO assembly is hand-rolled instead of `grub-mkrescue`

`grub-mkrescue` is the normal one-command way to build a bootable GRUB ISO,
but it bakes in an **unsigned** GRUB EFI binary. That works fine with Secure
Boot off, but a Secure Boot-enforcing firmware refuses to run it. To support
Secure Boot, the build instead:

1. Builds a **BIOS boot image** with `grub-mkimage` (an El Torito core
   image, using the plain `i386-pc` modules — BIOS has no Secure Boot to
   satisfy).
2. Builds a **UEFI boot image** as a small FAT filesystem (`efi.img`)
   containing three **already-Microsoft/Debian-signed** binaries pulled from
   the `shim-signed`, `shim-helpers-amd64-signed`, and
   `grub-efi-amd64-signed` packages:
   `EFI/BOOT/BOOTX64.EFI` (shim), `EFI/BOOT/grubx64.efi` (signed GRUB),
   `EFI/BOOT/mmx64.efi` (shim's "MOK manager"), plus a tiny
   `EFI/debian/grub.cfg` that just points GRUB at the real config on the
   ISO.
3. Runs `xorriso -as mkisofs` directly with both boot images attached (one
   as the El Torito BIOS entry, one as the "alternative" EFI entry) and a
   protective MBR + GPT, producing one file that boots on BIOS, UEFI, and
   UEFI with Secure Boot enforced — from a burned disc or a `dd`'d USB
   stick.

The installer's `install-helper` mirrors this for the installed disk: it
installs GRUB with `--uefi-secure-boot` (which pulls in the signed shim
automatically via Debian's `grub-install` wrapper) and registers a firmware
boot menu entry via `efibootmgr`.

## Packaging (`build/make-package.sh`)

Builds one Debian package (`onlybrowseros_<version>_all.deb`) containing
*everything* OnlyBrowserOS adds on top of stock Debian: every Python file
under `src/`, the Firefox policy glue, the extension (zipped into a
`.xpi`), and every file under `build/overlay/` (systemd units, sudoers
rules, polkit rules, udev rules) — **except** the live-USB-only sudoers file
that grants disk-erasing permission, which must never ship in an update to
an already-installed computer.

The version string is `<base version>.<UTC build timestamp>` (e.g.
`1.0.202609160841`), so every build is provably newer than the last and apt
always offers the update.

This same package is what gets installed into the ISO's chroot *and* what
gets published as an update — one source of truth, no drift between "what
ships on day one" and "what an update installs."

## Testing (`build/test-iso.sh` + `src/system/autotest`)

Fully automated, no human clicking through a VM:

- **`test-iso.sh`** drives QEMU headlessly (`-display none`, serial console
  redirected to a log file), with modes for `--auto-live` (boot the USB
  image and run checks) and `--auto-install` (install onto a blank virtual
  disk, then boot *that* and run checks). Flags: `--uefi`, `--secureboot`
  (boots with Microsoft's Secure Boot keys pre-enrolled in OVMF firmware —
  and for that mode, since a real kernel/initrd can't be handed to QEMU
  directly without bypassing the firmware, it patches a copy of the ISO's
  GRUB menu to add the test's kernel arguments and boots the whole ISO
  through the real signed boot chain), and `--ram` to simulate a 1GB
  laptop.
- **`src/system/autotest`** is baked into the image but only runs when the
  kernel command line carries `obos.autotest=install` or
  `obos.autotest=report` (never on a real user's machine). It checks, among
  other things:
  - the tab limit actually closes excess tabs
  - the download filter keeps a PDF and blocks a `.zip`
  - the settings native-messaging bridge can read/change tab level, time
    zone, and keyboard, and revert them
  - "Open Settings" from the taskbar opens the right page even past the tab
    limit
  - CUPS (printing) is idle until needed
  - closing the browser shows the home screen
  - Secure Boot / kernel lockdown status, for diagnosing the boot chain
- Each run prints a memory report (`Pss` per process group) and saves a
  screenshot, so a memory regression or a broken UI is visible without
  reproducing the whole test by hand.

## Publishing updates (`build/make-signing-key.sh` + `build/release.sh`)

1. **One-time:** `make-signing-key.sh you@email` generates a GPG signing key
   (asks for a passphrase) and prints instructions to back up the *private*
   key offline — losing it means computers already in the field can never
   receive another update; leaking it means anyone can push code to every
   OnlyBrowserOS computer that trusts it.
2. **Each release:** `release.sh` builds the package, drops it into a local
   clone of a GitHub repo (served as a static site via GitHub Pages), runs
   `apt-ftparchive` to generate the package index (`Packages`, `Release`),
   signs it (`InRelease`, `Release.gpg`), and pushes.
3. Every OnlyBrowserOS computer has that repo's URL and public key baked in
   at build time (`/etc/apt/sources.list.d/onlybrowseros.list`), and
   `unattended-upgrades` is configured to treat it exactly like a Debian
   security repo — so an update Just Happens, with no UI, the same way a
   Firefox security patch does.

**Status: built and tested with a throwaway key, but not yet activated with
the real release key** — see [`05-whats-left.md`](05-whats-left.md).
