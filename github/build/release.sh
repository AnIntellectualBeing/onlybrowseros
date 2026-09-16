#!/usr/bin/env bash
#
# Publish an OnlyBrowserOS update.
#
#   ./release.sh              build, sign, commit and push the update
#   ./release.sh --no-push    everything except the push (to look first)
#
# Updates live in a GitHub repository served by GitHub Pages
# ($OBOS_UPDATE_REPO, read by computers from $OBOS_UPDATE_URL). This script
# keeps a clone of it in build/updates-site, adds the new package, writes the
# signed package index that apt reads, and pushes. Every OnlyBrowserOS
# computer checks once a day and installs the update by itself.
#
# Needs: the signing key from make-signing-key.sh, gpg, git, gh (logged in)
# and apt-ftparchive (sudo apt install apt-utils).

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$HERE/config.sh"

die()  { printf '\033[31m  ✗  %s\033[0m\n' "$*" >&2; exit 1; }
info() { printf '    %s\n' "$*"; }

PUSH=1
case "${1:-}" in
  "") ;;
  --no-push) PUSH=0 ;;
  *) die "usage: $0 [--no-push]" ;;
esac

[[ $EUID -ne 0 ]] || die "run this as yourself, not with sudo (the signing key is in your keyring)"
for tool in gpg git apt-ftparchive dpkg-deb; do
  command -v "$tool" >/dev/null || die "$tool is missing"
done
KEYS="${OBOS_KEYS_DIR:-$HERE/keys}"
[[ -f "$KEYS/fingerprint" ]] || die "no signing key yet: run ./make-signing-key.sh you@example.com first"
FPR="$(cat "$KEYS/fingerprint")"
gpg --list-secret-keys "$FPR" >/dev/null 2>&1 || die "the signing key $FPR is not in this computer's keyring"

SITE="${OBOS_UPDATES_SITE:-$HERE/updates-site}"
if [[ ! -d "$SITE/.git" ]]; then
  command -v gh >/dev/null || die "gh is missing; clone $OBOS_UPDATE_REPO into $SITE by hand"
  info "fetching $OBOS_UPDATE_REPO"
  gh repo clone "$OBOS_UPDATE_REPO" "$SITE" || die "could not clone $OBOS_UPDATE_REPO (does it exist?)"
fi
if git -C "$SITE" remote get-url origin >/dev/null 2>&1 && git -C "$SITE" rev-parse -q --verify HEAD >/dev/null; then
  git -C "$SITE" pull --ff-only --quiet || die "could not update $SITE from GitHub"
fi

mkdir -p "$SITE/pool"
DEB="$("$HERE/make-package.sh" "$SITE/pool")"
VERSION="$(dpkg-deb -f "$DEB" Version)"
info "package $OBOS_ID $VERSION"

# Keep the three newest versions; apt always takes the newest. (To undo a bad
# update, fix it and release again: the fix gets a newer version.)
ls -1t "$SITE"/pool/"${OBOS_ID}"_*_all.deb | tail -n +4 | xargs -r git -C "$SITE" rm -q --ignore-unmatch --
ls -1t "$SITE"/pool/"${OBOS_ID}"_*_all.deb | tail -n +4 | xargs -r rm -f --

# The index apt reads: Packages lists the packages, Release their checksums,
# InRelease and Release.gpg the signature over it.
(
  cd "$SITE"
  apt-ftparchive packages pool > Packages
  gzip -9kf Packages
  tmp="$(mktemp)"
  apt-ftparchive \
    -o APT::FTPArchive::Release::Origin="$OBOS_NAME" \
    -o APT::FTPArchive::Release::Label="$OBOS_NAME" \
    -o APT::FTPArchive::Release::Suite=stable \
    -o APT::FTPArchive::Release::Codename=stable \
    release . > "$tmp"
  mv "$tmp" Release
  chmod 0644 Release
  gpg --yes --local-user "$FPR" --clearsign --output InRelease Release
  gpg --yes --local-user "$FPR" --armor --detach-sign --output Release.gpg Release
  cp "$KEYS/$OBOS_ID-archive.gpg" "$OBOS_ID-archive.gpg"
  touch .nojekyll    # GitHub Pages serves the files exactly as they are
)
info "index signed with $FPR"

git -C "$SITE" add -A
git -C "$SITE" commit -q -m "$OBOS_NAME update $VERSION" || die "nothing to commit"
if (( PUSH )); then
  git -C "$SITE" push -q || die "push failed; the update is committed in $SITE, push it by hand"
  printf '\n\033[32m  ✓  %s %s published\033[0m\n' "$OBOS_NAME" "$VERSION"
  info "computers pick it up within a day, from $OBOS_UPDATE_URL"
else
  printf '\n\033[32m  ✓  %s %s ready in %s (not pushed)\033[0m\n' "$OBOS_NAME" "$VERSION" "$SITE"
fi
