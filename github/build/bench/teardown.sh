#!/bin/bash
# Unmount the bench; its changes (build/bench/upper) are thrown away.
B="$(cd "$(dirname "$0")" && pwd)"
R="$B/root"
for m in tmp/.X11-unix run dev/pts dev sys proc ""; do umount -l "$R/$m" 2>/dev/null; done
rm -rf "$B/upper" "$B/work"
echo "bench removed"
