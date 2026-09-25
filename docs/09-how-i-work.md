# How I Work on It — Environment, Commands and GitHub

This is the practical companion to the other documents. It covers the machine I
built OnlyBrowserOS on, the tools I installed, the commands I ran every day, how I
tested, how the code and ISOs got onto GitHub, and a path you can follow to make
an operating system like this yourself.

- [`06-build-from-scratch.md`](06-build-from-scratch.md) builds the ISO by hand,
  one command at a time, so you can see every step.
- [`03-how-it-was-built.md`](03-how-it-was-built.md) explains what my build
  scripts do inside.
- This file is about *using* those scripts and the work around them.

---

## 1. How an operating system like this is made

A Linux-based operating system has five layers. You write almost none of them;
you pick them, configure them and add your own layer on top.

| Layer | What it does | In OnlyBrowserOS |
|---|---|---|
| **Boot loader** | Firmware (BIOS or UEFI) starts it; it loads the kernel | GRUB, plus Microsoft-signed `shim` for Secure Boot |
| **Kernel** | Talks to the hardware: CPU, memory, disks, Wi-Fi, USB | Debian's `linux-image-amd64` + firmware packages |
| **init** | The first program; starts every service in order | `systemd` |
| **Userland** | Libraries and programs: networking, sound, graphics | Debian packages: NetworkManager, PipeWire, Xorg, Openbox |
| **Your product** | What the user actually sees | Firefox locked down, my taskbar, installer, start page, settings |

There are four common ways to build the layers below "your product":

1. **Linux From Scratch**: compile every program from source yourself. It's
   good for learning, but you have to maintain everything forever.
2. **Yocto / Buildroot**: build systems for embedded devices. They're very
   small, but they need long compiles and don't include desktop browsers with
   video codecs.
3. **Remaster a distribution** (Cubic, live-build): start from an existing
   Ubuntu or Debian ISO and change it. It's quick at first, but it's hard to
   see and control what is really inside.
4. **debootstrap + chroot + squashfs**, which is what I did: download a
   *minimal* Debian into a folder, install exactly the packages I want, add my
   own files, and pack the folder into a bootable ISO. Nothing is compiled.
   Debian keeps shipping security updates for everything I didn't write.

The whole process in one line:

```
debootstrap → chroot + apt install → add my package → configure → squashfs → GRUB + xorriso → ISO
```

---

## 2. My build machine

I built everything inside a **VirtualBox virtual machine**, not directly on the
laptop:

| | |
|---|---|
| Operating system | Ubuntu 24.04 LTS (64-bit) |
| CPU / RAM | 5 virtual cores, 8 GB RAM |
| Disk | 50 GB virtual disk (a build needs at least 12 GB free) |
| Internet | Needed: every package is downloaded from Debian's mirrors |

Why a VM: the build runs as root and mounts things inside a folder, so a
mistake can't damage my real system. I could also throw the VM away and start
again.

**The catch:** VirtualBox doesn't pass hardware virtualisation through, so
there's no `/dev/kvm` inside it. QEMU tests in the VM therefore run in pure
software emulation (TCG), several times slower than normal. `test-iso.sh`
detects this and switches by itself. On a normal Linux PC with KVM, the same
tests are much faster.

### Tools I installed

```bash
# Build tools (build-iso.sh also installs any that are missing)
sudo apt install debootstrap squashfs-tools xorriso mtools dosfstools \
    grub-pc-bin grub-efi-amd64-bin grub-common rsync zstd \
    debian-archive-keyring python3

# Testing: a virtual PC with BIOS, UEFI and Secure Boot firmware
sudo apt install qemu-system-x86 qemu-utils ovmf

# Packages and signed updates
sudo apt install dpkg-dev apt-utils gnupg

# Git and the GitHub command-line tool
sudo apt install git gh
```

Versions I used: QEMU 8.2.2, OVMF 2024.02, git 2.43, gh 2.100. The image itself
is **Debian 13 "trixie"**, even though the build machine is Ubuntu. debootstrap
can install any Debian release from any Debian-family host.

One Ubuntu quirk: Ubuntu's `debootstrap` may not know the newest Debian release
name. `build-iso.sh` fixes that by linking the `trixie` script to `sid`, which
bootstraps every modern Debian correctly.

### Editor and languages

- **Python 3 + GTK 3**: taskbar, installer, home screen (`src/panel`,
  `src/installer`, `src/home`)
- **HTML/CSS/JavaScript**: start page, Downloads page, settings (`src/start`),
  Firefox configuration (`src/firefox`)
- **Bash**: build, test and boot-time scripts (`build/`, `src/session`,
  `src/system`)

Any text editor works; nothing needs an IDE or a compiler.

---

## 3. The repository layout

```
webos/                       ← the git repository
├── README.md                ← front page on GitHub
├── docs/                    ← these documents (+ images/)
├── refeence_images/         ← my design mockups the UI follows
└── github/
    ├── src/                 ← everything OnlyBrowserOS adds to Debian
    │   ├── panel/           taskbar (Python/GTK)
    │   ├── installer/       installer (Python/GTK) + root helper
    │   ├── home/            home screen shown when the browser is closed
    │   ├── start/           start page, Downloads page, settings (HTML)
    │   ├── firefox/         Firefox lock-down (autoconfig) and tab limit
    │   ├── session/         what starts after auto-login
    │   ├── system/          boot-time tuning, settings backend, USB, autotest
    │   └── shared/          theme, keyboards, "Low/Mid/High-end" levels
    ├── build/
    │   ├── config.sh        name, version, Debian release, package lists
    │   ├── build-iso.sh     builds the ISO
    │   ├── make-package.sh  builds onlybrowseros_<ver>_all.deb
    │   ├── test-iso.sh      boots the ISO in QEMU, by hand or automatically
    │   ├── bench/           memory measurement bench
    │   ├── make-signing-key.sh, release.sh   signed updates
    │   ├── overlay/         system config files that go into the package
    │   ├── work/ out/ test/ logs/            ← generated, not in git
    └── legacy/              the first prototype (web-page desktop)
```

`.gitignore` keeps the generated folders out of git. `work/` holds the whole
unpacked Debian system (several GB) and `out/` the ISOs (~800 MB). ISOs go to
GitHub **Releases**, never into the repository itself.

---

## 4. The daily loop

Almost every change went through the same four steps:

```bash
cd ~/Documents/projects/webos/github/build

# 1. Edit something in ../src/  (e.g. the taskbar: ../src/panel/panel.py)

# 2. Rebuild from the "overlay" stage: reuses the downloaded Debian system,
#    only re-installs my package and repacks the ISO (~6 minutes)
sudo ./build-iso.sh --from overlay 2>&1 | tee logs/build-N-what.log

# 3. Test it automatically in a 1 GB virtual laptop
./test-iso.sh --auto-live --ram 1024 2>&1 | tee logs/test-N-what.log

# 4. Look at the results: PASS/FAIL lines in the log, screenshots in test/
grep OBOS-AUTOTEST logs/test-N-what.log
```

I numbered every build and test log (`build-17-polish.log`,
`test-17-final-1gb.log`, …), so when something broke I could compare it with
the last run that worked.

### Build commands

```bash
sudo ./build-iso.sh                  # full build from nothing (~30 min, mostly downloads)
sudo ./build-iso.sh --from overlay   # after changing src/ or build/overlay/
sudo ./build-iso.sh --from apt       # after changing a package list in config.sh
sudo ./build-iso.sh --to apt         # stop after a stage (to look inside work/chroot)
sudo ./build-iso.sh --clean          # delete work/ and start fresh
sudo ./build-iso.sh --list-stages    # deps bootstrap apt overlay configure cleanup squashfs iso
OBOS_VERSION=1.3 sudo ./build-iso.sh # any config.sh value can be overridden like this
```

Each stage leaves a stamp in `work/stamps/`, so a re-run skips what already
finished. Timings from the last v1.2 build (from `overlay` on):

```
12:44:31  Installing OnlyBrowserOS      (5 s)
12:44:36  Configuring the system        (1 min)
12:45:30  Trimming the image
12:45:31  Compressing the system        (4 min — zstd level 19, the slowest part)
12:49:42  Building the ISO
```

The result is `out/onlybrowseros-1.2-amd64.iso` plus its `.sha256`.

To build only the package (no root needed):

```bash
./make-package.sh          # → out/onlybrowseros_1.2.<date>_all.deb
dpkg-deb -c out/onlybrowseros_*.deb | less   # see what's inside
```

### Looking inside the built system

The unpacked system is a normal folder, so I could inspect it directly:

```bash
ls build/work/chroot/usr/lib/onlybrowseros/
sudo chroot build/work/chroot dpkg -l | wc -l      # how many packages
sudo du -sh build/work/chroot/usr/* | sort -h      # what takes the space
```

---

## 5. Testing

### Automatic tests

```bash
./test-iso.sh --auto-live                       # boot live, BIOS, 2 GB
./test-iso.sh --auto-live --ram 1024            # the 1 GB laptop this is made for
./test-iso.sh --auto-install                    # install to an empty disk, reboot, test
./test-iso.sh --auto-install --uefi
./test-iso.sh --auto-install --secureboot --ram 1536   # like a shop-bought laptop
./test-iso.sh --timeout 90 ...                  # more time (software emulation is slow)
```

How it works:
1. QEMU starts with no window. The kernel command line gets `obos.autotest=report`.
2. Inside the image, `src/system/autotest` sees that flag and, once the
   desktop is up, tests the tab limit, downloads, settings, printing and the
   home screen. It measures memory, takes screenshots and prints lines like
   `OBOS-AUTOTEST: SETTINGSTEST PASS` to the serial port.
3. `test-iso.sh` collects the serial output into `build/test/serial-*.log` and
   the screenshots into `build/test/*.png`.
4. `--auto-install` drives the real installer first, then boots the installed
   disk and runs the same tests there.

The Secure Boot test uses OVMF's firmware with Microsoft's keys enrolled
(`OVMF_CODE_4M.secboot.fd` + `OVMF_VARS_4M.ms.fd`). If anything in the boot
chain isn't signed, it fails exactly as a real laptop would.

### By hand

```bash
./test-iso.sh                 # live ISO in a window (or VNC on localhost:5901)
./test-iso.sh --install       # live ISO + empty 20 GB disk, click through the installer
./test-iso.sh --boot-disk     # start what was installed
```

VirtualBox works too: a new "Debian (64-bit)" VM with the ISO attached.

### Memory bench

For measuring Firefox's memory precisely, without booting a whole VM (see
[`08-memory.md`](08-memory.md)):

```bash
cd build/bench
sudo ./setup.sh                                   # throwaway overlay on top of work/chroot
Xvfb :90 -screen 0 1366x768x24 &                  # invisible screen for Firefox
sudo ./run.sh baseline '{}'                       # measure with current settings
sudo ./run.sh noprefetch '{"network.dns.disablePrefetch": true}'   # try one preference
sudo ./teardown.sh                                # before the next build
```

### Real hardware

```bash
lsblk                                             # find the USB stick, e.g. /dev/sdb
sudo dd if=out/onlybrowseros-1.2-amd64.iso of=/dev/sdb bs=4M status=progress oflag=sync
```

On Windows, use Rufus (choose **DD mode**) or balenaEtcher. On the laptop, open
the one-time boot menu (usually F12, F9 or Esc) and pick the USB stick.

---

## 6. Updates (built, not switched on yet)

OnlyBrowserOS is one Debian package, so updating it is just publishing a newer
package where computers look for it:

```bash
./make-signing-key.sh me@example.com   # ONCE: creates the GPG key; back it up offline
./release.sh --no-push                 # build package, sign the index, look first
./release.sh                           # same, then push to the updates repository
```

`release.sh` keeps a clone of a second GitHub repository (served by GitHub
Pages) in `build/updates-site/`. It adds the `.deb`, runs `apt-ftparchive` to
write the `Packages`/`Release` index, signs it (`InRelease`, `Release.gpg`) and
pushes. Installed computers check daily through apt. The private key is never
committed: `.gitignore` blocks `*.asc`, and the key lives only in my keyring
and on offline backups.

---

## 7. Git and GitHub, step by step

### One-time setup

```bash
git config --global user.name  "AnIntellectualBeing"
git config --global user.email "AnIntellectualBeing@users.noreply.github.com"
gh auth login          # GitHub.com → HTTPS → log in with a web browser
gh auth status         # check
```

The `users.noreply.github.com` address links commits to my GitHub account
without publishing my real e-mail address.

### The repository

The GitHub repository `AnIntellectualBeing/onlybrowseros` already existed. I had
created it on the website (with an "Initial commit" README) and uploaded two
design images through the browser ("Add files via upload"). My local project had
its own separate history. To join the two without losing either:

```bash
cd ~/Documents/projects/webos
git init -b main
git add .
git commit -m "OnlyBrowserOS v1.1: ..."
git remote add origin https://github.com/AnIntellectualBeing/onlybrowseros.git
git fetch origin
git merge origin/main --allow-unrelated-histories -m "Merge existing GitHub repo history"
git push -u origin main
```

`--allow-unrelated-histories` is needed because the two histories have no
common commit.

### Every change after that

```bash
git status
git add -A
git commit -m "Short summary of what changed and why"
git push
```

### Releases (where the ISOs live)

GitHub keeps files up to 2 GB per release asset, which is plenty for an 800 MB
ISO. Files over 100 MB can't go into the repository itself.

```bash
cd github/build/out
sha256sum -c onlybrowseros-1.2-amd64.iso.sha256          # check the ISO first

# A draft release: invisible to the public until it's published
gh release create onlybrowseros-v1.2 --draft \
    --title "OnlyBrowserOS 1.2" --notes-file notes.md \
    onlybrowseros-1.2-amd64.iso.sha256

# Upload the ISO (takes a while; --clobber replaces a half-finished upload)
gh release upload onlybrowseros-v1.2 onlybrowseros-1.2-amd64.iso --clobber

# Check that both files are there, then make it public
gh release view onlybrowseros-v1.2
gh release edit onlybrowseros-v1.2 --draft=false --latest
```

Publishing the release creates the `onlybrowseros-v1.2` tag on `main`. Earlier
releases have tags `onlybrowseros-v1.0` and `onlybrowseros-v1.1`.

### Rewriting old commit messages

Some early commit messages carried a `Co-Authored-By:` line I didn't want. I
removed it from every commit, and from the v1.1 tag that points into that
history:

```bash
git branch backup-before-rewrite                 # safety copy
git filter-branch -f \
  --msg-filter 'grep -v "^Co-Authored-By:" | sed -e :a -e "/^\n*\$/{\$d;N;ba" -e "}"' \
  --tag-name-filter cat -- main onlybrowseros-v1.0 onlybrowseros-v1.1
git diff backup-before-rewrite main --stat       # empty = no file changed, only messages
git push --force-with-lease origin main
git push --force origin onlybrowseros-v1.1
```

- The `grep` drops the line and the `sed` removes the blank lines it leaves at
  the end of each message.
- Rewriting history changes every commit hash after the first changed commit,
  which is why it needs a force-push. Anyone who cloned before has to clone
  again.
- Only do this on a repository you own.

---

## 8. If you want to make your own

For a complete hands-on course with a working example, see
[`10-make-your-own-os.md`](10-make-your-own-os.md). In short, a route that
follows how this project grew:

1. **Learn the pieces by hand.** Follow [`06-build-from-scratch.md`](06-build-from-scratch.md)
   in a VM until a plain Debian boots from your own ISO in QEMU. That's the
   hardest part to understand and the least code.
2. **Decide what the one job of your system is.** Mine is "the web, nothing
   else", which decided everything else: which packages, no desktop, no file
   manager.
3. **Make it boot into your program.** Auto-login on tty1, `startx`, a small
   window manager (Openbox), then your program full-screen
   (`src/session/`).
4. **Put your files into one `.deb` package.** Then the ISO build and future
   updates install the same thing (`make-package.sh`).
5. **Script the build in stages** so you can rebuild in minutes, not half an
   hour.
6. **Automate the tests early.** A serial-port report from inside the VM
   caught most of my bugs before I ever wrote a USB stick.
7. **Test on the weakest target** (1 GB RAM) and with Secure Boot on, because
   that's what real laptops have.
8. **Write an installer last.** It's just: partition the disk, copy the
   squashfs contents across, install GRUB, rename the user (`src/installer/`).
9. **Publish:** code on GitHub, ISO plus checksum on the Releases page, and a
   README that says how to write the USB stick.

Things that cost me the most time, so you can avoid them, are in
[`07-project-story.md`](07-project-story.md) under "The hardest problems".
