#!/usr/bin/env bash
#
# Start out/myos.iso in a virtual PC (QEMU).
#
#   ./test.sh              a window, like a real screen, BIOS, 2 GB RAM
#   ./test.sh --uefi       the same with UEFI firmware
#   ./test.sh --serial     no window: the text console in this terminal
#                          (quit with Ctrl+A then X)
#   RAM=1024 ./test.sh     pretend to be a 1 GB laptop
#
# Needs: sudo apt install qemu-system-x86 ovmf

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ISO="${ISO:-$HERE/out/myos.iso}"
RAM="${RAM:-2048}"

args=(-m "$RAM" -smp 2 -cdrom "$ISO" -boot d -vga std
      -netdev user,id=n0 -device virtio-net-pci,netdev=n0)

# KVM makes the virtual PC as fast as the real one. Inside another VM
# (VirtualBox) there is usually no KVM, and QEMU emulates the CPU: slower.
if [[ -w /dev/kvm ]]; then args+=(-accel kvm -cpu host); else args+=(-accel tcg -cpu max); fi

for a in "$@"; do
  case "$a" in
    --uefi)
      cp -n /usr/share/OVMF/OVMF_VARS_4M.fd "$HERE/out/uefi-vars.fd"
      args+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
             -drive if=pflash,format=raw,file="$HERE/out/uefi-vars.fd") ;;
    --serial)
      # Start the kernel directly so it can be told to use the serial port.
      args+=(-nographic -kernel "$HERE/work/iso/live/vmlinuz" -initrd "$HERE/work/iso/live/initrd.img"
             -append "boot=live console=tty0 console=ttyS0,115200") ;;
    *) sed -n '3,11p' "$0"; exit 1 ;;
  esac
done

exec qemu-system-x86_64 "${args[@]}"
