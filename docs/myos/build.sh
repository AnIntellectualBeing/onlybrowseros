#!/usr/bin/env bash
#
# MyOS: a small operating system built from nothing, one lesson at a time.
# Every lesson below matches a section of docs/10-make-your-own-os.md.
#
#   sudo ./build.sh                  all lessons, then the ISO
#   sudo ./build.sh --to 2           lessons 1-2 only, then the ISO (boot it and look)
#   sudo ./build.sh --from 7         redo lessons 7-9 on the existing system, then the ISO
#   sudo ./build.sh --iso            only rebuild the ISO
#
# The result is out/myos.iso. Try it with ./test.sh.
# Needs a Debian or Ubuntu machine with:
#   sudo apt install debootstrap squashfs-tools xorriso mtools grub-pc-bin \
#        grub-efi-amd64-bin grub-common dpkg-dev debian-archive-keyring qemu-system-x86

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HERE/work}"          # the system being built lives here
C="$WORK/chroot"                     # "C" = the folder that becomes MyOS's /
ISO="$WORK/iso"                      # the files that go onto the ISO
OUT="${OUT:-$HERE/out/myos.iso}"
SUITE=trixie                         # Debian 13
MIRROR=http://deb.debian.org/debian
USERNAME=me                          # the account MyOS logs in as
PASSWORD=live

FROM=1; TO=9
case "${1:-}" in
  --to)   TO="${2:?}" ;;
  --from) FROM="${2:?}" ;;
  --iso)  FROM=99 ;;
  "")     ;;
  *)      sed -n '4,16p' "$0"; exit 1 ;;
esac

[[ $EUID -eq 0 ]] || { echo "Run me with sudo."; exit 1; }

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

# Run a command inside MyOS. "chroot" makes the folder look like / to it.
in_chroot() { chroot "$C" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
                HOME=/root LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive bash -euc "$*"; }

# Programs inside the folder need the kernel's virtual file systems.
enter() {
  local m
  for m in proc sys dev dev/pts run; do mountpoint -q "$C/$m" && continue
    case $m in
      proc)    mount -t proc proc "$C/proc" ;;
      sys)     mount -t sysfs sys "$C/sys" ;;
      dev)     mount --bind /dev "$C/dev" ;;
      dev/pts) mount -t devpts devpts "$C/dev/pts" ;;
      run)     mount -t tmpfs tmpfs "$C/run" ;;
    esac
  done
  # So apt inside can look up names (the real file is replaced in lesson 5).
  rm -f "$C/etc/resolv.conf"; cp -L /etc/resolv.conf "$C/etc/resolv.conf"
  # Tell every package "don't start services now": we are not running MyOS yet.
  printf '#!/bin/sh\nexit 101\n' > "$C/usr/sbin/policy-rc.d"; chmod +x "$C/usr/sbin/policy-rc.d"
}
leave() {
  rm -f "$C/usr/sbin/policy-rc.d"
  local m; for m in run dev/pts dev sys proc; do
    mountpoint -q "$C/$m" && umount -l "$C/$m"; done; true
}
trap leave EXIT

apt_install() { in_chroot "apt-get update -qq && apt-get install -y $*"; }

# Install a folder under packages/ as a real Debian package.
install_package() {
  local name="$1" tmp
  tmp="$(mktemp -d)"
  cp -a "$HERE/packages/$name" "$tmp/"
  chmod -R u+rwX,go+rX,go-w "$tmp/$name"         # git does not keep permissions
  dpkg-deb --root-owner-group --build "$tmp/$name" "$C/tmp/$name.deb"
  rm -rf "$tmp"
  in_chroot "apt-get update -qq && apt-get install -y /tmp/$name.deb && rm /tmp/$name.deb"
}

# ======================================================================
lesson1() { say "Lesson 1: a minimal Debian in a folder"
  leave; rm -rf "$C"; mkdir -p "$C"
  # Ubuntu's debootstrap may not know the newest Debian name yet.
  [[ -e /usr/share/debootstrap/scripts/$SUITE ]] || ln -s sid "/usr/share/debootstrap/scripts/$SUITE"
  debootstrap --variant=minbase \
    --components=main,contrib,non-free,non-free-firmware \
    --include=ca-certificates \
    "$SUITE" "$C" "$MIRROR"
  du -sh "$C"
}

# ======================================================================
lesson2() { say "Lesson 2: make it bootable"
  enter
  cat > "$C/etc/apt/sources.list" <<EOF
deb $MIRROR $SUITE main contrib non-free non-free-firmware
deb $MIRROR $SUITE-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security $SUITE-security main contrib non-free non-free-firmware
EOF
  # Only what we ask for: no "recommended" extras. Smaller and faster,
  # but every package you really need must be named.
  cat > "$C/etc/apt/apt.conf.d/99myos" <<'EOF'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
EOF
  apt_install linux-image-amd64 systemd-sysv udev dbus libpam-systemd \
              live-boot live-boot-initramfs-tools initramfs-tools \
              sudo procps less nano
  echo 'LANG=C.UTF-8' > "$C/etc/default/locale"
  in_chroot "id $USERNAME >/dev/null 2>&1 || useradd --create-home --shell /bin/bash \
               --groups sudo,audio,video,render,input $USERNAME
             echo '$USERNAME:$PASSWORD' | chpasswd
             passwd -l root"
  # Rebuild the initramfs so it contains live-boot.
  in_chroot "update-initramfs -u -k all"
}

# ======================================================================
lesson3() { say "Lesson 3: give it a name"
  # /etc/os-release is a link to /usr/lib/os-release; write the real file.
  cat > "$C/usr/lib/os-release" <<'EOF'
PRETTY_NAME="MyOS 0.1"
NAME="MyOS"
VERSION_ID="0.1"
VERSION="0.1"
ID=myos
ID_LIKE=debian
HOME_URL="https://example.org/myos"
EOF
  echo myos > "$C/etc/hostname"
  printf '127.0.0.1\tlocalhost\n127.0.1.1\tmyos\n' > "$C/etc/hosts"
  printf 'MyOS 0.1 \\n \\l\n\n' > "$C/etc/issue"          # shown above the login prompt
  printf '\nWelcome to MyOS. Type "sudo poweroff" to switch off.\n\n' > "$C/etc/motd"
}

# ======================================================================
lesson4() { say "Lesson 4: log in by itself, and your first service"
  # A drop-in changes one setting of a unit without copying the whole file.
  mkdir -p "$C/etc/systemd/system/getty@tty1.service.d"
  cat > "$C/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --noclear --autologin $USERNAME %I \$TERM
EOF
  # Your own program and a service that runs it once at every start.
  cat > "$C/usr/local/bin/myos-hello" <<'EOF'
#!/bin/sh
ram=$(free -m | awk '/^Mem:/ {print $2}')
echo "MyOS: started with $(nproc) CPU(s) and $ram MB of RAM"
EOF
  chmod +x "$C/usr/local/bin/myos-hello"
  cat > "$C/etc/systemd/system/myos-hello.service" <<'EOF'
[Unit]
Description=Say hello at start-up

[Service]
Type=oneshot
ExecStart=/usr/local/bin/myos-hello
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
EOF
  enter
  in_chroot "systemctl enable myos-hello.service"
}

# ======================================================================
lesson5() { say "Lesson 5: networking"
  enter
  apt_install network-manager wpasupplicant iw rfkill wireless-regdb iputils-ping curl
  in_chroot "systemctl enable NetworkManager && systemctl disable NetworkManager-wait-online"
}

# ======================================================================
lesson6() { say "Lesson 6: graphics, and a browser that fills the screen"
  enter
  apt_install xserver-xorg-core xserver-xorg-input-libinput xinit x11-xserver-utils \
              openbox firefox-esr fonts-dejavu-core fonts-noto-color-emoji
  # tty1 logs in by itself (lesson 4); its login shell starts the graphics.
  cat > "$C/etc/skel/.bash_profile" <<'EOF'
[ -f ~/.bashrc ] && . ~/.bashrc
if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    exec startx -- vt1 -keeptty >~/.xorg.log 2>&1
fi
EOF
  cat > "$C/etc/skel/.xinitrc" <<'EOF'
xset s off -dpms
openbox &
exec firefox-esr --kiosk https://www.wikipedia.org
EOF
  in_chroot "cp /etc/skel/.bash_profile /etc/skel/.xinitrc /home/$USERNAME/ &&
             chown $USERNAME: /home/$USERNAME/.bash_profile /home/$USERNAME/.xinitrc"
}

# ======================================================================
lesson7() { say "Lesson 7: your own desktop: a session and a bar, as a package"
  enter
  install_package myos-desktop
  # Start our session instead of ~/.xinitrc.
  sed -i 's|exec startx -- |exec startx /usr/bin/myos-session -- |' \
    "$C/etc/skel/.bash_profile"
  in_chroot "cp /etc/skel/.bash_profile /home/$USERNAME/ && rm -f /etc/skel/.xinitrc /home/$USERNAME/.xinitrc"
}

# ======================================================================
lesson8() { say "Lesson 8: your own browser setup, as a second package"
  enter
  install_package myos-browser
}

# ======================================================================
lesson9() { say "Lesson 9: ready for real laptops"
  enter
  apt_install xserver-xorg-video-all pipewire pipewire-pulse wireplumber \
              systemd-zram-generator
  # Firmware: each may be missing on some Debian release; skip what fails.
  local p
  for p in firmware-linux-free firmware-misc-nonfree firmware-iwlwifi firmware-realtek \
           firmware-atheros firmware-intel-graphics firmware-amd-graphics \
           firmware-sof-signed intel-microcode amd64-microcode; do
    in_chroot "apt-get install -y $p" || echo "skipped $p"
  done
  in_chroot "update-initramfs -u -k all"
}

# ======================================================================
make_iso() { say "Making the ISO"
  leave
  # The build's copy of our resolver file must not ship. With NetworkManager
  # (lesson 5) the real one is written at run time; point there.
  rm -f "$C/etc/resolv.conf"
  [[ -x "$C/usr/sbin/NetworkManager" ]] && ln -s /run/NetworkManager/resolv.conf "$C/etc/resolv.conf"
  rm -rf "$C/var/lib/apt/lists/"* "$C/var/cache/apt/"*.bin "$C/tmp/"*
  : > "$C/etc/machine-id"                    # every computer makes its own at first start

  rm -rf "$ISO"; mkdir -p "$ISO/live" "$ISO/boot/grub"
  cp "$C"/boot/vmlinuz-*    "$ISO/live/vmlinuz"
  cp "$C"/boot/initrd.img-* "$ISO/live/initrd.img"
  cp "$HERE/grub.cfg" "$ISO/boot/grub/grub.cfg"
  # The whole system, compressed into one read-only file.
  mksquashfs "$C" "$ISO/live/filesystem.squashfs" -comp zstd -noappend \
    -e boot/initrd.img-*
  mkdir -p "$(dirname "$OUT")"
  # grub-mkrescue: a boot loader for BIOS and UEFI plus our files, as one ISO.
  grub-mkrescue -o "$OUT" "$ISO" -- -volid MYOS
  ls -lh "$OUT"
}

# ======================================================================
for n in 1 2 3 4 5 6 7 8 9; do
  (( n >= FROM && n <= TO )) && "lesson$n"
done
make_iso
