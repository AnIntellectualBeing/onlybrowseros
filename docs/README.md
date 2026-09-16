# OnlyBrowserOS — Documentation Index

This folder explains the project: what it is, how it was built, why it was
built that way, and what's left to do. Written so you (the project owner) can
read it later, understand the whole system, and talk about it in an interview
without needing to re-read every source file.

| File | What's in it |
|---|---|
| [`01-what-it-is.md`](01-what-it-is.md) | The product in plain words: what OnlyBrowserOS does, who it's for, the elevator pitch |
| [`02-how-it-works.md`](02-how-it-works.md) | The technical architecture: how the pieces fit together, boot to browser. **This is your interview material.** |
| [`03-how-it-was-built.md`](03-how-it-was-built.md) | The build system: how the ISO is assembled, how testing works, how updates get published |
| [`04-decisions-and-why.md`](04-decisions-and-why.md) | The product/design decisions made and the reasoning behind each — useful for "why did you choose X" questions |
| [`05-whats-left.md`](05-whats-left.md) | Open items: what needs your decision, what needs real-hardware testing, what a future session should pick up |

## Quick facts

- **What it is:** a Debian-based Linux distribution that boots straight into
  a locked-down Firefox browser — for people who only need the web and want
  something that can't be broken by installing the wrong thing.
- **Base:** Debian 13 "trixie", stripped down, ~2 GB installed.
- **Code:** ~8,500 lines across Python (taskbar, installer, settings backend),
  JavaScript (browser extension), HTML/CSS (start page, settings UI), and
  shell (build and boot scripts).
- **Repo:** https://github.com/AnIntellectualBeing/onlybrowseros
- **Latest release:** `onlybrowseros-v1.1` — see the GitHub Releases page for
  the downloadable ISO.
