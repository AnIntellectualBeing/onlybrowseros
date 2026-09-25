#!/usr/bin/env bash
#
# Build the OnlyBrowserOS package: every OnlyBrowserOS file that goes into the
# system (taskbar, installer, home screen, start page, settings, browser set-up
# and system configuration) as one Debian package.
#
#   ./make-package.sh [OUTPUT_DIR]     -> OUTPUT_DIR/onlybrowseros_<version>_all.deb
#
# build-iso.sh installs this package into the image, and release.sh publishes
# new versions of it as updates. The version is OBOS_VERSION plus the build
# time (1.0.202609161030), so every build is newer than the one before and
# computers take it as an update. Needs no root.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
SRC="$REPO/src"
# shellcheck source=config.sh
source "$HERE/config.sh"

OUT="${1:-$HERE/out}"
VERSION="${OBOS_PACKAGE_VERSION:-$OBOS_VERSION.$(date -u +%Y%m%d%H%M)}"
LIB="usr/lib/$OBOS_ID"

die() { printf '\033[31m  ✗  %s\033[0m\n' "$*" >&2; exit 1; }
command -v dpkg-deb >/dev/null || die "dpkg-deb is missing (sudo apt install dpkg)"
command -v python3 >/dev/null || die "python3 is missing"

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

put() {  # put MODE SOURCE DEST (DEST relative to the package root)
  install -D -m "$1" "$2" "$ROOT/$3"
}

# ------------------------------------------------------------- programs
for dir in shared panel home installer; do
  for file in "$SRC/$dir"/*.py; do
    put 0644 "$file" "$LIB/$dir/$(basename "$file")"
  done
done
for tool in tune set-tab-limit settings-host system-setting usb-mount autotest; do
  put 0755 "$SRC/system/$tool" "$LIB/$tool"
done
put 0755 "$SRC/installer/install-helper" "$LIB/install-helper"
put 0755 "$SRC/session/autostart" "$LIB/autostart"
put 0755 "$SRC/session/browser" "$LIB/browser"
put 0755 "$SRC/session/media-key" "$LIB/media-key"
put 0755 "$SRC/session/onlybrowseros-session" "usr/bin/onlybrowseros-session"

# ------------------------------------------------------------ the browser
# The start page gets the landscape drawn by the same code as the home screen.
install -d "$ROOT/usr/share/$OBOS_ID/start"
python3 "$SRC/shared/landscape.py" --page "$SRC/start/index.html" > "$ROOT/usr/share/$OBOS_ID/start/index.html"
chmod 0644 "$ROOT/usr/share/$OBOS_ID/start/index.html"
put 0644 "$SRC/start/downloads.html" "usr/share/$OBOS_ID/start/downloads.html"
put 0644 "$SRC/firefox/autoconfig.js" "usr/lib/firefox-esr/defaults/pref/autoconfig.js"
put 0644 "$SRC/firefox/onlybrowseros.cfg" "usr/lib/firefox-esr/onlybrowseros.cfg"
put 0644 "$SRC/firefox/native-host.json" "usr/lib/mozilla/native-messaging-hosts/onlybrowseros.settings.json"

# A Firefox extension is a zip with manifest.json at its root.
python3 - "$SRC/firefox/tablimit" "$ROOT/$LIB/tablimit.xpi" <<'PY'
import sys, zipfile, pathlib
src, out = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(src.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(src).as_posix())
PY
chmod 0644 "$ROOT/$LIB/tablimit.xpi"

# ---------------------------------------------------- system configuration
# Everything in build/overlay except what only the USB stick may have: the
# permission to erase disks, which the installer removes from installed
# computers and an update must never bring back.
(cd "$HERE/overlay" && find . -type f ! -path "./etc/sudoers.d/$OBOS_ID-live") | while read -r file; do
  mode=0644
  case "$file" in
    ./etc/sudoers.d/*) mode=0440 ;;
  esac
  put "$mode" "$HERE/overlay/$file" "${file#./}"
done

# --------------------------------------------------------------- metadata
install -d "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $OBOS_ID
Version: $VERSION
Architecture: all
Maintainer: $OBOS_NAME <updates@$OBOS_ID.invalid>
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, firefox-esr, openbox, sudo
Section: misc
Priority: optional
Description: $OBOS_NAME: the computer that is only a browser
 The taskbar, installer, home screen, start page, settings and browser
 set-up of $OBOS_NAME.
EOF

# The files in /etc are deliberately not marked as configuration files: nobody
# edits them by hand on these computers, and an update must be able to change
# them without asking.
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    systemctl enable onlybrowseros-tune.service onlybrowseros-autotest.service >/dev/null 2>&1 || true
    # On a running computer (not while the image is built): rewrite the browser
    # settings now, so the next browser start uses what the update brought.
    if [ -d /run/systemd/system ]; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        udevadm control --reload >/dev/null 2>&1 || true
        /usr/lib/onlybrowseros/tune >/dev/null 2>&1 || true
    fi
fi
exit 0
EOF
chmod 0755 "$ROOT/DEBIAN/postinst"

# visudo refuses a broken sudoers file before it can lock anyone out.
if command -v visudo >/dev/null; then
  for file in "$ROOT"/etc/sudoers.d/*; do
    visudo -cqf "$file" || die "invalid sudoers file: ${file#$ROOT/}"
  done
fi

mkdir -p "$OUT"
DEB="$OUT/${OBOS_ID}_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$DEB" >/dev/null
echo "$DEB"
