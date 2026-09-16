#!/usr/bin/env python3
"""
WebOS privileged helper.

Everything the bridge cannot do as an unprivileged user lives here. It is
invoked as `sudo -n /usr/lib/webos/webos-helper <command>` and nothing else in
the sudoers file is granted, so this file is the entire root attack surface of
the running system. Keep it small and keep every input validated.

Commands
--------
  install     read JSON options on stdin and install WebOS to a disk,
              emitting progress on stdout as `##{"phase":..,"percent":..}`
              lines interleaved with plain log lines.

The caller is the machine's own desktop session, so the intent here is to stop
mistakes -- wiping the disk you booted from, a username that breaks useradd --
rather than to defend against a hostile local user, who could simply use sudo
for the same commands.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TARGET = Path("/target")
ESP_MOUNT = TARGET / "boot" / "efi"

# Paths that must not be copied into the installed system: kernel virtual
# filesystems, the live medium, and caches that would just waste disk.
RSYNC_EXCLUDES = [
    "/dev/*", "/proc/*", "/sys/*", "/run/*", "/tmp/*",
    "/mnt/*", "/media/*", "/target", "/target/*",
    "/cdrom/*", "/live/*", "/lib/live/mount/*",
    "/lost+found", "/swapfile",
    "/var/cache/apt/archives/*.deb",
    "/var/tmp/*",
    "/home/*/.cache/*",
    "/root/.cache/*",
    "/etc/fstab",
    "/etc/machine-id",
    "/var/lib/dbus/machine-id",
    "/etc/systemd/system/getty@tty1.service.d/autologin.conf",
]

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TZ_RE = re.compile(r"^[A-Za-z0-9+_/-]{1,64}$")
KB_RE = re.compile(r"^[a-z]{2,6}$")

RESERVED_USERS = {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp",
                  "mail", "news", "uucp", "proxy", "www-data", "backup", "list",
                  "irc", "nobody", "systemd-network", "messagebus"}


# ---------------------------------------------------------------- output

def emit(**kwargs):
    sys.stdout.write("##" + json.dumps(kwargs) + "\n")
    sys.stdout.flush()


def say(text):
    sys.stdout.write(str(text).rstrip() + "\n")
    sys.stdout.flush()


class Fail(Exception):
    pass


# ---------------------------------------------------------------- running

def sh(args, check=True, quiet=False, timeout=None, chroot=False):
    if chroot:
        args = ["chroot", str(TARGET)] + args
    if not quiet:
        say("  $ " + " ".join(args))
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise Fail(f"{args[0]}: command not found")
    except subprocess.TimeoutExpired:
        raise Fail(f"{args[0]}: timed out")

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if out and not quiet:
        for line in out.splitlines()[-15:]:
            say("    " + line)
    if err and not quiet:
        for line in err.splitlines()[-15:]:
            say("    " + line)
    if check and p.returncode != 0:
        raise Fail(f"{args[0]} failed (status {p.returncode}): {err.splitlines()[-1] if err else 'no detail'}")
    return p.returncode, out, err


# ------------------------------------------------------------ validation

def validate(opts):
    disk = str(opts.get("disk", ""))
    if not re.fullmatch(r"/dev/[a-zA-Z0-9/_-]{1,40}", disk):
        raise Fail(f"Refusing to touch {disk!r}: not a device path")
    if not Path(disk).is_block_device():
        raise Fail(f"{disk} is not a block device")

    # Must be a whole disk, not a partition.
    code, out, _ = sh(["lsblk", "-ndo", "TYPE", disk], quiet=True)
    if out.strip() != "disk":
        raise Fail(f"{disk} is a {out.strip() or 'unknown device'}, not a whole disk")

    # Refuse anything currently providing a mounted filesystem.
    code, out, _ = sh(["lsblk", "-nro", "MOUNTPOINT", disk], quiet=True)
    mounted = [m for m in out.split("\n") if m.strip()]
    if mounted:
        raise Fail(f"{disk} is in use (mounted at {', '.join(mounted)}) — "
                   f"this is almost certainly the disk you booted from")

    username = str(opts.get("username", "")).strip()
    if not USERNAME_RE.fullmatch(username):
        raise Fail(f"Invalid username {username!r}")
    if username in RESERVED_USERS:
        raise Fail(f"{username!r} is a reserved system account")

    hostname = str(opts.get("hostname", "")).strip()
    if not HOSTNAME_RE.fullmatch(hostname):
        raise Fail(f"Invalid computer name {hostname!r}")

    password = str(opts.get("password", ""))
    if len(password) < 4:
        raise Fail("Password must be at least 4 characters")
    if "\n" in password or ":" in password:
        raise Fail("Password may not contain a colon or newline")

    tz = str(opts.get("timezone", "UTC")).strip() or "UTC"
    if not TZ_RE.fullmatch(tz) or ".." in tz:
        raise Fail(f"Invalid time zone {tz!r}")
    if not Path("/usr/share/zoneinfo", tz).exists():
        say(f"  ! unknown time zone {tz}, falling back to UTC")
        tz = "UTC"

    kb = str(opts.get("keyboard", "us")).strip() or "us"
    if not KB_RE.fullmatch(kb):
        raise Fail(f"Invalid keyboard layout {kb!r}")

    return {
        "disk": disk,
        "username": username,
        "hostname": hostname,
        "password": password,
        "timezone": tz,
        "keyboard": kb,
        "autologin": bool(opts.get("autologin", True)),
    }


def firmware_mode():
    return "uefi" if Path("/sys/firmware/efi").is_dir() else "bios"


def part_name(disk, index):
    # /dev/sda -> /dev/sda1 ; /dev/nvme0n1 -> /dev/nvme0n1p1
    return f"{disk}p{index}" if disk[-1].isdigit() else f"{disk}{index}"


def wait_for(path, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if Path(path).exists():
            return True
        time.sleep(0.3)
    return False


# ------------------------------------------------------------------ steps

def partition(disk, mode):
    emit(phase="Partitioning the disk", percent=8)

    sh(["wipefs", "-a", disk], check=False)
    sh(["sgdisk", "--zap-all", disk], check=False)

    if mode == "uefi":
        sh(["parted", "-s", disk, "mklabel", "gpt"])
        sh(["parted", "-s", disk, "mkpart", "ESP", "fat32", "1MiB", "513MiB"])
        sh(["parted", "-s", disk, "set", "1", "esp", "on"])
        sh(["parted", "-s", disk, "mkpart", "root", "ext4", "513MiB", "100%"])
        esp, root = part_name(disk, 1), part_name(disk, 2)
    else:
        # An MS-DOS label is what a fifteen-year-old BIOS expects; GPT on such
        # machines is a coin flip.
        sh(["parted", "-s", disk, "mklabel", "msdos"])
        sh(["parted", "-s", disk, "mkpart", "primary", "ext4", "1MiB", "100%"])
        sh(["parted", "-s", disk, "set", "1", "boot", "on"])
        esp, root = None, part_name(disk, 1)

    sh(["partprobe", disk], check=False)
    sh(["udevadm", "settle"], check=False)

    if not wait_for(root):
        raise Fail(f"Kernel did not present {root} after partitioning")
    if esp and not wait_for(esp):
        raise Fail(f"Kernel did not present {esp} after partitioning")

    return esp, root


def format_and_mount(esp, root):
    emit(phase="Creating filesystems", percent=12)
    sh(["mkfs.ext4", "-F", "-L", "webos-root", root])
    if esp:
        sh(["mkfs.vfat", "-F", "32", "-n", "WEBOS-EFI", esp])

    emit(phase="Mounting the target", percent=15)
    TARGET.mkdir(parents=True, exist_ok=True)
    sh(["mount", root, str(TARGET)])
    if esp:
        ESP_MOUNT.mkdir(parents=True, exist_ok=True)
        sh(["mount", esp, str(ESP_MOUNT)])


def copy_system():
    emit(phase="Copying the system", percent=20)

    args = ["rsync", "-aHAX", "--numeric-ids", "--info=progress2",
            "--no-inc-recursive"]
    for pattern in RSYNC_EXCLUDES:
        args += ["--exclude", pattern]
    args += ["/", str(TARGET) + "/"]

    say("  $ " + " ".join(args[:6]) + " … / /target/")

    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    last = -1
    buf = b""
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        buf += chunk
        # progress2 rewrites one line with \r, so split on both.
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for part in parts:
            text = part.decode("utf-8", "replace").strip()
            if not text:
                continue
            m = re.search(r"(\d{1,3})%", text)
            if m:
                pct = int(m.group(1))
                # rsync's 0-100 maps onto the 20-70 band of the overall job.
                scaled = 20 + int(pct * 0.5)
                if scaled != last:
                    last = scaled
                    emit(percent=scaled)
            elif "rsync:" in text or "error" in text.lower():
                say("    " + text)

    code = proc.wait()
    # 23 and 24 are "some files vanished / partial transfer", which is normal
    # when copying a running system.
    if code not in (0, 23, 24):
        raise Fail(f"rsync failed with status {code}")
    say("  system files copied")


def make_swap():
    emit(phase="Creating swap", percent=72)

    try:
        mem_kb = 0
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
        free = shutil.disk_usage(TARGET).free
    except (OSError, ValueError, IndexError):
        say("  ! could not size swap, skipping")
        return None

    size = min(max(mem_kb * 1024, 1024 ** 3), 4 * 1024 ** 3)
    if free < size + 4 * 1024 ** 3:
        say("  ! not enough free space for a swap file, skipping")
        return None

    swap = TARGET / "swapfile"
    code, _, _ = sh(["fallocate", "-l", str(size), str(swap)], check=False)
    if code != 0:
        sh(["dd", "if=/dev/zero", f"of={swap}", "bs=1M",
            f"count={size // (1024 ** 2)}", "status=none"])
    os.chmod(swap, 0o600)
    sh(["mkswap", str(swap)], quiet=True)
    say(f"  swap file: {size // (1024 ** 2)} MB")
    return "/swapfile"


def uuid_of(dev):
    code, out, _ = sh(["blkid", "-s", "UUID", "-o", "value", dev], quiet=True)
    uuid = out.strip()
    if not uuid:
        raise Fail(f"Could not read the UUID of {dev}")
    return uuid


def write_fstab(esp, root, swap):
    emit(phase="Writing fstab", percent=75)

    lines = [
        "# /etc/fstab — generated by the WebOS installer",
        "# <file system>                             <mount point>  <type>  <options>              <dump> <pass>",
        f"UUID={uuid_of(root)} /              ext4    errors=remount-ro,noatime 0      1",
    ]
    if esp:
        lines.append(
            f"UUID={uuid_of(esp)}                             /boot/efi      vfat    umask=0077                0      1"
        )
    if swap:
        lines.append(f"{swap}                                  none           swap    sw                        0      0")
    lines.append("tmpfs                                       /tmp           tmpfs   defaults,nosuid,nodev     0      0")

    (TARGET / "etc").mkdir(parents=True, exist_ok=True)
    (TARGET / "etc" / "fstab").write_text("\n".join(lines) + "\n")
    say("  fstab written")


def bind_mounts(mode, undo=False):
    binds = [("/dev", "dev"), ("/dev/pts", "dev/pts"), ("/proc", "proc"),
             ("/sys", "sys"), ("/run", "run")]
    if mode == "uefi" and Path("/sys/firmware/efi/efivars").is_dir():
        binds.append(("/sys/firmware/efi/efivars", "sys/firmware/efi/efivars"))

    if undo:
        for src, rel in reversed(binds):
            sh(["umount", "-l", str(TARGET / rel)], check=False, quiet=True)
        return

    for src, rel in binds:
        dest = TARGET / rel
        dest.mkdir(parents=True, exist_ok=True)
        sh(["mount", "--rbind", src, str(dest)], quiet=True)
        sh(["mount", "--make-rslave", str(dest)], check=False, quiet=True)


def configure(opts):
    emit(phase="Configuring the installed system", percent=80)

    hostname = opts["hostname"]
    user = opts["username"]

    (TARGET / "etc" / "hostname").write_text(hostname + "\n")
    (TARGET / "etc" / "hosts").write_text(
        "127.0.0.1\tlocalhost\n"
        f"127.0.1.1\t{hostname}\n"
        "::1\t\tlocalhost ip6-localhost ip6-loopback\n"
        "ff02::1\t\tip6-allnodes\n"
        "ff02::2\t\tip6-allrouters\n"
    )
    say(f"  hostname: {hostname}")

    # Time zone.
    tz_link = TARGET / "etc" / "localtime"
    if tz_link.exists() or tz_link.is_symlink():
        tz_link.unlink()
    tz_link.symlink_to(f"/usr/share/zoneinfo/{opts['timezone']}")
    (TARGET / "etc" / "timezone").write_text(opts["timezone"] + "\n")
    say(f"  time zone: {opts['timezone']}")

    # Keyboard.
    (TARGET / "etc" / "default" / "keyboard").write_text(
        'XKBMODEL="pc105"\n'
        f'XKBLAYOUT="{opts["keyboard"]}"\n'
        'XKBVARIANT=""\n'
        'XKBOPTIONS=""\n'
        'BACKSPACE="guess"\n'
    )
    say(f"  keyboard: {opts['keyboard']}")

    # The live image ships a "webos" account holding the kiosk configuration.
    # Renaming it keeps that configuration instead of building a fresh home.
    if user != "webos":
        sh(["usermod", "-l", user, "-d", f"/home/{user}", "-m", "webos"],
           chroot=True, check=False)
        sh(["groupmod", "-n", user, "webos"], chroot=True, check=False)
        say(f"  account renamed webos -> {user}")

    # Password, fed over stdin so it never appears in the process list.
    proc = subprocess.run(["chroot", str(TARGET), "chpasswd"],
                          input=f"{user}:{opts['password']}\n",
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise Fail(f"Could not set the password: {proc.stderr.strip()}")
    say("  password set")

    # Root stays locked; the user has sudo.
    sh(["passwd", "-l", "root"], chroot=True, check=False, quiet=True)

    # Autologin.
    dropin = TARGET / "etc" / "systemd" / "system" / "getty@tty1.service.d"
    dropin.mkdir(parents=True, exist_ok=True)
    autologin = dropin / "autologin.conf"
    if opts["autologin"]:
        autologin.write_text(
            "[Service]\n"
            "ExecStart=\n"
            f"ExecStart=-/sbin/agetty --noclear --autologin {user} %I $TERM\n"
        )
        say("  automatic login enabled")
    else:
        if autologin.exists():
            autologin.unlink()
        say("  automatic login disabled")

    # Identity that must differ from the live image.
    for rel in ("etc/machine-id", "var/lib/dbus/machine-id"):
        p = TARGET / rel
        try:
            if p.exists() or p.is_symlink():
                p.unlink()
        except OSError:
            pass
    (TARGET / "etc" / "machine-id").write_text("")

    for key in (TARGET / "etc" / "ssh").glob("ssh_host_*"):
        try:
            key.unlink()
        except OSError:
            pass

    # Mark the installation so the UI stops offering to install.
    release = TARGET / "etc" / "webos-release"
    try:
        text = release.read_text()
        if "INSTALLED=" not in text:
            release.write_text(text.rstrip() + "\nINSTALLED=yes\n")
    except OSError:
        pass


def install_bootloader(disk, mode):
    emit(phase="Installing the bootloader", percent=88)

    grub_default = TARGET / "etc" / "default" / "grub"
    grub_default.parent.mkdir(parents=True, exist_ok=True)
    grub_default.write_text(
        'GRUB_DEFAULT=0\n'
        'GRUB_TIMEOUT=3\n'
        'GRUB_DISTRIBUTOR="WebOS"\n'
        'GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"\n'
        'GRUB_CMDLINE_LINUX=""\n'
        'GRUB_TERMINAL_OUTPUT="gfxterm"\n'
        'GRUB_GFXMODE="auto"\n'
        'GRUB_DISABLE_RECOVERY="false"\n'
        'GRUB_DISABLE_OS_PROBER="false"\n'
    )

    if mode == "uefi":
        sh(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi",
            "--bootloader-id=WebOS", "--recheck"], chroot=True)
        # Old and cheap firmware routinely ignores or loses NVRAM entries.
        # The removable path (\EFI\BOOT\BOOTX64.EFI) is always tried, so write
        # it as well and the machine boots either way.
        sh(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi",
            "--bootloader-id=WebOS", "--removable", "--recheck"],
           chroot=True, check=False)
    else:
        sh(["grub-install", "--target=i386-pc", "--recheck", disk], chroot=True)

    emit(phase="Generating the boot menu", percent=92)
    sh(["update-grub"], chroot=True, check=False)

    emit(phase="Building the initramfs", percent=95)
    sh(["update-initramfs", "-u", "-k", "all"], chroot=True, check=False)


def cleanup(mode):
    bind_mounts(mode, undo=True)
    sh(["umount", "-l", str(ESP_MOUNT)], check=False, quiet=True)
    sh(["umount", "-l", str(TARGET)], check=False, quiet=True)
    sh(["sync"], check=False, quiet=True)


# ------------------------------------------------------------------- main

def cmd_install():
    raw = sys.stdin.read()
    try:
        opts = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise Fail(f"Bad options: {exc}")

    emit(phase="Checking the target", percent=4)
    opts = validate(opts)
    mode = firmware_mode()
    say(f"  target {opts['disk']}, firmware {mode.upper()}")

    for tool in ("parted", "mkfs.ext4", "rsync", "blkid", "lsblk"):
        if not shutil.which(tool):
            raise Fail(f"Required tool missing from the image: {tool}")
    if mode == "uefi" and not shutil.which("mkfs.vfat"):
        raise Fail("Required tool missing from the image: mkfs.vfat")

    if TARGET.is_mount():
        cleanup(mode)

    esp, root = partition(opts["disk"], mode)
    format_and_mount(esp, root)

    try:
        copy_system()
        swap = make_swap()
        write_fstab(esp, root, swap)
        bind_mounts(mode)
        configure(opts)
        install_bootloader(opts["disk"], mode)
    finally:
        emit(phase="Unmounting", percent=98)
        cleanup(mode)

    emit(phase="Complete", percent=100)
    say(f"WebOS is installed on {opts['disk']}.")


def main():
    if os.geteuid() != 0:
        say("error: webos-helper must run as root")
        return 1

    if len(sys.argv) < 2:
        say("usage: webos-helper install")
        return 2

    command = sys.argv[1]
    if command != "install":
        say(f"error: unknown command {command!r}")
        return 2

    try:
        cmd_install()
    except Fail as exc:
        say(f"error: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        say(f"error: unexpected failure: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
