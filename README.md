# divoom-minitoo

Reverse-engineered toolkit for the **Divoom MiniToo** pixel display, and
**Clauddy** — a Claude Code status indicator built on top.

## Clauddy

Display three states on the device: working, waiting for your feedback,
chilling.

| working | alerting | chilling |
| :---: | :---: | :---: |
| ![working](apps/clauddy/assets/working.gif) | ![alerting](apps/clauddy/assets/alerting.gif) | ![chilling](apps/clauddy/assets/chilling.gif) |

Wires into Claude Code hooks; switches faces in under a second. Setup in
[`apps/clauddy/README.md`](apps/clauddy/README.md).

---

## The toolkit

The MiniToo speaks an undocumented Bluetooth Classic RFCOMM protocol. This repo
also contains the protocol notes, a working macOS Bluetooth daemon, and an
uploader that bypasses the SiFli `eZip` native library. Clauddy is one app
built on it; the rest is reusable for anyone hacking the device.

## What's in here

```
FINDINGS.md            Protocol findings — opcodes, frame format, what works
                       and what crashes the device. The hero doc.

docs/                  How-to-reproduce notes, onboarding, and the decision log
                       behind instant custom-face switching.

core/                  The toolkit. macOS Bluetooth daemon (`dv`), the Swift
                       RFCOMM sender, the eZip native-lib bridge, GIF/JPEG
                       uploaders, and probes used to map the protocol.

apps/clauddy/          A Claude Code agent-status display: three preloaded GIF
                       faces (chilling / working / alerting) and a one-line
                       command to switch between them. Wires up to Claude Code
                       hooks.

references/            Vendored third-party projects kept for reference only
                       (e.g. pixoo-mcp-server — different Divoom device).
```

The repo is laid out as a **library + apps** monorepo. `core/` is reusable —
nothing in it knows about Claude. `apps/clauddy/` is one application built on
top; future apps (other agents, Pomodoro, weather, Home Assistant bridge) live
beside it.

---

## Quick start

Pick the path that matches what you want to do.

**I want to control my MiniToo from the command line.**
Read [`docs/SETUP.md`](docs/SETUP.md) for pairing and `core/dv` usage.

**I want a physical status indicator for Claude Code.**
Read [`apps/clauddy/README.md`](apps/clauddy/README.md). The installer handles
pairing, uploads three GIFs into the MiniToo's three custom faces, and wires
itself into your Claude Code hooks.

**I want to extend the protocol or build a new app.**
Start with [`FINDINGS.md`](FINDINGS.md) — it's the source of truth for what the
device actually does. Then `core/` is your library.

---

## Status

- **Device:** Divoom MiniToo, firmware 2.4.0, 160×128 display.
- **Host:** macOS only. Uses `IOBluetooth` for Classic RFCOMM. Linux / Windows
  ports would need a different transport binary.
- **Maturity:** working draft. The agent-status path (instant face switching
  via `Channel/SetClockSelectId`) is solid and used daily. Other paths
  (live-animation streaming via `0x8B`, photo upload via `0x8D`, ANCS-style
  text-with-icon notifications) are verified end-to-end but less polished. See
  the per-opcode support matrix in `FINDINGS.md` §9.

---

## Trademark and affiliation

Not affiliated with, sponsored by, or endorsed by Divoom. *Divoom* and
*MiniToo* are trademarks of their respective owners and are used here only to
identify the hardware this software is compatible with.

This project does **not** redistribute Divoom firmware, app binaries, or
account data. The `eZip` bridge in `core/ezip/` patches the official iOS
framework's compiled object files for macOS load — see `FINDINGS.md` §8h for
the legal/technical details before redistributing builds.
