# OnlyBrowserOS — Documentation

How OnlyBrowserOS works, how I built it, and why it is built the way it is.

| File | What's in it |
|---|---|
| [`01-what-it-is.md`](01-what-it-is.md) | The product in plain words: what it does and who it's for |
| [`02-how-it-works.md`](02-how-it-works.md) | The architecture, from power-on to the browser on screen |
| [`03-how-it-was-built.md`](03-how-it-was-built.md) | The build system: assembling, testing and publishing the ISO |
| [`04-decisions-and-why.md`](04-decisions-and-why.md) | The trade-offs, and why I chose each side |
| [`05-whats-left.md`](05-whats-left.md) | To-do list, real-hardware tests, known gaps |
| [`06-build-from-scratch.md`](06-build-from-scratch.md) | The whole process by hand, one command at a time |
| [`07-project-story.md`](07-project-story.md) | How the project went, from first prototype to v1.2, and the hardest problems |
| [`08-memory.md`](08-memory.md) | Where the RAM goes, how I measure it, and how I brought it down |
| [`09-how-i-work.md`](09-how-i-work.md) | My build machine, tools, every command I run, testing, and publishing on GitHub; how to make your own |
| [`10-make-your-own-os.md`](10-make-your-own-os.md) | A hands-on course to build your own small OS, in its own repository: [createyourdistro](https://github.com/AnIntellectualBeing/createyourdistro) |

## Quick facts

- **What it is:** a Debian-based Linux distribution that boots straight into
  a locked-down Firefox, for people who only need the web.
- **Base:** Debian 13 "trixie", cut down; about 2 GB installed, 770 MB ISO.
- **Code:** about 8,700 lines in `src/` plus 1,400 in the build and test scripts: Python (taskbar, installer, settings backend),
  JavaScript (Firefox extension), HTML/CSS (start page, settings), shell
  (build, boot and test scripts).
- **Runs on:** 64-bit PCs with 1 GB of RAM or more; BIOS, UEFI, Secure Boot.
- **Repo:** https://github.com/AnIntellectualBeing/onlybrowseros —
  ISOs are on the Releases page.
