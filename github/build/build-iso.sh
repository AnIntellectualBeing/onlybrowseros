#!/usr/bin/env bash
#
# Build a bootable, installable OnlyBrowserOS ISO.
#
#   sudo ./build-iso.sh                  full build
#   sudo ./build-iso.sh --from overlay   re-run from a stage (keeps the chroot)
#   sudo ./build-iso.sh --to apt         stop after a stage
#   sudo ./build-iso.sh --clean          throw the work tree away first
#   sudo ./build-iso.sh --list-stages
#
# Nothing here compiles code. Debian ships every program ready-made; the build
# downloads them into a folder, adds OnlyBrowserOS, and packs the result into
# one bootable file. Stages are stamped, so a re-run skips what already
# succeeded. Editing anything under src/ only needs `--from overlay`.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
SRC="$REPO/src"

# shellcheck source=config.sh
source "$HERE/config.sh"

WORK="${OBOS_WORK:-$HERE/work}"
CHROOT="$WORK/chroot"
ISODIR="$WORK/iso"
STAMPS="$WORK/stamps"
OUT_DIR="$HERE/out"
OUTPUT="${OBOS_OUTPUT:-$OUT_DIR/${OBOS_ID}-${OBOS_VERSION}-${OBOS_ARCH}.iso}"
LIB="/usr/lib/$OBOS_ID"

STAGES=(deps bootstrap apt overlay configure cleanup squashfs iso)

# ---------------------------------------------------------------- output --

if [[ -t 1 ]]; then
  C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_D=$'\033[2m'; C_0=$'\033[0m'
else
  C_B=""; C_G=""; C_Y=""; C_R=""; C_D=""; C_0=""
fi

step()  { printf '\n%s==> [%s] %s%s\n' "$C_B$C_G" "$(date +%H:%M:%S)" "$*" "$C_0"; }
info()  { printf '    %s\n' "$*"; }
dim()   { printf '%s    %s%s\n' "$C_D" "$*" "$C_0"; }
warn()  { printf '%s  !  %s%s\n' "$C_Y" "$*" "$C_0" >&2; }
die()   { printf '\n%s  ✗  %s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }

# --------------------------------------------------------------- cleanup --

unmount_all() {
  local m
  for m in dev/pts dev sys proc run; do
    if mountpoint -q "$CHROOT/$m" 2>/dev/null; then
      umount -lf "$CHROOT/$m" 2>/dev/null || true
    fi
  done
}

on_exit() {
  local rc=$?
  unmount_all
  if (( rc != 0 )); then
    printf '\n%s  ✗  build failed (exit %d)%s\n' "$C_R" "$rc" "$C_0" >&2
    printf '    the chroot is left at %s for inspection\n' "$CHROOT" >&2
    printf '    fix, then re-run with --from <stage> to resume\n' >&2
  fi
}
trap on_exit EXIT

# ------------------------------------------------------------------ args --

FROM=""
TO=""
DO_CLEAN=0

while (( $# )); do
  case "$1" in
    --from)         FROM="${2:-}"; shift 2 ;;
    --from=*)       FROM="${1#*=}"; shift ;;
    --to)           TO="${2:-}"; shift 2 ;;
    --to=*)         TO="${1#*=}"; shift ;;
    --clean)        DO_CLEAN=1; shift ;;
    --list-stages)  printf '%s\n' "${STAGES[@]}"; exit 0 ;;
    -h|--help)      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              die "unknown option: $1" ;;
  esac
done

is_stage() { local s; for s in "${STAGES[@]}"; do [[ "$s" == "$1" ]] && return 0; done; return 1; }
[[ -z "$FROM" ]] || is_stage "$FROM" || die "unknown stage '$FROM' (see --list-stages)"
[[ -z "$TO"   ]] || is_stage "$TO"   || die "unknown stage '$TO' (see --list-stages)"

[[ $EUID -eq 0 ]] || die "this must run as root: sudo $0"

stamp_file() { echo "$STAMPS/$1"; }
have_stamp() { [[ -f "$(stamp_file "$1")" ]]; }
set_stamp()  { mkdir -p "$STAMPS"; date -Iseconds > "$(stamp_file "$1")"; }

should_run() {
  local stage="$1"
  if [[ -n "$FROM" ]]; then
    local hit=0 s
    for s in "${STAGES[@]}"; do
      [[ "$s" == "$FROM" ]] && hit=1
      [[ "$s" == "$stage" ]] && { (( hit )) && return 0 || return 1; }
    done
  fi
  have_stamp "$stage" && { dim "stage '$stage' already done, skipping"; return 1; }
  return 0
}

chr_sh() {
  chroot "$CHROOT" /usr/bin/env -i \
    HOME=/root \
    DEBIAN_FRONTEND=noninteractive \
    DEBCONF_NONINTERACTIVE_SEEN=true \
    LC_ALL=C LANGUAGE=C LANG=C \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /bin/bash -eu -o pipefail -c "$1"
}

mount_pseudo() {
  mkdir -p "$CHROOT"/{dev,proc,sys,run}
  mountpoint -q "$CHROOT/proc"    || mount -t proc  proc  "$CHROOT/proc"
  mountpoint -q "$CHROOT/sys"     || mount -t sysfs sys   "$CHROOT/sys"
  mountpoint -q "$CHROOT/dev"     || mount --bind /dev    "$CHROOT/dev"
  mountpoint -q "$CHROOT/dev/pts" || mount -t devpts devpts "$CHROOT/dev/pts"
  mountpoint -q "$CHROOT/run"     || mount -t tmpfs tmpfs  "$CHROOT/run"
}

# ============================================================== stage: deps

stage_deps() {
  step "Checking the build machine"

  . /etc/os-release 2>/dev/null || true
  info "host: ${PRETTY_NAME:-unknown}, kernel $(uname -r), $(nproc) cores"

  local need=(debootstrap squashfs-tools xorriso mtools dosfstools
              grub-pc-bin grub-efi-amd64-bin grub-common python3
              rsync ca-certificates debian-archive-keyring zstd)
  local missing=() pkg
  for pkg in "${need[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed" || missing+=("$pkg")
  done

  if (( ${#missing[@]} )); then
    info "installing build tools: ${missing[*]}"
    apt-get update -qq
    apt-get install -y --no-install-recommends "${missing[@]}"
  else
    info "all build tools present"
  fi

  # Ubuntu's debootstrap may not carry a script for the chosen Debian suite.
  # Every modern Debian release bootstraps correctly with the sid script.
  local scripts=/usr/share/debootstrap/scripts
  if [[ ! -e "$scripts/$OBOS_SUITE" ]]; then
    warn "debootstrap has no script for '$OBOS_SUITE'; linking it to sid"
    ln -sf sid "$scripts/$OBOS_SUITE"
  fi

  local avail
  avail=$(df -BG --output=avail "$HERE" | tail -1 | tr -dc '0-9')
  info "free space: ${avail}G"
  (( avail >= 12 )) || die "need at least 12 GB free to build (have ${avail}G)"

  mkdir -p "$WORK" "$OUT_DIR" "$STAMPS"
  set_stamp deps
}

# ========================================================= stage: bootstrap

stage_bootstrap() {
  step "Downloading the Debian $OBOS_SUITE base system"

  if [[ -d "$CHROOT" ]]; then
    info "removing previous chroot"
    unmount_all
    rm -rf "$CHROOT"
  fi
  mkdir -p "$CHROOT"

  info "this downloads ~100 MB"
  debootstrap \
    --arch="$OBOS_ARCH" \
    --variant=minbase \
    --components="$(echo "$OBOS_COMPONENTS" | tr ' ' ',')" \
    --include=ca-certificates,apt-utils \
    "$OBOS_SUITE" "$CHROOT" "$OBOS_MIRROR" \
    || die "debootstrap failed (check network and mirror)"

  info "base system: $(du -sh "$CHROOT" | cut -f1)"
  set_stamp bootstrap
}

# =============================================================== stage: apt

stage_apt() {
  step "Installing packages"

  # Nothing in a chroot may start a daemon.
  printf '#!/bin/sh\nexit 101\n' > "$CHROOT/usr/sbin/policy-rc.d"
  chmod +x "$CHROOT/usr/sbin/policy-rc.d"

  cp -f --remove-destination /etc/resolv.conf "$CHROOT/etc/resolv.conf"

  rm -f "$CHROOT/etc/apt/sources.list.d/debian.sources"
  cat > "$CHROOT/etc/apt/sources.list" <<EOF
deb $OBOS_MIRROR $OBOS_SUITE $OBOS_COMPONENTS
deb $OBOS_MIRROR ${OBOS_SUITE}-updates $OBOS_COMPONENTS
deb $OBOS_SECURITY_MIRROR ${OBOS_SUITE}-security $OBOS_COMPONENTS
EOF

  cat > "$CHROOT/etc/apt/apt.conf.d/99${OBOS_ID}" <<'EOF'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
EOF

  # Keep the image lean: no manual pages or documentation nobody can open.
  mkdir -p "$CHROOT/etc/dpkg/dpkg.cfg.d"
  cat > "$CHROOT/etc/dpkg/dpkg.cfg.d/99${OBOS_ID}-slim" <<'EOF'
path-exclude=/usr/share/man/*
path-exclude=/usr/share/doc/*
path-include=/usr/share/doc/*/copyright
path-exclude=/usr/share/help/*
path-exclude=/usr/share/info/*
path-exclude=/usr/share/lintian/*
EOF

  mount_pseudo

  info "updating package lists"
  chr_sh "apt-get update -qq"

  # The ffmpeg library Firefox loads for H.264/AAC carries its soversion in
  # the package name, so look it up rather than hard-coding it.
  local avcodec
  avcodec="$(chr_sh "apt-cache pkgnames libavcodec | grep -E '^libavcodec[0-9]+\$' | sort -V | tail -1")" || true
  [[ -n "$avcodec" ]] || die "no libavcodec package found; Firefox would not play most video"
  info "video codecs from $avcodec"
  PKGS_BROWSER="$PKGS_BROWSER $avcodec"

  local groups=(CORE NETWORK GRAPHICS BROWSER AUDIO SHELL PRINTING MEMORY INSTALLER EXTRA)

  # Check every required name before installing anything, so a typo or a
  # package Debian dropped is reported in one go instead of an hour in.
  local group varname missing=""
  for group in "${groups[@]}"; do
    varname="PKGS_$group"
    # shellcheck disable=SC2086
    missing+="$(chr_sh "for p in $(echo ${!varname}); do apt-cache show --no-all-versions \$p >/dev/null 2>&1 || printf '%s ' \$p; done")"
  done
  [[ -z "${missing// /}" ]] || die "these packages do not exist in Debian $OBOS_SUITE: $missing"
  info "all required packages found"

  for group in "${groups[@]}"; do
    varname="PKGS_$group"
    info "installing ${group,,} packages"
    # shellcheck disable=SC2086
    chr_sh "apt-get install -y --no-install-recommends $(echo ${!varname})" \
      || die "could not install the ${group,,} package set"
  done

  for group in FIRMWARE VM SECUREBOOT; do
    varname="PKGS_$group"
    info "installing ${group,,} packages (best effort)"
    local pkg
    for pkg in ${!varname}; do
      if chr_sh "apt-get install -y --no-install-recommends $pkg" >/dev/null 2>&1; then
        dim "  + $pkg"
      else
        warn "skipped $pkg (not available for $OBOS_SUITE)"
      fi
    done
  done

  chr_sh "command -v firefox-esr >/dev/null" || die "firefox-esr is missing from the image"

  info "installed size: $(du -sh --exclude=proc --exclude=sys --exclude=dev "$CHROOT" | cut -f1)"
  set_stamp apt
}

# =========================================================== stage: overlay

stage_overlay() {
  step "Installing OnlyBrowserOS"

  # Everything OnlyBrowserOS adds (programs, start page, browser set-up and the
  # system configuration in build/overlay) is one package: the same package
  # release.sh publishes as an update.
  local deb
  deb="$("$HERE/make-package.sh" "$WORK/package")" || die "could not build the OnlyBrowserOS package"
  cp "$deb" "$CHROOT/tmp/$OBOS_ID.deb"
  mount_pseudo
  chr_sh "dpkg -i /tmp/$OBOS_ID.deb >/dev/null" || die "could not install the OnlyBrowserOS package"
  rm -f "$CHROOT/tmp/$OBOS_ID.deb"
  ls -1t "$WORK"/package/*.deb | tail -n +4 | xargs -r rm -f --
  info "installed $(basename "$deb")"

  # Only the USB stick may erase disks. The package never carries this
  # permission, and the installer removes it from installed computers.
  install -m 0440 -o root -g root "$HERE/overlay/etc/sudoers.d/$OBOS_ID-live" "$CHROOT/etc/sudoers.d/$OBOS_ID-live"
  chr_sh "visudo -cq -f /etc/sudoers.d/$OBOS_ID && visudo -cq -f /etc/sudoers.d/$OBOS_ID-live" \
    || die "a sudoers file is invalid"

  # OnlyBrowserOS's own updates, once the signing key exists (make-signing-key.sh).
  local key="$HERE/keys/$OBOS_ID-archive.gpg"
  if [[ -f "$key" ]]; then
    install -D -m 0644 "$key" "$CHROOT/usr/share/keyrings/$OBOS_ID-archive.gpg"
    echo "deb [signed-by=/usr/share/keyrings/$OBOS_ID-archive.gpg] $OBOS_UPDATE_URL ./" \
      > "$CHROOT/etc/apt/sources.list.d/$OBOS_ID.list"
    info "updates from $OBOS_UPDATE_URL"
  else
    rm -f "$CHROOT/etc/apt/sources.list.d/$OBOS_ID.list" "$CHROOT/usr/share/keyrings/$OBOS_ID-archive.gpg"
    warn "no update signing key in build/keys: this ISO gets Debian security updates only"
  fi

  install -d -m 0755 "$CHROOT/etc/$OBOS_ID"
  cat > "$CHROOT/etc/$OBOS_ID/release" <<EOF
NAME=$OBOS_NAME
VERSION=$OBOS_VERSION
BASE=Debian $OBOS_SUITE
BUILD_DATE=$(date -u +%Y-%m-%d)
EOF
  [[ -f "$CHROOT/etc/$OBOS_ID/tabs.conf" ]] || cat > "$CHROOT/etc/$OBOS_ID/tabs.conf" <<'EOF'
# How many tabs the browser may have open at once.
# auto = decided from the amount of RAM at every boot; or a number from 1 to 20.
TAB_LIMIT=auto
EOF

  # /etc/os-release is a link to /usr/lib/os-release on Debian; write the
  # real file and keep the link.
  rm -f "$CHROOT/etc/os-release" "$CHROOT/usr/lib/os-release"
  cat > "$CHROOT/usr/lib/os-release" <<EOF
PRETTY_NAME="$OBOS_NAME $OBOS_VERSION"
NAME="$OBOS_NAME"
VERSION_ID="$OBOS_VERSION"
VERSION="$OBOS_VERSION"
ID=$OBOS_ID
ID_LIKE=debian
VERSION_CODENAME=$OBOS_SUITE
EOF
  ln -s ../usr/lib/os-release "$CHROOT/etc/os-release"

  printf '%s %s \\n \\l\n\n' "$OBOS_NAME" "$OBOS_VERSION" > "$CHROOT/etc/issue"

  echo "$OBOS_HOSTNAME" > "$CHROOT/etc/hostname"
  cat > "$CHROOT/etc/hosts" <<EOF
127.0.0.1	localhost
127.0.1.1	$OBOS_HOSTNAME
::1		localhost ip6-localhost ip6-loopback
ff02::1		ip6-allnodes
ff02::2		ip6-allrouters
EOF

  set_stamp overlay
}

# ========================================================= stage: configure

stage_configure() {
  step "Configuring the system"

  mount_pseudo

  chr_sh "sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen >/dev/null"
  echo 'LANG=en_US.UTF-8' > "$CHROOT/etc/default/locale"
  info "locale: en_US.UTF-8"

  # The live account. The installer renames it, which carries the session
  # setup onto the installed system. Privileges are granted to the obos group
  # rather than to the name, so they survive that rename.
  chr_sh "
    getent group obos >/dev/null || groupadd --system obos
    if ! id -u '$OBOS_USER' >/dev/null 2>&1; then
      useradd --create-home --shell /bin/bash --comment '$OBOS_NAME' '$OBOS_USER'
    fi
    for g in sudo obos audio video render netdev plugdev bluetooth input; do
      getent group \$g >/dev/null && usermod -aG \$g '$OBOS_USER'
    done
    echo '$OBOS_USER:$OBOS_PASSWORD' | chpasswd
    passwd -l root >/dev/null
  "
  install -d -m 0755 "$CHROOT/home/$OBOS_USER"
  cp -f "$CHROOT/etc/skel/.bash_profile" "$CHROOT/home/$OBOS_USER/.bash_profile"
  cp -f "$CHROOT/etc/skel/.xinitrc"      "$CHROOT/home/$OBOS_USER/.xinitrc"
  install -d -m 0755 "$CHROOT/home/$OBOS_USER/Downloads"
  chr_sh "chown -R '$OBOS_USER:$OBOS_USER' /home/$OBOS_USER"
  info "live user '$OBOS_USER' (password: $OBOS_PASSWORD)"

  install -d -m 0755 "$CHROOT/etc/systemd/system/getty@tty1.service.d"
  cat > "$CHROOT/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --noclear --skip-login --nonewline --noissue --autologin $OBOS_USER %I \$TERM
EOF
  info "automatic login on tty1"

  chr_sh "
    systemctl enable NetworkManager.service bluetooth.service systemd-timesyncd.service \
                     earlyoom.service ${OBOS_ID}-tune.service ${OBOS_ID}-autotest.service >/dev/null
    systemctl disable NetworkManager-wait-online.service >/dev/null 2>&1 || true
    # A Python process that waits all day to install updates at shutdown (~30 MB);
    # the apt-daily-upgrade timer installs them without it.
    systemctl disable unattended-upgrades.service >/dev/null 2>&1 || true
    # Printing: CUPS starts when something is printed and stops when idle.
    systemctl disable cups.service cups-browsed.service >/dev/null 2>&1 || true
    systemctl enable cups.socket cups.path >/dev/null 2>&1 || true
    systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service >/dev/null 2>&1 || true
    systemctl set-default multi-user.target >/dev/null
  "
  local unit
  for unit in pipewire.socket pipewire-pulse.socket wireplumber.service; do
    compgen -G "$CHROOT/etc/systemd/user/*.wants/$unit" >/dev/null \
      || warn "user unit $unit is not enabled; there will be no sound"
  done
  info "services enabled"

  # NetworkManager owns every interface.
  install -d -m 0755 "$CHROOT/etc/network"
  printf '# Interfaces are managed by NetworkManager.\nsource /etc/network/interfaces.d/*\n' \
    > "$CHROOT/etc/network/interfaces"

  cat > "$CHROOT/etc/default/keyboard" <<'EOF'
XKBMODEL="pc105"
XKBLAYOUT="us"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

  info "building the initramfs"
  chr_sh "update-initramfs -u -k all" || die "update-initramfs failed"

  set_stamp configure
}

# =========================================================== stage: cleanup

stage_cleanup() {
  step "Trimming the image"

  mount_pseudo

  chr_sh "
    apt-get autoremove -y --purge >/dev/null 2>&1 || true
    apt-get clean
  "

  rm -f  "$CHROOT/usr/sbin/policy-rc.d"
  rm -f  "$CHROOT/etc/resolv.conf"
  ln -sf /run/NetworkManager/resolv.conf "$CHROOT/etc/resolv.conf"

  rm -rf "$CHROOT"/var/lib/apt/lists/*
  rm -rf "$CHROOT"/var/cache/apt/*.bin
  rm -rf "$CHROOT"/var/cache/debconf/*-old
  rm -rf "$CHROOT"/tmp/* "$CHROOT"/var/tmp/*
  find   "$CHROOT/var/log" -type f -exec truncate -s 0 {} \; 2>/dev/null || true

  : > "$CHROOT/etc/machine-id"
  rm -f "$CHROOT/var/lib/dbus/machine-id"

  chr_sh "dpkg-query -W -f='\${binary:Package} \${Version}\n'" > "$WORK/packages.txt" || true

  unmount_all
  info "final system: $(du -sh "$CHROOT" | cut -f1), $(wc -l < "$WORK/packages.txt") packages"
  set_stamp cleanup
}

# ========================================================== stage: squashfs

stage_squashfs() {
  step "Compressing the system"

  unmount_all
  rm -rf "$ISODIR"
  mkdir -p "$ISODIR/live" "$ISODIR/boot/grub" "$ISODIR/.disk"

  local vmlinuz initrd
  vmlinuz="$(ls -1 "$CHROOT"/boot/vmlinuz-* 2>/dev/null | sort -V | tail -1)"
  initrd="$(ls -1 "$CHROOT"/boot/initrd.img-* 2>/dev/null | sort -V | tail -1)"
  [[ -f "$vmlinuz" && -f "$initrd" ]] || die "kernel or initramfs missing from the chroot"

  cp "$vmlinuz" "$ISODIR/live/vmlinuz"
  cp "$initrd"  "$ISODIR/live/initrd.img"
  info "kernel $(basename "$vmlinuz"), initramfs $(du -h "$initrd" | cut -f1)"

  cp -f "$WORK/packages.txt" "$ISODIR/live/filesystem.packages" 2>/dev/null || true

  # The kernel stays inside the squashfs: the installer copies this filesystem
  # to disk, and an installed system without /boot/vmlinuz cannot boot. The
  # initramfs is left out because the installer regenerates it anyway.
  # zstd at high levels takes a lot of memory per thread; on a small build
  # machine limit the threads and the queue (OBOS_SQUASHFS_PROCESSORS/_MEM).
  local procs="${OBOS_SQUASHFS_PROCESSORS:-$(nproc)}"
  info "compressing with $OBOS_COMPRESSION level $OBOS_COMPRESSION_LEVEL on $procs cores (the slow part)"
  mksquashfs "$CHROOT" "$ISODIR/live/filesystem.squashfs" \
    -comp "$OBOS_COMPRESSION" \
    -Xcompression-level "$OBOS_COMPRESSION_LEVEL" \
    -processors "$procs" ${OBOS_SQUASHFS_MEM:+-mem "$OBOS_SQUASHFS_MEM"} \
    -b 1M -noappend -no-progress \
    -wildcards \
    -e "proc/*" "sys/*" "dev/*" "run/*" "tmp/*" \
       "var/cache/apt/archives/*.deb" \
       "boot/initrd.img-*" \
    || die "mksquashfs failed"

  printf '%s' "$(du -sx --block-size=1 "$CHROOT" | cut -f1)" > "$ISODIR/live/filesystem.size"
  info "squashfs: $(du -h "$ISODIR/live/filesystem.squashfs" | cut -f1)"
  set_stamp squashfs
}

# =============================================================== stage: iso

stage_iso() {
  step "Building the ISO"

  local params="boot=live quiet loglevel=3 splash=off vt.global_cursor_default=0"

  # When OnlyBrowserOS is already installed on a disk in this computer (the
  # USB stick or virtual DVD was left in after installing), starting that
  # installed system comes first, so a restart after installing does not land
  # in the live system again with its "Install" button.
  cat > "$ISODIR/boot/grub/grub.cfg" <<EOF
set timeout=5
set timeout_style=menu

# With Secure Boot, GRUB may only use what is built into Debian's signed image
# (these are); on BIOS computers they load from /boot/grub/i386-pc.
if [ "\$grub_platform" = "pc" ]; then
    insmod part_msdos
    insmod part_gpt
    insmod ext2
fi

set color_normal=light-gray/black
set menu_color_normal=light-gray/black
set menu_color_highlight=white/blue

set default=0
if search --no-floppy --file --set=obos_installed /etc/$OBOS_ID/installed; then
    export obos_installed
    menuentry "Start $OBOS_NAME (installed on this computer)" {
        set root=\$obos_installed
        configfile /boot/grub/grub.cfg
    }
fi

menuentry "Try or install $OBOS_NAME" {
    linux  /live/vmlinuz $params
    initrd /live/initrd.img
}

submenu "Advanced options" {
    menuentry "Try or install $OBOS_NAME with safe graphics (for old or unusual screens)" {
        linux  /live/vmlinuz $params nomodeset
        initrd /live/initrd.img
    }
    menuentry "Try $OBOS_NAME and show start-up messages (for fixing problems)" {
        linux  /live/vmlinuz boot=live loglevel=6 systemd.show_status=1
        initrd /live/initrd.img
    }
}
EOF

  echo "$OBOS_NAME $OBOS_VERSION - $OBOS_ARCH - $(date -u +%Y-%m-%d)" > "$ISODIR/.disk/info"

  mkdir -p "$OUT_DIR"
  rm -f "$OUTPUT"

  # BIOS: GRUB's El Torito core image, with its modules next to it.
  local grub_pc=/usr/lib/grub/i386-pc
  install -d "$ISODIR/boot/grub/i386-pc"
  cp "$grub_pc"/*.mod "$grub_pc"/*.lst "$ISODIR/boot/grub/i386-pc/"
  grub-mkimage -O i386-pc-eltorito -d "$grub_pc" -p /boot/grub \
    -o "$ISODIR/boot/grub/i386-pc/eltorito.img" biosdisk iso9660 \
    || die "could not make the BIOS boot image"

  # UEFI, with Secure Boot on or off: Microsoft-signed shim starts Debian's
  # signed GRUB for discs and USB sticks, which finds this medium by
  # /.disk/info, reads /boot/grub/grub.cfg and starts Debian's signed kernel.
  local shim="$CHROOT/usr/lib/shim/shimx64.efi.signed"
  local mok="$CHROOT/usr/lib/shim/mmx64.efi.signed"
  local grub_efi="$CHROOT/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed"
  local f
  for f in "$shim" "$mok" "$grub_efi"; do
    [[ -f "$f" ]] || die "missing $f (packages shim-signed, shim-helpers-amd64-signed, grub-efi-amd64-signed)"
  done
  local efi="$ISODIR/efi.img"
  rm -f "$efi"
  mkfs.vfat -C -n OBOS-EFI "$efi" 10240 >/dev/null || die "could not make the EFI boot image"
  export MTOOLS_SKIP_CHECK=1
  mmd -i "$efi" ::/EFI ::/EFI/BOOT ::/EFI/debian
  mcopy -i "$efi" "$shim" ::/EFI/BOOT/BOOTX64.EFI
  mcopy -i "$efi" "$grub_efi" ::/EFI/BOOT/grubx64.efi
  mcopy -i "$efi" "$mok" ::/EFI/BOOT/mmx64.efi
  printf 'search --file --set=root /.disk/info\nset prefix=($root)/boot/grub\nconfigfile $prefix/grub.cfg\n' \
    > "$WORK/efi-grub.cfg"
  mcopy -i "$efi" "$WORK/efi-grub.cfg" ::/EFI/debian/grub.cfg

  # One hybrid image that boots on BIOS and UEFI, from a disc or written to a
  # USB stick: the layout grub-mkrescue makes, with the signed EFI files.
  xorriso -as mkisofs \
    -iso-level 3 -r -J -joliet-long \
    -V "$OBOS_VOLID" \
    --grub2-mbr "$grub_pc/boot_hybrid.img" \
    --protective-msdos-label \
    -partition_cyl_align off -partition_offset 0 -partition_hd_cyl 64 -partition_sec_hd 32 \
    -efi-boot-part --efi-boot-image \
    -c boot.catalog \
    -b boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
    -eltorito-alt-boot -e efi.img -no-emul-boot \
    -o "$OUTPUT" "$ISODIR" \
    || die "xorriso failed"

  chmod 0644 "$OUTPUT"
  ( cd "$(dirname "$OUTPUT")" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256" )
  if [[ -n "${SUDO_UID:-}" ]]; then
    chown "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$OUTPUT" "$OUTPUT.sha256" "$OUT_DIR"
  fi

  set_stamp iso
}

# ============================================================= run stages --

if (( DO_CLEAN )); then
  step "Cleaning"
  unmount_all
  rm -rf "$WORK"
  info "removed $WORK"
fi

printf '%s%s %s (Debian %s, %s)%s\n' "$C_B" "$OBOS_NAME" "$OBOS_VERSION" "$OBOS_SUITE" "$OBOS_ARCH" "$C_0"
printf '%soutput: %s%s\n' "$C_D" "$OUTPUT" "$C_0"

START=$(date +%s)

for stage in "${STAGES[@]}"; do
  if should_run "$stage"; then
    "stage_$stage"
  fi
  [[ "$stage" == "$TO" ]] && { info "stopping after '$TO' as asked"; exit 0; }
done

ELAPSED=$(( $(date +%s) - START ))

printf '\n%s  ✓  %s %s built in %dm %ds%s\n' \
  "$C_G" "$OBOS_NAME" "$OBOS_VERSION" "$((ELAPSED / 60))" "$((ELAPSED % 60))" "$C_0"
printf '     %s  (%s)\n' "$OUTPUT" "$(du -h "$OUTPUT" | cut -f1)"
printf '\n     test it:   %s/test-iso.sh\n' "$HERE"
printf '     write it:  sudo dd if=%s of=/dev/sdX bs=4M status=progress oflag=sync\n\n' "$OUTPUT"
