#!/bin/bash
# Memory bench: a throwaway copy-on-write root over the built image
# (build/work/chroot), where Firefox can be measured natively.
#   sudo ./setup.sh ; Xvfb :90 -screen 0 1366x768x24 &
#   sudo ./run.sh NAME '{"some.pref": value}'      one measurement, offline
#   sudo ./teardown.sh                              before the next build
# See docs/08-memory.md.
set -e
B="$(cd "$(dirname "$0")" && pwd)"
LOWER="$B/../work/chroot"
R="$B/root"
[[ -d "$LOWER/usr/lib/firefox-esr" ]] || { echo "build the image first (build-iso.sh)"; exit 1; }
mkdir -p "$B/upper" "$B/work" "$R"
mountpoint -q "$R" || mount -t overlay overlay -o "lowerdir=$LOWER,upperdir=$B/upper,workdir=$B/work" "$R"
for m in proc sys dev dev/pts; do mountpoint -q "$R/$m" || mount --bind "/$m" "$R/$m"; done
mountpoint -q "$R/run" || mount -t tmpfs tmpfs "$R/run"
mkdir -p "$R/run/NetworkManager" "$R/run/onlybrowseros" "$R/tmp/.X11-unix"
cp -L /etc/resolv.conf "$R/run/NetworkManager/resolv.conf"
mountpoint -q "$R/tmp/.X11-unix" || mount --bind /tmp/.X11-unix "$R/tmp/.X11-unix"
echo "bench ready at $R"
