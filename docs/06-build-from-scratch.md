# Build It From Scratch — the Whole Process by Hand

My build script (`github/build/build-iso.sh`) does everything below
automatically. This guide does the same work **one command at a time**, so
every step is visible and understood. Follow it once and you can make any
"Linux that boots into one program" system, with or without my scripts.

Commands starting with `$` run as your normal user, `#` as root (`sudo -i`).
Everything happens in a work folder; nothing on your own system changes except
the build tools you install.

---

## Part 0 — What a bootable Linux USB stick actually contains

Before building one, know the four pieces:

| Piece | File on the ISO | What it does |
|---|---|---|
| **Boot loader** (GRUB) | `boot/grub/…`, `EFI/BOOT/…` | The first program the firmware runs. Shows the menu, loads the next two files into memory. |
| **Kernel** | `live/vmlinuz` | Linux itself: drives the hardware, runs programs. |
| **initramfs** | `live/initrd.img` | A tiny temporary root file system in RAM. Its only job: find the real system and switch to it. For a USB stick that means finding the squashfs file below and mounting it. |
| **The system** | `live/filesystem.squashfs` | Every program and file of the OS, compressed into one read-only file. |

Start-up order: **firmware → GRUB → kernel + initramfs → mount squashfs →
systemd → login → graphics → browser.**

A USB stick is read-only for the running system, so the Debian package
`live-boot` (inside the initramfs) stacks a RAM layer on top of the squashfs
(overlayfs): the system *thinks* it can write anywhere; writes land in RAM and
disappear at power-off. Installing to a disk is then just "copy the running
system onto a real partition and make that disk bootable".

Two firmware types must both work:
- **BIOS** (old PCs): reads the first sector of the disk.
- **UEFI** (anything from ~2012): reads `.efi` programs from a FAT partition.
  With **Secure Boot** on it only runs programs signed by a key it trusts
  (Microsoft's). That's why I use Microsoft-signed `shim`, which then runs
  Debian-signed GRUB and a Debian-signed kernel (Part 9).

---

## Part 1 — The build machine

Any Debian or Ubuntu machine or VM, 12 GB free, internet:

```
$ sudo apt install debootstrap squashfs-tools xorriso mtools dosfstools \
      grub-pc-bin grub-efi-amd64-bin grub-common rsync zstd \
      debian-archive-keyring qemu-system-x86 qemu-utils ovmf
$ mkdir -p ~/obos && cd ~/obos
```

- `debootstrap` — downloads a minimal Debian into a folder.
- `squashfs-tools` — makes the compressed system file.
- `xorriso`, `mtools`, `dosfstools` — make the ISO and its FAT boot image.
- `grub-*` — the BIOS boot image is built from these.
- `qemu`, `ovmf` — a virtual PC (with UEFI firmware) to test in.

---

## Part 2 — A minimal Debian in a folder (debootstrap)

```
# debootstrap --arch=amd64 --variant=minbase \
      --components=main,contrib,non-free,non-free-firmware \
      trixie ~/obos/chroot http://deb.debian.org/debian
```

`~/obos/chroot` is now a complete (tiny, ~250 MB) Debian 13: `/bin`, `/etc`,
`/usr`, a package manager, but no kernel, no graphics, no network manager.
`minbase` means only the essential packages. `non-free-firmware` is needed
because most Wi-Fi cards need binary firmware.

On Ubuntu, if debootstrap does not know "trixie" yet:
`# ln -s sid /usr/share/debootstrap/scripts/trixie`.

---

## Part 3 — Working inside the folder (chroot)

`chroot` runs a program with a folder as its `/`. Programs inside need the
kernel's virtual file systems, so mount them first:

```
# C=~/obos/chroot
# mount -t proc proc $C/proc
# mount -t sysfs sys $C/sys
# mount --bind /dev $C/dev
# mount -t devpts devpts $C/dev/pts
# mount -t tmpfs tmpfs $C/run
# cp /etc/resolv.conf $C/etc/resolv.conf          # so apt can resolve names
# printf '#!/bin/sh\nexit 101\n' > $C/usr/sbin/policy-rc.d && chmod +x $C/usr/sbin/policy-rc.d
# chroot $C /bin/bash
```

`policy-rc.d` returning 101 tells Debian's packages "do not start services
now". Without it, installing NetworkManager inside the folder would try to
start it on *your* machine.

Everything in Parts 4–7 runs inside this chroot shell (prompt `(chroot)#`).
When done: `exit`, then unmount in reverse order (`umount $C/run $C/dev/pts
$C/dev $C/sys $C/proc`).

---

## Part 4 — Package sources and keeping it small

```
(chroot)# cat > /etc/apt/sources.list <<'EOF'
deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb http://deb.debian.org/debian trixie-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
EOF
(chroot)# cat > /etc/apt/apt.conf.d/99obos <<'EOF'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
EOF
(chroot)# cat > /etc/dpkg/dpkg.cfg.d/99obos-slim <<'EOF'
path-exclude=/usr/share/man/*
path-exclude=/usr/share/doc/*
path-include=/usr/share/doc/*/copyright
path-exclude=/usr/share/info/*
EOF
(chroot)# apt-get update
```

**No "Recommends"** is the single biggest size and RAM saving: Debian packages
recommend many extras (a full desktop's worth). The price: I must name every
package I really need myself. Forgetting one is a real bug class — in v1.2 I
found Bluetooth headphones paired but played no sound, because PipeWire's
Bluetooth module (`libspa-0.2-bluetooth`) is only a *recommendation* of
PipeWire.

---

## Part 5 — Installing the operating system's parts

Each group is a list in `github/build/config.sh`. By hand:

```
(chroot)# apt-get install -y \
    linux-image-amd64 systemd-sysv systemd-timesyncd libpam-systemd dbus dbus-user-session udev \
    live-boot live-boot-initramfs-tools initramfs-tools \
    locales tzdata keyboard-configuration console-setup sudo polkitd ca-certificates \
    procps psmisc util-linux less nano iproute2 iputils-ping curl
```
The kernel, systemd (the first program, PID 1, that starts everything else),
and `live-boot`, which teaches the initramfs to boot from the squashfs.

```
(chroot)# apt-get install -y network-manager wpasupplicant iw rfkill wireless-regdb bluez
```
Networking: NetworkManager handles Wi-Fi and cable; my taskbar talks to it
with `nmcli`. `bluez` is the Bluetooth service; the taskbar talks to it with
`bluetoothctl`.

```
(chroot)# apt-get install -y xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-video-all \
    xinit x11-xserver-utils x11-xkb-utils openbox \
    fonts-dejavu-core fonts-liberation2 fonts-noto-core fonts-noto-color-emoji
```
Graphics: the X server draws the screen, `xinit`/`startx` starts it, and
**openbox** is the window manager — I use it only to keep the browser
maximised without a title bar and to bind the laptop keys. It uses about 3 MB.

```
(chroot)# apt-get install -y firefox-esr libpci3 libxss1 libavcodec61
(chroot)# apt-get install -y pipewire pipewire-pulse pipewire-alsa wireplumber \
    libspa-0.2-bluetooth pulseaudio-utils alsa-ucm-conf
(chroot)# apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 brightnessctl
(chroot)# apt-get install -y cups cups-client cups-filters ipp-usb avahi-daemon libnss-mdns
(chroot)# apt-get install -y systemd-zram-generator earlyoom unattended-upgrades xdg-utils
```
- Firefox ESR (Extended Support Release: one major version for about a year,
  security fixes weekly). `libavcodec` gives it H.264/AAC video (YouTube,
  video calls); `libxss1` lets it keep the screen on during video.
- PipeWire is the sound server; `pactl` and `wpctl` control it.
- Python + GTK 3 for my taskbar, installer and home screen.
- CUPS prints to modern printers without drivers ("driverless" IPP).
- zram (compressed swap in RAM) and earlyoom are what make 1 GB machines
  survive (see `08-memory.md`).

The installer runs from the USB stick, so its tools must be inside too:
```
(chroot)# apt-get install -y parted gdisk dosfstools e2fsprogs rsync \
    grub-common grub2-common grub-pc-bin grub-efi-amd64-bin efibootmgr \
    shim-signed shim-helpers-amd64-signed grub-efi-amd64-signed
```

Firmware for real laptops (each one may fail on its own; that's fine):
```
(chroot)# for p in firmware-linux-free firmware-misc-nonfree firmware-iwlwifi firmware-realtek \
    firmware-atheros firmware-brcm80211 firmware-intel-graphics firmware-intel-sound \
    firmware-mediatek firmware-amd-graphics firmware-sof-signed firmware-cirrus bluez-firmware \
    intel-microcode amd64-microcode intel-media-va-driver mesa-va-drivers; do
    apt-get install -y $p || echo "skipped $p"; done
```

At this point the folder is about 2 GB: a working Debian with a browser, but
nothing that makes it *OnlyBrowserOS* yet.

---

## Part 6 — Adding OnlyBrowserOS itself

Everything I wrote lives in `github/src/` and `github/build/overlay/`. My
build turns it into **one Debian package** (`make-package.sh`) and installs it
with `dpkg -i`, so the ISO and later updates install exactly the same thing.
By hand, it is copying files into place:

| From the repo | To the system | What it is |
|---|---|---|
| `src/panel/*.py`, `src/shared/*.py`, `src/home/`, `src/installer/` | `/usr/lib/onlybrowseros/…` | taskbar, home screen, installer |
| `src/system/*`, `src/installer/install-helper` | `/usr/lib/onlybrowseros/` | root helpers |
| `src/session/autostart`, `browser`, `media-key` | `/usr/lib/onlybrowseros/` | the session scripts |
| `src/session/onlybrowseros-session` | `/usr/bin/` | starts openbox |
| `src/start/` | `/usr/share/onlybrowseros/start/` | start page, Downloads page |
| `src/firefox/autoconfig.js` | `/usr/lib/firefox-esr/defaults/pref/` | tells Firefox to read… |
| `src/firefox/onlybrowseros.cfg` | `/usr/lib/firefox-esr/` | …this: new-tab page, hidden menus |
| `src/firefox/tablimit/` zipped as `.xpi` | `/usr/lib/onlybrowseros/tablimit.xpi` | my Firefox extension |
| `src/firefox/native-host.json` | `/usr/lib/mozilla/native-messaging-hosts/` | lets the extension call `settings-host` |
| `build/overlay/etc/…` | `/etc/…` | system configuration (below) |

The important configuration files in the overlay:
- `etc/sudoers.d/onlybrowseros` — the few root helpers the user may run
  without a password (tab limit, time zone, keyboard, USB mounting).
- `etc/polkit-1/rules.d/` — lets the user manage Wi-Fi, Bluetooth, sleep.
- `etc/systemd/system/onlybrowseros-tune.service` — runs `tune` at every boot
  (writes Firefox's policies and memory settings for this machine's RAM).
- `etc/systemd/zram-generator.conf`, `etc/sysctl.d/`, earlyoom override —
  memory safety.
- `etc/onlybrowseros/openbox/rc.xml` — window rules and laptop keys.
- `etc/udev/rules.d/` — mount USB sticks; notice plugged-in screens.
- `etc/systemd/logind.conf.d/` — power button sleeps, long press shuts down.
- `etc/skel/.bash_profile` — starts the graphics on tty1 (Part 7).

With my repo: `$ github/build/make-package.sh /tmp/pkg` builds the package;
then copy it into the chroot and `(chroot)# dpkg -i /tmp/onlybrowseros_*.deb`.

---

## Part 7 — Configuring: user, auto-login, services

```
(chroot)# sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen
(chroot)# echo 'LANG=en_US.UTF-8' > /etc/default/locale
(chroot)# groupadd --system obos
(chroot)# useradd --create-home --shell /bin/bash user
(chroot)# for g in sudo obos audio video render netdev plugdev bluetooth input; do usermod -aG $g user; done
(chroot)# echo 'user:live' | chpasswd && passwd -l root
(chroot)# cp /etc/skel/.bash_profile /home/user/ && chown user: /home/user/.bash_profile
```
Permissions go to the `obos` **group**, not the user name, because the
installer later renames the account (`user` → whatever the person types) and
group membership survives a rename.

**Auto-login** — a systemd "drop-in" that changes how the text console on tty1
starts:
```
(chroot)# mkdir -p /etc/systemd/system/getty@tty1.service.d
(chroot)# cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --noclear --skip-login --nonewline --noissue --autologin user %I $TERM
EOF
```

The chain from here to the browser, all plain files:
1. `agetty` logs `user` in on tty1 → bash runs `~/.bash_profile`.
2. `.bash_profile` sees tty1 and no screen yet → `startx onlybrowseros-session`
   (in a loop: if the screen session dies, it starts again).
3. `onlybrowseros-session` sets keyboard, text size, screen power saving, then
   `exec openbox --startup /usr/lib/onlybrowseros/autostart`.
4. `autostart` starts the taskbar (restarted if it exits) and the `browser`
   script.
5. `browser` runs Firefox in a loop: closed on purpose → home screen;
   crashed → start again, and after repeated quick crashes set the last session
   aside (a page that crashes Firefox on restore would otherwise loop forever).

Services:
```
(chroot)# systemctl enable NetworkManager bluetooth systemd-timesyncd earlyoom \
      onlybrowseros-tune fstrim.timer cups.socket
(chroot)# systemctl disable NetworkManager-wait-online unattended-upgrades cups cups-browsed
(chroot)# systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service
(chroot)# systemctl set-default multi-user.target
(chroot)# update-initramfs -u -k all
```
`multi-user.target` means "no display manager": graphics come from the
auto-login, which saves a whole login-screen program. CUPS is started by its
socket only when something prints. The last command rebuilds the initramfs so
it contains live-boot.

---

## Part 8 — Clean up and compress

```
(chroot)# apt-get clean && exit
# rm -f $C/usr/sbin/policy-rc.d $C/etc/resolv.conf
# ln -s /run/NetworkManager/resolv.conf $C/etc/resolv.conf
# rm -rf $C/var/lib/apt/lists/* $C/tmp/*
# : > $C/etc/machine-id                    # every installed copy gets its own ID
# umount $C/run $C/dev/pts $C/dev $C/sys $C/proc

# mkdir -p ~/obos/iso/live ~/obos/iso/boot/grub ~/obos/iso/.disk
# cp $C/boot/vmlinuz-* ~/obos/iso/live/vmlinuz
# cp $C/boot/initrd.img-* ~/obos/iso/live/initrd.img
# mksquashfs $C ~/obos/iso/live/filesystem.squashfs -comp zstd -Xcompression-level 19 \
      -b 1M -noappend -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*' 'boot/initrd.img-*'
# echo "OnlyBrowserOS" > ~/obos/iso/.disk/info
```
**zstd instead of xz:** a slightly bigger file, but several times faster to
decompress — an old laptop reading from a slow USB stick feels decompression
speed, not file size. The kernel stays *inside* the squashfs too, because the
installer copies that file system to disk, and an installed system needs its
kernel in `/boot`.

---

## Part 9 — The boot loader and the ISO (BIOS + UEFI + Secure Boot)

The menu, `~/obos/iso/boot/grub/grub.cfg`:
```
set timeout=5
menuentry "Try or install OnlyBrowserOS" {
    linux  /live/vmlinuz boot=live quiet
    initrd /live/initrd.img
}
menuentry "Safe graphics" {
    linux  /live/vmlinuz boot=live quiet nomodeset
    initrd /live/initrd.img
}
```
`boot=live` switches live-boot on; `nomodeset` falls back to basic graphics
for unusual screens. (My real menu also starts an already-installed copy first
if it finds one, so a stick left in after installing is harmless.)

**BIOS boot image** — GRUB's core, built from the unsigned modules (BIOS has
no Secure Boot):
```
# mkdir -p ~/obos/iso/boot/grub/i386-pc
# cp /usr/lib/grub/i386-pc/*.mod /usr/lib/grub/i386-pc/*.lst ~/obos/iso/boot/grub/i386-pc/
# grub-mkimage -O i386-pc-eltorito -d /usr/lib/grub/i386-pc -p /boot/grub \
      -o ~/obos/iso/boot/grub/i386-pc/eltorito.img biosdisk iso9660
```

**UEFI boot image** — a small FAT disk image holding **signed** programs,
taken from the chroot's `shim-signed` and `grub-efi-amd64-signed` packages:
```
# mkfs.vfat -C -n OBOS-EFI ~/obos/iso/efi.img 10240
# mmd -i ~/obos/iso/efi.img ::/EFI ::/EFI/BOOT ::/EFI/debian
# mcopy -i ~/obos/iso/efi.img $C/usr/lib/shim/shimx64.efi.signed ::/EFI/BOOT/BOOTX64.EFI
# mcopy -i ~/obos/iso/efi.img $C/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed ::/EFI/BOOT/grubx64.efi
# mcopy -i ~/obos/iso/efi.img $C/usr/lib/shim/mmx64.efi.signed ::/EFI/BOOT/mmx64.efi
# printf 'search --file --set=root /.disk/info\nset prefix=($root)/boot/grub\nconfigfile $prefix/grub.cfg\n' > /tmp/g.cfg
# mcopy -i ~/obos/iso/efi.img /tmp/g.cfg ::/EFI/debian/grub.cfg
```
UEFI firmware runs `\EFI\BOOT\BOOTX64.EFI` from removable media. That is
**shim**, signed by Microsoft, so Secure Boot accepts it. Shim runs
`grubx64.efi`, Debian's GRUB signed with Debian's key (which shim trusts).
Signed GRUB may not load modules from disk, and it looks for its config in
`\EFI\debian\grub.cfg` — hence the three-line file that finds the ISO by
`/.disk/info` and jumps to the real menu. GRUB then loads Debian's signed
kernel.

Why not just `grub-mkrescue`? It is the usual one-liner, but it builds its own
**unsigned** GRUB, which Secure Boot refuses ("Access Denied"). This manual
assembly is the fix.

**The hybrid ISO** — one file that boots as a DVD or a USB stick, BIOS or UEFI:
```
# xorriso -as mkisofs -iso-level 3 -r -J -joliet-long -V ONLYBROWSEROS \
    --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img --protective-msdos-label \
    -partition_cyl_align off -partition_offset 0 -partition_hd_cyl 64 -partition_sec_hd 32 \
    -efi-boot-part --efi-boot-image -c boot.catalog \
    -b boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
    -eltorito-alt-boot -e efi.img -no-emul-boot \
    -o ~/obos/onlybrowseros.iso ~/obos/iso
```
- `--grub2-mbr … boot_hybrid.img` puts a BIOS boot sector at the start, so the
  file also boots when written raw to a USB stick.
- `-b …eltorito.img` is the BIOS entry, `-e efi.img` the UEFI entry.
- `-efi-boot-part --efi-boot-image` also exposes `efi.img` as a partition,
  which is what UEFI looks for on a USB stick.

---

## Part 10 — Testing in a virtual machine

```
$ qemu-img create -f qcow2 disk.qcow2 20G
$ qemu-system-x86_64 -m 1024 -smp 2 -accel kvm -cpu host -vga std \
      -cdrom onlybrowseros.iso -drive file=disk.qcow2,if=virtio
```
- `-m 1024` = a 1 GB laptop. Remove `-accel kvm -cpu host` if the build machine
  is itself a VM without nested virtualisation (much slower then).
- UEFI: add `-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd`
  and a writable copy of `OVMF_VARS_4M.fd`.
- Secure Boot: use `OVMF_CODE_4M.secboot.fd` with a copy of
  `OVMF_VARS_4M.ms.fd` (Microsoft keys enrolled, like a shop-bought laptop),
  plus `-machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on`.

My `test-iso.sh` does this automatically and headless: it boots with
`obos.autotest=report` on the kernel command line, which makes
`src/system/autotest` (inside the image) test the tab limit, downloads,
settings, printing and the home screen, measure memory, and print the results
on the serial port, which the script collects. `--auto-install` installs onto
the virtual disk first, then boots the installed system and tests that.

---

## Part 11 — Writing the USB stick and booting a real laptop

```
$ lsblk                                   # find the stick, e.g. /dev/sdb
$ sudo dd if=onlybrowseros.iso of=/dev/sdb bs=4M status=progress oflag=sync
```
`dd` copies the file byte for byte, which works because the ISO is hybrid
(Part 9). On the laptop, the one-time boot menu key is usually F12, F9 or Esc.

---

## Part 12 — How the installer turns the live system into an installed one

`src/installer/install-helper` runs as root and does, in order:

1. **Checks** the chosen disk: a whole disk, 8 GB or more, not the USB stick
   it runs from, nothing mounted.
2. **Partitions**: UEFI → GPT with a 512 MB FAT32 EFI partition + ext4 for the
   rest; BIOS → an MS-DOS table with one ext4 partition (what very old BIOSes
   expect).
3. **Copies** the running system with `rsync -aHAX / /target/`, skipping
   `/proc`, `/sys`, `/dev`, the live medium, caches and the live session's
   browser profile.
4. **Swap file** sized from RAM (the second swap after zram), and
   `/etc/fstab` using partition UUIDs.
5. **The account**: hostname, time zone, keyboard, renames `user` to the
   chosen name (`usermod -l … -m`), sets the password, keeps or removes
   auto-login, and **deletes the live-only sudoers file** so the installed
   computer can never run the disk-erasing helper.
6. **Boot**: removes `live-boot`, rebuilds the initramfs, and runs
   `grub-install --uefi-secure-boot` (UEFI, installs shim + signed GRUB, also
   to the fallback path `\EFI\BOOT\BOOTX64.EFI` because cheap firmware forgets
   boot entries) or `grub-install --target=i386-pc` (BIOS), then `update-grub`
   and an `efibootmgr` entry named OnlyBrowserOS.

The GTK installer (`installer.py`) only collects the choices and shows
progress: it sends the choices as JSON to the helper through
`sudo -n` and reads `##{"phase":…,"percent":…}` lines back.

---

## Part 13 — Updates

- **Debian's security updates**: `unattended-upgrades` installs them daily
  (the apt timers are delayed and limited so they never slow down browsing).
- **My own updates**: the same `onlybrowseros` package, published in a
  signed apt repository on GitHub Pages. `release.sh` builds the package, runs
  `apt-ftparchive` to make the `Packages`/`Release` index, signs it with my
  GPG key and pushes. Computers have the repository and my public key built
  in, so they update themselves exactly like Debian's own packages. See
  `03-how-it-was-built.md`.

---

## Where to go from here

- Change a package list in `github/build/config.sh`, rebuild with
  `sudo ./build-iso.sh --from apt`, and watch the size and memory change in the
  test report.
- Change the taskbar (`github/src/panel/panel.py`), rebuild with `--from
  overlay`: a couple of minutes.
- Read `02-how-it-works.md` for how each running piece works, and
  `04-decisions-and-why.md` for why it's built this way.
