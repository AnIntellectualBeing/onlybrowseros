# Decisions and Why — Interview-Ready Reasoning

This file is the "why did you do X instead of Y" answers, gathered in one
place. Each one was a real trade-off, not an arbitrary choice.

## Why Debian instead of building a distro from scratch, or forking another one?

Building a Linux distro truly from scratch (compiling every package
yourself, Linux-From-Scratch style) is months of ongoing maintenance for no
product benefit here. Forking an existing "browser-only" distro would mean
inheriting someone else's architecture and constraints. Debootstrapping
plain Debian and layering custom code on top gives full control over the
user experience while getting a huge, well-tested package ecosystem, security
updates, and hardware support for free.

## Why a taskbar and installer written in Python + GTK, not Electron or a web UI?

Memory. This entire product exists to serve computers with as little as 1GB
of RAM. An Electron app starts around 100-150MB before it does anything;
Python + PyGObject (GTK's Python bindings) draws native widgets and typically
sits at 30-60MB. On a 1GB machine, that difference is the gap between the
browser fitting in memory at all and constant swapping.

## Why hand-draw every icon with Cairo instead of using an icon theme?

Three reasons: (1) no icon theme package needs to be installed, saving disk
and avoiding version-mismatch bugs; (2) vector paths scale perfectly at any
size/DPI with zero blur, which matters once text-size scaling was added;
(3) it keeps the whole taskbar as pure Python files with no binary asset
pipeline.

## Why is the tab limit described as "Low-end / Mid-range / High-end PC" instead of a number?

Early versions let the installer set a raw tab count. The product owner's
feedback was that a number like "4 tabs" means nothing to someone buying a
computer, but "Mid-range PC" is language people already use when shopping for
a laptop. The underlying mechanism didn't change — it's still a number of
tabs, calculated from RAM — only the label shown to the user did. This is a
recurring theme in the project: **the technical mechanism stays the same, the
words describing it get simplified for a non-technical audience.**

## Why put every Settings control inside one browser page instead of a native app?

Three reasons converged: (1) a second native settings window would cost
another 30-60MB of RAM running permanently or need its own start/stop
lifecycle; (2) it would visually not match the browser (different toolkit,
different theme) unless a lot of duplicate styling work was done; (3) since
the whole product's philosophy is "it's just a browser," putting settings
*in* the browser reinforces that instead of contradicting it. The trade-off
is that a native app could react to system events instantly, while the
browser page talks to the system through native messaging (see below) —
acceptable since settings changes are infrequent, deliberate actions.

## Why native messaging instead of, say, a REST API on localhost?

A localhost HTTP server run by a background daemon is a bigger attack
surface (any process on the machine, or any tab, could reach it) and needs
its own service to keep alive. Native messaging is scoped by design: only
the extension whose ID is whitelisted in the host manifest can invoke it, it
spawns fresh for each request instead of running as a persistent daemon, and
it inherits the exact permission model that already exists for "a user
program that needs root sometimes" — sudo.

## Why validate everything as strict allow-lists rather than block-lists?

Both `install-helper` and `settings-host` take the same approach: define
exactly what a valid value looks like (a specific regex for a hostname, a
literal set of known time zones, a number in a bounded range) and reject
everything else, rather than trying to enumerate bad inputs. A block-list
approach to something like a disk path or a shell argument is a losing game
— there's always another edge case. This is standard secure-coding practice,
but it's worth being able to say explicitly: **every root-privileged helper
in this project validates with an allow-list, not a block-list.**

## Why restrict downloads to files the browser can open?

The product is explicitly "just a browser" — there's no file manager to
organize a `.zip`, no way to run a `.deb` or `.exe` even if one were
downloaded, and letting arbitrary files pile up in Downloads with no way to
do anything with them is confusing, not useful. Restricting to
browser-openable types (PDF, images, video, audio, text) means everything in
Downloads can always actually be opened by clicking it — no dead ends.

## Why keep Firefox's own sign-in but remove private windows and add-ons?

Firefox account sign-in brings a person's bookmarks and saved passwords with
them onto a shared/replacement computer, which is a genuine convenience with
low risk (it lives entirely inside the one browser window). Private windows
were removed specifically because the tab-limit extension already merges any
second window's tabs back into the first (see
[`02-how-it-works.md`](02-how-it-works.md)) — private and normal tabs can't
share a window in Firefox, so a private window would be the one way to end
up with two visible windows again, defeating the "one window" design.
Add-ons were removed because arbitrary third-party code with browser-wide
permissions is exactly the kind of "this computer can now be broken by
installing the wrong thing" risk the whole product exists to prevent.

## Why Secure Boot support instead of just telling users to disable it?

Early testing shipped with Secure Boot required to be off, with a note in
the README. The product owner's feedback was direct: most people buying a
laptop from the last ~10 years will never go into firmware settings, and
telling them to is itself a support burden and a support failure for a
product whose entire pitch is "no learning curve." The fix (signed shim +
signed GRUB, hand-built hybrid ISO) is more build-system complexity, but it's
complexity paid once by the developer instead of confusion paid by every
user.

## Why a self-hosted apt repo for updates instead of a hosted service?

The project owner already has a GitHub account and no budget for a paid
update-hosting service. GitHub Pages serves static files for free, and
`apt-ftparchive` + GPG signing is the exact mechanism Debian itself uses for
its own repos — no custom protocol to invent or maintain, and any Debian
system (including the ones being shipped) already knows how to consume it
via `unattended-upgrades`.

## Why package everything as one `.deb` instead of one package per component?

At this project's size (taskbar + installer + settings + start page +
system config, roughly 8,500 lines total), splitting into multiple packages
would add packaging overhead (multiple `control` files, inter-package
dependency declarations) without a real benefit — nothing here is ever
installed independently of the rest. One package also guarantees the
taskbar, installer, and settings backend are always the *same version* on
disk, avoiding a whole category of "the taskbar shipped a new setting but the
backend that reads it is still the old version" bugs.
