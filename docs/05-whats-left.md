# What's Left

My to-do list: what has to happen before updates work, what still needs
testing on real hardware, open decisions, and known gaps that aren't
blocking.

## Before my own updates work

The update mechanism (see `03-how-it-was-built.md`) is **built and tested
with a throwaway key, but not activated on the real release**. To turn it on:

1. **Create the real signing key** (one time, on my own machine, not as
   root):
   ```
   cd github/build
   ./make-signing-key.sh your@email
   ```
   It asks for a passphrase and then says to back up the private key to two
   separate offline USB sticks. **This matters: if the key is lost, no
   computer already sold or installed can ever receive another update.**
   Never commit the private key to git or share it.

2. **Create the public GitHub repo for updates** (already named
   `AnIntellectualBeing/onlybrowseros-updates` in `build/config.sh` —
   `OBOS_UPDATE_REPO` / `OBOS_UPDATE_URL`):
   ```
   gh repo create AnIntellectualBeing/onlybrowseros-updates --public --add-readme
   ```
   Then turn on GitHub Pages for it: repo Settings → Pages → Deploy from
   branch → `main`, `/ (root)`.

3. **Rebuild the ISO** after step 1 exists — the build script only bakes in
   the update URL and public key if it finds a key in `build/keys/`. Any ISO
   built before this (including v1.1 and v1.2) only gets Debian
   security patches, not OnlyBrowserOS updates.

4. **For every future release**, from then on:
   ```
   cd github/build
   ./release.sh
   ```

## Needs real-hardware testing

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
- **v1.2 hardware features, untested on real hardware:** Bluetooth
  headphones actually playing sound, the volume/brightness key overlay,
  plugging in an HDMI TV/projector (should mirror), the screen switching off
  after 10 idle minutes but staying on during a video, a short power-button
  press sleeping and a long press shutting down, and the "RAID / Intel RST"
  message in the installer on laptops whose disk is hidden that way.
- Try it on the **lowest-spec machine I can get** — 1GB of RAM if I can
  find one — since that's the hardest case the "Low-end PC" tier is meant to
  handle.

## Decisions still open

- **Trademark check was a web search only, not a legal one.** Before
  selling or publicly shipping under the name "OnlyBrowserOS," search the
  official trademark databases (USPTO, EUIPO TMview, WIPO Global Brand
  Database) or talk to a trademark lawyer. The closest existing name found
  was "BrowserOS" (an unrelated AI browser project) — worth a specific look.
- **Legal pages** (privacy policy, terms, license) — deferred
  for now. Needed before any public release with real
  users.
- **Language** — English only for now. No i18n/translation
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
- On a very slow first start, Firefox can take minutes to install the
  OnlyBrowserOS extension. The tab limit ignores tabs opened in the
  extension's first 10 seconds (so a restored session is never closed), so a
  tab opened right then gets through: one extra tab until the user closes
  one. Seen once in four 1 GB test runs (v1.2), under software emulation.
- A downloaded test PDF appeared twice in one test run (`report.pdf` and
  `report-1.pdf`) — Firefox's own "don't overwrite" renaming, most likely,
  but not investigated further.
- Work or school Wi-Fi that requires a username as well as a password
  (802.1X) is not supported yet — the network menu will tell the user this
  rather than silently failing.
- Bluetooth pairing with a code (v1.2): keyboards show "type 123456 on the
  device", phones are confirmed automatically. Only tested against a fake
  `bluetoothctl` (QEMU has no Bluetooth) — try a real keyboard and phone.
- No CJK (Chinese/Japanese/Korean) fonts are included, to keep the image
  size down — those languages will show as missing-glyph boxes.
- Firefox's own emergency escape hatches (some keyboard shortcuts,
  `about:preferences` typed directly into the address bar) may still reach
  hidden functionality even though the menu items leading to them are
  hidden. The menu paths are blocked; the underlying pages themselves are
  not.

## Where to start when coming back to this

1. `docs/02-how-it-works.md` — the architecture
2. this file — what is outstanding
3. `git log` — what changed since this file was last updated
