# MyOS — the course example

A small operating system built from nothing: Debian 13 underneath, it logs in
by itself and opens Firefox full screen above a bar with a clock and a power
button.

The course that explains every line is
[`docs/10-make-your-own-os.md`](../10-make-your-own-os.md).

```
sudo apt install debootstrap squashfs-tools xorriso mtools grub-pc-bin \
     grub-efi-amd64-bin grub-common dpkg-dev debian-archive-keyring qemu-system-x86 ovmf
sudo ./build.sh          # all lessons → out/myos.iso  (downloads ~1 GB)
./test.sh                # start it in a virtual PC
```

| File | What it is |
|---|---|
| `build.sh` | Lessons 1–9 as functions, then `make_iso`. `--to N` stops after a lesson, `--from N` redoes from a lesson, `--iso` only repacks |
| `grub.cfg` | The boot menu |
| `packages/myos-desktop/` | Your own desktop as a Debian package: session, bar (`bar.py`), window rules |
| `packages/myos-browser/` | Firefox policies and the start page, as a second package |
| `test.sh` | QEMU: `--uefi`, `--serial`, `RAM=1024` |

`work/` (the system being built) and `out/` (the ISO) are created by the
build and are not in git.
