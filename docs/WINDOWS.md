# Using the MiniToo from Windows

Two pieces run on Windows:

- **`core/dv-win`** — a command-line sender, the counterpart of the macOS
  `core/divoom-send.swift` / `core/dv`. Same Bluetooth Classic SPP channel and
  frame format ([`FINDINGS.md`](../FINDINGS.md) §3), through the Windows
  Bluetooth API (`Windows.Devices.Bluetooth.Rfcomm`). It can also upload a GIF
  to one of the device's custom faces.
- **`apps/clauddy/windows`** (`clauddy-win`) — Clauddy: the three status faces
  driven by Claude Code hooks. See [Clauddy on Windows](#clauddy-on-windows).

The rest of the repo (the eZip bridge, photo and pixel-art uploaders, probes)
is still macOS-only.

## Requirements

- Windows 10 (1809) or 11
- .NET 8 SDK or newer (`dotnet --version`)
- The device paired under **Settings → Bluetooth & devices**
  (the Windows name is `Divoom MiniToo-Audio`; a Tiivoo 2 shows up as
  `Divoom Tiivoo 2-Audio`)

## dv-win

```powershell
dotnet build core/dv-win -c Release
```

The binary lands in `core\dv-win\bin\Release\net8.0-windows10.0.19041.0\dv-win.exe`.
Or use `dotnet run --project core/dv-win -c Release -- <args>`.

Find the device address, then pass it as the first argument or set it once:

```powershell
dv-win list                          # paired devices; Divoom ones are marked
$env:DIVOOM_MAC = "B1:21:81:6D:CD:AE"

dv-win device-id                     # the DeviceId the device reports
dv-win brightness 40
dv-win screen off                    # and: screen on
dv-win face 3
dv-win clock
dv-win select <ClockId> <DeviceId>   # Channel/SetClockSelectId, as Clauddy does
dv-win raw 32 32                     # opcode + args in hex (here: brightness 50)
dv-win rawfile frames.txt 40         # one `raw` line per frame, '#' = comment
```

Arbitrary JSON commands:

```powershell
'{"Command":"WhiteNoise/Get"}' | dv-win json -
dv-win json "@command.json"
```

Store a GIF on a custom face (page 0, 1 or 2; the DeviceId is read from the
device when `--device-id` is omitted). The page's previous contents are
replaced:

```powershell
dv-win upload-face apps/clauddy/assets/working.gif --page 1
```

The GIF is cropped to the 160×128 canvas (cover fit, nearest neighbour), encoded
as 4:4:4 JPEG and sent the way the phone app does; the device asks for the file
and confirms it. Uploads take 8 s to a minute depending on the GIF. Options:
`--quality`, `--speed-ms`, `--speed-scale`, `--file-id`, and
`--clock-id <id> --style-id <id>` to set the frame style afterwards.

Replies are printed as they arrive (`->` sent, `<-` received):

```
-> 01 1f 00 01 7b 22 43 6f ... 02
<- { "Command": "WhiteNoise/Get", "OnOff": 0, "Time": 15, "EndStatus": 0, "Volume": [0, 0, 0, 0, 0, 0, 0, 0] }
```

Options (anywhere on the line): `--listen <ms>` (how long to wait for replies,
default 1500), `--delay <ms>` (pause between frames, default 40), `--settle <ms>`
(pause after the channel opens, default 1500), `--uuid <guid>` (SPP record to
open).

## Clauddy on Windows

```powershell
dotnet publish apps/clauddy/windows -c Release -o $env:USERPROFILE\.clauddy\bin
$clauddy = "$env:USERPROFILE\.clauddy\bin\clauddy-win.exe"

& $clauddy install            # pairing must be done in Windows first
& $clauddy set working        # chilling | working | alerting
```

`install` finds the paired device, reads its DeviceId, writes
`%USERPROFILE%\.clauddy\config.json` and uploads the three GIFs from
`apps/clauddy/assets` (about 1.5 minutes; `--skip-upload` if they are already on
the device). It prompts for nothing: the ids that select the three custom faces
are the Divoom store's `Custom1/2/3` entries (984, 986, 988), the same as on
the author's account, and they worked on a second MiniToo. If switching does
nothing visible on your device, `install --login` looks the ids up through a
Divoom account (email and hidden password prompt; nothing is stored). That does
not work for accounts created with Sign in with Apple, which have no password;
`--clock-ids <chilling,working,alerting>` takes the ids directly.

### Claude Code hooks

```powershell
& $clauddy start     # starts the daemon, adds the hooks to ~/.claude/settings.json
& $clauddy status
& $clauddy stop      # stops the daemon, removes the hooks again
```

Hooks cost a process start on every prompt and tool call, so they are only in
`settings.json` while Clauddy is running. `start` adds four entries (same mapping
as macOS: `UserPromptSubmit` and `PreToolUse` → working, `Notification` →
alerting, `Stop` → chilling) next to whatever hooks you already have, and
`stop` removes exactly those; other settings are left as they are. The file is
copied to `settings.json.clauddy-backup` before the first change, a file that is
not valid JSON is never touched, and `--settings <path>` works on another file
(`CLAUDE_CONFIG_DIR` is honoured). `clauddy-win hooks` prints the entries
without touching anything.

Whether a Claude Code session that is already open notices hooks being added or
removed depends on the Claude Code version: in testing, a session that was open
before `start` began running them at once. If yours does not, restart it or
reload hooks in the `/hooks` menu. A session that still has them after `stop` is
harmless: while Clauddy is stopped, `hook` exits at once and does not start the
daemon.

`hook` is the multi-session aware variant of `set`: a higher-severity face is
held against downgrades from other sessions for 5 s (alerting) or 2 s (working),
the downgrade is retried once the hold expires, and asking for the face already
showing costs nothing. `CLAUDDY_ALERT_HOLD` and `CLAUDDY_WORK_HOLD` tune the
holds.

### The daemon

`start` (or the first `set`) starts `clauddy-win daemon` in the background. It
keeps the Bluetooth channel open, so a switch is a pipe write (about 120 ms,
about 0.5 s for the first one) and several Claude windows share one owner of the
device. It reconnects when the channel drops, logs to
`%USERPROFILE%\.clauddy\daemon.log`, and exits on `clauddy-win stop`. While it
runs, the Divoom phone app cannot connect to the device; `install` stops it
first. Run `clauddy-win stop` before republishing the binary, or the publish
cannot overwrite the files the daemon has loaded.

The daemon is started without inheriting the caller's stdout. That matters for
hooks: whoever runs one reads its output until every holder of the pipe has
closed it, so a daemon holding the pipe would keep Claude Code waiting.

## Things to know

- **Quoting in Windows PowerShell 5.1.** It strips the double quotes out of
  arguments passed to native programs, so `json '{"Command":"..."}'` arrives as
  invalid JSON. Pipe the JSON in (`json -`) or use `json @file`; PowerShell 7
  and bash do not have this problem.
- **One client at a time.** If the Divoom phone app is connected, the connect
  fails or the device stays silent; close the app or power-cycle the device.
- **The device is sometimes deaf right after you connect.** The channel opens
  (about 70 ms) but the firmware ignores what it is sent, most often after the
  device has been idle or after a previous client was killed rather than
  disconnected. A reconnect usually fixes it, so the tools check that the
  device answers a query and reconnect up to five times (about 4 s each) before
  giving up. Stop the daemon with `clauddy-win stop` instead of killing it.
- **The virtual COM port does not work.** Windows creates a `COMn` port for the
  device's SPP record, but opening it and writing frames got no replies, so
  `dv-win` uses `StreamSocket` instead.
- **Unmapped replies.** After some commands the device also sends a
  `04 f7 55 4e 6f 62 ...` frame (`op 04: f7 55 ...` in the output). It is
  harmless and not decoded.

## Status

Verified on a MiniToo (firmware 2.4.0) on Windows 11: `list`, `device-id`,
`json` (replies parsed), `screen`, `select`, and `upload-face` for all three
Clauddy GIFs; `clauddy-win install --skip-upload` and `set` for all three
states, including the daemon and its hold logic. `start` and `stop` were
tested against a copy of a real `settings.json` (existing hooks preserved,
repeated `start` does not duplicate, `stop` restores the original, invalid JSON
untouched). Not yet exercised on hardware from Windows: `brightness`, `face`,
`clock`, `raw`, `rawfile` (they build the same frames as the Swift sender) and
`install --login`. The installed hooks were seen driving the daemon from a
running Claude Code session (a `PreToolUse` hook switched the face to working).
