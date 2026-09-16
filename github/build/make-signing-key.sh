#!/usr/bin/env bash
#
# Create the key that signs OnlyBrowserOS updates. Run it ONCE, as yourself
# (not with sudo):
#
#   ./make-signing-key.sh you@example.com
#
# It asks for a passphrase; release.sh asks for it again each time you publish.
#
# The key proves an update really comes from you. Computers built after this
# carry its public half and accept only updates signed with it. So:
#   - Back up the private key (the script tells you how) on two USB sticks you
#     keep offline. Lost key = no more updates for computers already out there.
#   - Never share it, never commit it to git. Whoever has it can put anything
#     on every OnlyBrowserOS computer.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$HERE/config.sh"

die() { printf '\033[31m  ✗  %s\033[0m\n' "$*" >&2; exit 1; }

EMAIL="${1:-}"
[[ "$EMAIL" == *@* ]] || die "usage: $0 you@example.com"
[[ $EUID -ne 0 ]] || die "run this as yourself, not with sudo: the key belongs in your own keyring"
command -v gpg >/dev/null || die "gpg is missing (sudo apt install gnupg)"

KEYS="${OBOS_KEYS_DIR:-$HERE/keys}"
UID_TEXT="$OBOS_NAME Updates <$EMAIL>"
if [[ -f "$KEYS/fingerprint" ]]; then
  die "a signing key already exists ($(cat "$KEYS/fingerprint")). Making a second one would lock out computers that trust the first."
fi

echo "Creating the $OBOS_NAME update signing key for $EMAIL."
echo "Choose a strong passphrase and write it down somewhere safe."
gpg --quick-generate-key "$UID_TEXT" ed25519 sign never

FPR="$(gpg --with-colons --list-secret-keys "$UID_TEXT" | awk -F: '/^fpr:/ {print $10; exit}')"
[[ -n "$FPR" ]] || die "gpg did not create the key"

mkdir -p "$KEYS"
gpg --export "$FPR" > "$KEYS/$OBOS_ID-archive.gpg"
echo "$FPR" > "$KEYS/fingerprint"

cat <<EOF

  ✓  Signing key created: $FPR

     Public key (goes into every ISO): $KEYS/$OBOS_ID-archive.gpg

  NOW back up the private key. Run:

     gpg --export-secret-keys --armor $FPR > $OBOS_ID-signing-key-BACKUP.asc

  copy that file to two USB sticks kept in different safe places, then delete
  it from this computer. Keep the passphrase with them.

  gpg also saved a revocation certificate in ~/.gnupg/openpgp-revocs.d/ (use it
  only if the key is ever stolen); back that up the same way.
EOF
