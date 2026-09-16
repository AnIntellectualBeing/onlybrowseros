#!/usr/bin/env bash
#
# Try OnlyBrowserOS in a QEMU virtual machine.
#
# By hand (a window, or VNC on localhost:5901 when QEMU has no display support):
#   ./test-iso.sh                  boot the live ISO
#   ./test-iso.sh --install        boot the live ISO with an empty 20 GB disk to install onto
#   ./test-iso.sh --boot-disk      start what was installed on that disk
#
# Automatic (no window; serial logs and screenshots land in build/test/):
#   ./test-iso.sh --auto-live      boot the live ISO, wait for the desktop, print a health report
#   ./test-iso.sh --auto-install   install onto a fresh disk, start it, print a health report
#
# Options:
#   --uefi          UEFI firmware instead of BIOS
#   --secureboot    UEFI with Secure Boot on (Microsoft keys, as on shop-bought
#                   laptops); boots through shim and the signed GRUB and kernel
#   --ram MB        memory for the VM (default 2048; try 1024 to feel a 1 GB laptop)
#   --timeout MIN   how long an automatic step may take (default 60)
#
# VirtualBox works just as well by hand: a new "Debian (64-bit)" VM with the ISO attached.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$HERE/config.sh"

ISO="${ISO:-$HERE/out/${OBOS_ID}-${OBOS_VERSION}-${OBOS_ARCH}.iso}"
TEST="$HERE/test"
DISK="$TEST/disk.qcow2"
KERNEL="$HERE/work/iso/live/vmlinuz"
INITRD="$HERE/work/iso/live/initrd.img"

MODE=live
RAM=2048
UEFI=0
SECUREBOOT=0
TIMEOUT=60

die()  { printf '\033[31m  ✗  %s\033[0m\n' "$*" >&2; exit 1; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m  !  %s\033[0m\n' "$*" >&2; }

while (( $# )); do
  case "$1" in
    --install)      MODE=install; shift ;;
    --boot-disk)    MODE=disk; shift ;;
    --auto-live)    MODE=auto-live; shift ;;
    --auto-install) MODE=auto-install; shift ;;
    --uefi)         UEFI=1; shift ;;
    --secureboot)   UEFI=1; SECUREBOOT=1; shift ;;
    --ram)          RAM="${2:?}"; shift 2 ;;
    --timeout)      TIMEOUT="${2:?}"; shift 2 ;;
    -h|--help)      sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              die "unknown option: $1" ;;
  esac
done

command -v qemu-system-x86_64 >/dev/null || die "QEMU is missing: sudo apt install qemu-system-x86 qemu-utils ovmf"
mkdir -p "$TEST"

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  ACCEL=(-accel kvm -cpu host)
  EXTRA_KERNEL_ARGS=""
else
  # One emulation thread: QEMU 8.2's multi-threaded emulation segfaults now
  # and then (seen under both BIOS and UEFI).
  ACCEL=(-accel tcg,thread=single -cpu max)
  # Under software emulation on a busy host the kernel's early timer check can
  # fail and panic ("IO-APIC + timer doesn't work"); skip that check.
  EXTRA_KERNEL_ARGS="no_timer_check"
  warn "no hardware virtualisation here: the VM runs in software emulation and is slow"
fi
SMP=$(( $(nproc) > 4 ? 4 : $(nproc) ))
MONITOR="$TEST/monitor.sock"
MACHINE=q35

FIRMWARE=()
VARS="$TEST/uefi-vars.fd"
VARS_TEMPLATE=""
if (( SECUREBOOT )); then
  # Secure Boot enforcing firmware with Microsoft's keys enrolled; it needs
  # the emulated SMM mode that real laptops have.
  code=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd
  VARS_TEMPLATE=/usr/share/OVMF/OVMF_VARS_4M.ms.fd
  [[ -f "$code" && -f "$VARS_TEMPLATE" ]] || die "Secure Boot firmware is missing: sudo apt install ovmf"
  VARS="$TEST/uefi-vars-secureboot.fd"
  MACHINE=q35,smm=on
  [[ -f "$VARS" ]] || cp "$VARS_TEMPLATE" "$VARS"
  FIRMWARE=(-global driver=cfi.pflash01,property=secure,value=on
            -drive "if=pflash,format=raw,readonly=on,file=$code" -drive "if=pflash,format=raw,file=$VARS")
elif (( UEFI )); then
  code=""
  for candidate in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd; do
    if [[ -f "$candidate" && -f "${candidate/CODE/VARS}" ]]; then
      code="$candidate"
      VARS_TEMPLATE="${candidate/CODE/VARS}"
      break
    fi
  done
  [[ -n "$code" ]] || die "UEFI firmware is missing: sudo apt install ovmf"
  # The firmware's boot entries live next to the disk they point at.
  [[ -f "$VARS" ]] || cp "$VARS_TEMPLATE" "$VARS"
  FIRMWARE=(-drive "if=pflash,format=raw,readonly=on,file=$code" -drive "if=pflash,format=raw,file=$VARS")
fi
if (( UEFI )) && [[ "${ACCEL[1]}" == tcg,* ]]; then
  # QEMU 8.2's multi-threaded emulation crashes now and then (general
  # protection fault inside QEMU) while running the UEFI firmware; one
  # emulation thread avoids it and boots no slower.
  ACCEL=(-accel tcg,thread=single -cpu max)
fi

QEMU=(qemu-system-x86_64 -name "$OBOS_NAME test" -machine "$MACHINE" "${ACCEL[@]}" -smp "$SMP" -m "$RAM"
      -vga std
      -audiodev none,id=snd0 -device ich9-intel-hda -device hda-duplex,audiodev=snd0
      -nic user,model=virtio-net-pci
      -device qemu-xhci -device usb-tablet
      -monitor "unix:$MONITOR,server,nowait"
      "${FIRMWARE[@]}")

# cache=none: the VM reads and writes its images directly, instead of filling
# the host's memory with file cache while it installs.
CDROM=(-drive "file=$ISO,media=cdrom,readonly=on,cache=none")
HDD=(-drive "file=$DISK,if=virtio,format=qcow2,cache=none")

monitor() {
  python3 - "$MONITOR" "$1" <<'PY'
import socket, sys, time
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1])
except OSError:
    sys.exit(0)
time.sleep(0.3)
s.recv(65536)
s.sendall((sys.argv[2] + "\n").encode())
time.sleep(1.5)
s.close()
PY
}

fresh_disk() {
  rm -f "$DISK" "$VARS"
  # A new disk gets new firmware settings, so no stale boot entry points at it.
  if (( UEFI )); then cp "$VARS_TEMPLATE" "$VARS"; fi
  qemu-img create -q -f qcow2 "$DISK" 20G
  info "new empty disk: $DISK"
}

display_args() {
  if qemu-system-x86_64 -display help 2>/dev/null | grep -qw gtk; then
    DISPLAY_ARGS=(-display gtk)
  elif qemu-system-x86_64 -display help 2>/dev/null | grep -qw sdl; then
    DISPLAY_ARGS=(-display sdl)
  else
    DISPLAY_ARGS=(-display none -vnc 127.0.0.1:1)
    info "no QEMU window support: connect a VNC viewer to localhost:5901"
  fi
}

# With Secure Boot the firmware must start the ISO itself (shim, signed GRUB,
# signed kernel), so the kernel cannot be handed to QEMU directly. Instead a
# copy of the ISO gets the test's kernel arguments in its boot menu.
# live_boot <autotest mode> -> sets LIVE_BOOT to the QEMU arguments.
live_boot() {
  local args="console=tty0 console=ttyS0,115200 obos.autotest=$1 $EXTRA_KERNEL_ARGS"
  if (( ! SECUREBOOT )); then
    LIVE_BOOT=("${CDROM[@]}" -kernel "$KERNEL" -initrd "$INITRD" -append "boot=live quiet $args")
    return
  fi
  local cfg="$TEST/grub-$1.cfg" copy="$TEST/secureboot-$1.iso"
  rm -f "$cfg" "$copy"
  xorriso -osirrox on -indev "$ISO" -extract /boot/grub/grub.cfg "$cfg" >/dev/null 2>&1 \
    || die "could not read the boot menu from $ISO"
  chmod u+w "$cfg"
  sed -i -e "0,/linux  \/live\/vmlinuz boot=live /s//linux  \/live\/vmlinuz boot=live $args /" \
         -e 's/^set timeout=5/set timeout=1/' "$cfg"
  grep -q "obos.autotest=$1" "$cfg" || die "could not add the test arguments to the boot menu"
  xorriso -indev "$ISO" -outdev "$copy" -boot_image any replay \
    -update "$cfg" /boot/grub/grub.cfg >/dev/null 2>&1 || die "could not make the Secure Boot test ISO"
  LIVE_BOOT=(-drive "file=$copy,media=cdrom,readonly=on,cache=none" -boot d)
}

# wait_for <serial log> <text> <qemu pid>: 0 found, 1 timed out, 2 VM stopped
wait_for() {
  local log="$1" text="$2" pid="$3" deadline=$(( $(date +%s) + TIMEOUT * 60 ))
  while (( $(date +%s) < deadline )); do
    grep -q "$text" "$log" 2>/dev/null && return 0
    kill -0 "$pid" 2>/dev/null || { grep -q "$text" "$log" 2>/dev/null && return 0; return 2; }
    sleep 10
  done
  return 1
}

show_report() {
  local log="$1"
  printf '\n'
  grep -aE '^OBOS-AUTOTEST:|^  \|' "$log" | tail -n 120 || true
  printf '\n'
}

stop_vm() {
  local pid="$1"
  monitor quit
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || return 0; sleep 1; done
  kill "$pid" 2>/dev/null || true
}

need_iso()    { [[ -f "$ISO" ]] || die "no ISO at $ISO (run: sudo ./build-iso.sh)"; }
need_kernel() { [[ -f "$KERNEL" && -f "$INITRD" ]] || die "no kernel in $HERE/work/iso/live (run the build first)"; }
firmware_tag() { if (( SECUREBOOT )); then echo secureboot; elif (( UEFI )); then echo uefi; else echo bios; fi; }

case "$MODE" in
  live)
    need_iso; display_args
    exec "${QEMU[@]}" "${DISPLAY_ARGS[@]}" "${CDROM[@]}" -boot d
    ;;

  install)
    need_iso; display_args
    [[ -f "$DISK" ]] || fresh_disk
    info "installing onto $DISK (delete it to start over)"
    exec "${QEMU[@]}" "${DISPLAY_ARGS[@]}" "${HDD[@]}" "${CDROM[@]}" -boot d
    ;;

  disk)
    [[ -f "$DISK" ]] || die "no installed disk yet (run --install or --auto-install first)"
    display_args
    exec "${QEMU[@]}" "${DISPLAY_ARGS[@]}" "${HDD[@]}"
    ;;

  auto-live)
    need_iso; need_kernel
    tag="live-$(firmware_tag)-${RAM}mb"
    log="$TEST/serial-$tag.log"; : > "$log"
    live_boot report
    info "booting the live system ($tag); waiting up to $TIMEOUT min for the desktop"
    "${QEMU[@]}" -display none -serial "file:$log" "${LIVE_BOOT[@]}" &
    pid=$!
    result=0
    # The browser has settled on its start page by the first memory report.
    if wait_for "$log" "OBOS-AUTOTEST: MEMORY at rest" "$pid"; then
      monitor "screendump $TEST/$tag-start.png -f png"
    fi
    wait_for "$log" "OBOS-AUTOTEST: REPORT DONE" "$pid" || result=$?
    monitor "screendump $TEST/$tag.png -f png"
    stop_vm "$pid"
    show_report "$log"
    info "screenshot: $TEST/$tag.png   serial log: $log"
    case $result in
      0) printf '\033[32m  ✓  live system started and reported\033[0m\n' ;;
      1) die "timed out after $TIMEOUT min" ;;
      *) die "the VM stopped before reporting" ;;
    esac
    ;;

  auto-install)
    need_iso; need_kernel
    fresh_disk
    tag="$(firmware_tag)-${RAM}mb"
    log="$TEST/serial-install-$tag.log"; : > "$log"
    live_boot install
    info "step 1/2: installing from the live system ($tag); up to $TIMEOUT min"
    "${QEMU[@]}" -display none -serial "file:$log" "${HDD[@]}" "${LIVE_BOOT[@]}" &
    pid=$!
    deadline=$(( $(date +%s) + TIMEOUT * 60 ))
    while kill -0 "$pid" 2>/dev/null && (( $(date +%s) < deadline )); do sleep 10; done
    if kill -0 "$pid" 2>/dev/null; then
      monitor "screendump $TEST/install-$tag-timeout.png -f png"
      stop_vm "$pid"
      show_report "$log"
      die "the install did not finish within $TIMEOUT min"
    fi
    show_report "$log"
    grep -q "OBOS-AUTOTEST: INSTALL OK" "$log" || die "the install failed; see $log"
    printf '\033[32m  ✓  installed\033[0m\n'

    log2="$TEST/serial-installed-$tag.log"; : > "$log2"
    info "step 2/2: starting the installed disk; up to $TIMEOUT min"
    "${QEMU[@]}" -display none -serial "file:$log2" "${HDD[@]}" &
    pid=$!
    result=0
    if wait_for "$log2" "OBOS-AUTOTEST: MEMORY at rest" "$pid"; then
      monitor "screendump $TEST/installed-$tag-start.png -f png"
    fi
    wait_for "$log2" "OBOS-AUTOTEST: REPORT DONE" "$pid" || result=$?
    monitor "screendump $TEST/installed-$tag.png -f png"
    stop_vm "$pid"
    show_report "$log2"
    info "screenshot: $TEST/installed-$tag.png   serial logs: $log $log2"
    case $result in
      0) printf '\033[32m  ✓  installed system started and reported\033[0m\n' ;;
      1) die "the installed system did not report within $TIMEOUT min" ;;
      *) die "the installed system stopped before reporting" ;;
    esac
    ;;
esac
