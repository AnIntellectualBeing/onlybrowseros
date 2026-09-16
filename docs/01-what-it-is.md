# What OnlyBrowserOS Is

## The elevator pitch

OnlyBrowserOS is an operating system for old or low-spec laptops that only
need to browse the web. Turn the computer on, and instead of a desktop with
icons and a start menu, it opens straight into a full-screen browser. There is
a thin bar at the bottom for Wi-Fi, sound, battery and power — and that's the
whole interface. No file manager, no app store, no control panel full of
settings nobody understands.

Think of it as "ChromeOS, but self-built on Debian, for computers too old or
too weak to run Windows or ChromeOS well."

## Who it's for

- Someone with an old laptop (as little as 1 GB of RAM) that's too slow for a
  normal desktop Linux distro or a modern Windows install, but is still fine
  for email, video calls, YouTube, and web apps.
- A shared or public computer (school, library, family) where you want to
  hand someone a browser and nothing else — no way to install malware, no
  file system to get lost in, no settings to break.
- Anyone who wants a "just works" experience with zero learning curve.

## What it actually does

- **Boots into the browser.** No login screen, no desktop. One maximized
  Firefox window fills the screen above a 44px taskbar.
- **A start page** with big tappable tiles for common sites (Gmail, YouTube,
  WhatsApp, etc.), each showing that site's real icon, plus a search box that
  doubles as an address bar. You can add or remove your own sites.
- **A taskbar** for Wi-Fi, Bluetooth, sound, brightness, battery, the clock,
  and power (sleep/restart/shut down) — plus the OnlyBrowserOS name, which
  opens a small popup with memory usage and a link to Settings.
- **One Settings page**, inside the browser itself — not a separate app —
  covering: how powerful the computer is (which controls how many tabs can
  stay open), text size, time zone, keyboard layout, password, browsing
  history, and saved passwords.
- **A home screen** shown if you ever close the browser on purpose — a calm
  screen with the time and an "Open the browser" button, so there's always a
  way back in.
- **A graphical installer** — four short screens (welcome, disk, account,
  confirm) — that copies the running system onto the laptop's hard disk.
- **Automatic updates** — Debian's security patches install themselves, and
  the project's own code (taskbar, installer, etc.) can be updated the same
  way through a self-hosted package repository.
- **Guardrails**, because the point of the product is "you cannot break this
  computer":
  - Downloads are limited to files the browser can actually open (PDFs,
    pictures, video, music, plain text) — no installers, no ZIP files.
  - No browser add-ons, no private browsing windows, no developer tools, no
    access to a file manager or terminal.
  - A tab limit tuned to the computer's memory, so it can't be made to freeze
    by opening too many tabs.
  - Low-battery warnings that count down to a safe, clean shutdown instead of
    letting the battery die mid-task.

## What makes it different from "just installing Linux Mint and Firefox"

Everything above is *automatic and locked down*. A regular Linux install
still gives you a full desktop, a file manager, a terminal, and the ability to
install anything — which is exactly what this product avoids. The taskbar,
installer, start page, and browser lockdown are all custom-built for this
project (see [`02-how-it-works.md`](02-how-it-works.md)), not off-the-shelf
components glued together.
