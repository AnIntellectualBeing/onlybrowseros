#!/usr/bin/env bash
# OnlyBrowserOS image configuration. Sourced by build-iso.sh.
# Override any value from the environment: OBOS_SUITE=trixie ./build-iso.sh

# ---------------------------------------------------------------- identity
OBOS_NAME="${OBOS_NAME:-OnlyBrowserOS}"
OBOS_ID="${OBOS_ID:-onlybrowseros}"           # lowercase, used for paths and file names
OBOS_VERSION="${OBOS_VERSION:-1.0}"
OBOS_HOSTNAME="${OBOS_HOSTNAME:-onlybrowseros}"
OBOS_USER="${OBOS_USER:-user}"                # live account; the installer renames it
OBOS_PASSWORD="${OBOS_PASSWORD:-live}"        # live session only; the installer asks for a real one
OBOS_VOLID="${OBOS_VOLID:-ONLYBROWSEROS}"     # ISO9660 volume label (uppercase, <= 32 chars)

# ---------------------------------------------------------------- updates
# OnlyBrowserOS's own updates: a signed package repository on GitHub Pages.
# build/release.sh publishes to OBOS_UPDATE_REPO; computers read OBOS_UPDATE_URL
# daily. Change both when the project moves to its own website.
OBOS_UPDATE_REPO="${OBOS_UPDATE_REPO:-AnIntellectualBeing/onlybrowseros-updates}"
OBOS_UPDATE_URL="${OBOS_UPDATE_URL:-https://anintellectualbeing.github.io/onlybrowseros-updates}"

# ------------------------------------------------------------------- base
# Debian rather than Alpine: Widevine (Netflix, Spotify) and reliable WebRTC
# need glibc. Debian rather than Ubuntu: Ubuntu ships its browsers as snaps,
# which do not install into a debootstrap chroot.
OBOS_SUITE="${OBOS_SUITE:-trixie}"
OBOS_MIRROR="${OBOS_MIRROR:-http://deb.debian.org/debian}"
OBOS_SECURITY_MIRROR="${OBOS_SECURITY_MIRROR:-http://security.debian.org/debian-security}"
OBOS_ARCH="${OBOS_ARCH:-amd64}"
OBOS_COMPONENTS="${OBOS_COMPONENTS:-main contrib non-free non-free-firmware}"

# --------------------------------------------------------------- squashfs
# zstd over xz: slightly larger, but several times faster to decompress,
# which is what an old laptop with a slow disk actually feels.
OBOS_COMPRESSION="${OBOS_COMPRESSION:-zstd}"
OBOS_COMPRESSION_LEVEL="${OBOS_COMPRESSION_LEVEL:-19}"

# ------------------------------------------------------------------ paths
OBOS_WORK="${OBOS_WORK:-}"        # defaults to build/work
OBOS_OUTPUT="${OBOS_OUTPUT:-}"    # defaults to build/out/onlybrowseros-<version>-<arch>.iso

# ------------------------------------------------------------- packages --
# Every package in these sets must exist; a missing one stops the build
# before anything is installed.
PKGS_CORE="
  linux-image-amd64
  systemd-sysv systemd-timesyncd libpam-systemd dbus dbus-user-session udev
  live-boot live-boot-initramfs-tools initramfs-tools
  locales tzdata keyboard-configuration console-setup
  sudo polkitd ca-certificates
  procps psmisc coreutils util-linux less nano file
  iproute2 iputils-ping curl
"

PKGS_NETWORK="
  network-manager wpasupplicant iw rfkill wireless-regdb
  bluez
"

PKGS_GRAPHICS="
  xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-video-all
  xinit x11-xserver-utils x11-xkb-utils openbox
  fonts-dejavu-core fonts-liberation2 fonts-noto-core fonts-noto-color-emoji
"

# libavcodec is added by the build (its package name carries the soversion).
# Without it Firefox cannot play H.264/AAC, which half the web's video uses.
PKGS_BROWSER="
  firefox-esr libpci3
"

PKGS_AUDIO="
  pipewire pipewire-pulse pipewire-alsa wireplumber
  pulseaudio-utils alsa-ucm-conf
"

# The taskbar and the installer are Python + GTK 3.
PKGS_SHELL="
  python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0
  brightnessctl
"

# Printing from the browser. CUPS finds network printers and modern USB
# printers by itself (driverless IPP Everywhere / AirPrint), so there are no
# drivers or printer setup screens. It starts only when something is printed.
PKGS_PRINTING="
  cups cups-client cups-filters ipp-usb avahi-daemon libnss-mdns
"

# Keeps a 1 GB laptop usable: compressed swap in RAM, and a watchdog that closes
# the heaviest tab before the kernel freezes the whole machine.
PKGS_MEMORY="
  systemd-zram-generator earlyoom
"

# The installer runs inside the live system, so its tools ship in the image.
PKGS_INSTALLER="
  parted gdisk dosfstools e2fsprogs rsync
  grub-common grub2-common grub-pc-bin grub-efi-amd64-bin
  efibootmgr
  shim-signed shim-helpers-amd64-signed grub-efi-amd64-signed
"

PKGS_EXTRA="
  unattended-upgrades xdg-utils
"

# ------------------------------------------------ best-effort packages --
# A failure here is logged and the build continues.
PKGS_FIRMWARE="
  firmware-linux-free firmware-misc-nonfree
  firmware-iwlwifi firmware-realtek firmware-atheros firmware-brcm80211
  firmware-libertas firmware-ti-connectivity firmware-sof-signed
  firmware-amd-graphics bluez-firmware
  intel-microcode amd64-microcode
  i965-va-driver intel-media-va-driver mesa-va-drivers
"

PKGS_VM="
  spice-vdagent
"

# Secure Boot works without switching it off: the USB stick and installed disks
# start Microsoft-signed shim, then Debian's signed GRUB and kernel (the signed
# packages are in PKGS_INSTALLER). Nothing extra here.
PKGS_SECUREBOOT=""
