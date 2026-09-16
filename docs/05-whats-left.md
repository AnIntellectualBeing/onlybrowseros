# What's Left

This session is ending. This file is the handoff: what you need to provide
or decide, what a future session should verify before shipping, and known
gaps that exist but aren't blocking.

## You need to do these before updates work

The update mechanism (see `03-how-it-was-built.md`) is **built and tested
with a throwaway key, but not activated on the real release**. To turn it on:

1. **Create the real signing key** (one time, on your own machine, not as
   root):
   ```
   cd github/build
   ./make-signing-key.sh your@email
   ```
   It will ask for a passphrase and then tell you to back up the private key
   to two separate offline USB sticks. **Do this — if the key is lost, no
   computer already sold or installed can ever receive another update.**
   Never commit the private key to git or share it.

2. **Create the public GitHub repo for updates** (I referenced it as
   `AnIntellectualBeing/onlybrowseros-updates` in `build/config.sh` —
   `OBOS_UPDATE_REPO` / `OBOS_UPDATE_URL` — but never created it, since it's
   a public repo and that was your call to make):
   ```
   gh repo create AnIntellectualBeing/onlybrowseros-updates --public --add-readme
   ```
   Then turn on GitHub Pages for it: repo Settings → Pages → Deploy from
   branch → `main`, `/ (root)`.

3. **Rebuild the ISO** after step 1 exists — the build script only bakes in
   the update URL and public key if it finds a key in `build/keys/`. Any ISO
   built before this (including the current v1.1 release) only gets Debian
   security patches, not OnlyBrowserOS updates.

4. **For every future release**, from then on:
   ```
   cd github/build
   ./release.sh
   ```

## Needs real-hardware testing (nothing here has touched real hardware yet)

Everything so far has been tested in QEMU (a virtual machine), which proves
the software logic works but can't fully validate real-world hardware
behavior. Before shipping to actual people:

- **Boot the USB stick on a real laptop.** Confirm it starts, Wi-Fi works,
  and Secure Boot really does stay on (QEMU's Secure Boot emulation is
  solid but real firmware from various manufacturers can behave
  differently).
- **Battery warnings** — QEMU has no battery to simulate draining; the
  10%/5%/3% warning thresholds and the safe-shutdown countdown have only
  been checked by directly calling the code with fake battery values, not by
  watching a real battery actually drain.
- **Printing to a real printer** — the automated test only confirms CUPS
  starts up correctly; nobody has printed an actual page yet. Test both a
  Wi-Fi printer and a USB printer if possible.
- **Install onto a real disk**, not just a QEMU virtual disk — disk timing
  and quirks vary a lot between real SSDs/HDDs and QEMU's virtio disk.
- Try it on the **lowest-spec machine you have** — 1GB of RAM if you can
  find one — since that's the hardest case the "Low-end PC" tier is meant to
  handle.

## Decisions still open (need your input)

- **Trademark check was a web search only, not a legal one.** Before
  selling or publicly shipping under the name "OnlyBrowserOS," search the
  official trademark databases (USPTO, EUIPO TMview, WIPO Global Brand
  Database) or talk to a trademark lawyer. The closest existing name found
  was "BrowserOS" (an unrelated AI browser project) — worth a specific look.
- **Legal pages** (privacy policy, terms, license) — deliberately deferred,
  per your earlier decision. Needed before any public release with real
  users.
- **Language** — English only, per your decision. No i18n/translation
  infrastructure exists yet; if that changes later, every user-facing string
  in the Python files, the extension, and the HTML pages would need to be
  extracted into a translation system.

## Known gaps (not blocking, but worth knowing about)

- One line in the automated test report incorrectly said "Secure Boot off"
  even during a run where Secure Boot enforcement was independently
  confirmed to be working (a separate manual test showed the firmware
  correctly refusing an unsigned boot loader with "Access Denied"). The
  detection logic in `src/system/autotest` was fixed afterward, but that fix
  itself hasn't been re-run through the full automated test yet.
- A downloaded test PDF appeared twice in one test run (`report.pdf` and
  `report-1.pdf`) — Firefox's own "don't overwrite" renaming, most likely,
  but not investigated further.
- Work or school Wi-Fi that requires a username as well as a password
  (802.1X) is not supported yet — the network menu will tell the user this
  rather than silently failing.
- Bluetooth devices that require typing a pairing code (some keyboards) are
  not supported yet; headphones, speakers, and mice (which don't need a
  code) work fine.
- No CJK (Chinese/Japanese/Korean) fonts are included, to keep the image
  size down — those languages will show as missing-glyph boxes.
- Firefox's own emergency escape hatches (some keyboard shortcuts,
  `about:preferences` typed directly into the address bar) may still reach
  hidden functionality even though the menu items leading to them are
  hidden. The menu paths are blocked; the underlying pages themselves are
  not.

## Where to pick this up next session

Read the files in this order if you're a new session picking this project
back up:
1. `docs/README.md` (this index)
2. `docs/02-how-it-works.md` — understand the architecture before touching
   code
3. This file, to see what's outstanding
4. Then check `git log` for the most recent commits to see what's changed
   since this file was written — **this file describes the state as of the
   `onlybrowseros-v1.1` release; it will go stale as more work happens.**

The project's memory files (used by the Claude Code session, not part of the
git repo) also track decisions and context — check
`~/.claude/projects/-home-vboxuser-Documents-projects-webos/memory/` if
continuing in the same Claude Code environment.
