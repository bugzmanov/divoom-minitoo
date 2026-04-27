# Clauddy MiniToo Package

Clauddy turns a Divoom MiniToo into a small status display with three preloaded
custom faces:

- `chilling`
- `working`
- `alerting`

Target platform is macOS. Runtime switching is a small Bluetooth JSON command,
so it is fast once the three faces have been installed.

## Why this exists

Display three states on the device: working, waiting for your feedback, chilling.

## Faces

The three GIFs in `assets/` are the shipping faces. Editable
[Aseprite](https://www.aseprite.org/) sources live next to each GIF
(`chilling.aseprite`, `working.aseprite`, `alerting.aseprite`) — open in
Aseprite, edit, re-export the GIF, re-run `install.sh` to push it to the
device.

## Install

Pair the MiniToo in macOS System Settings first. Disconnect the official Divoom
phone app while installing or switching states.

Run:

```bash
cd /path/to/apps/clauddy
./install.sh --email <DIVOOM_LOGIN>
```

The installer:

1. Tries to find the paired MiniToo Bluetooth MAC address automatically.
2. Checks that macOS can open a Bluetooth connection to the MiniToo.
3. Prompts for the Divoom password locally.
4. Logs in only to discover custom face IDs and persist frame styles.
5. Writes `~/.clauddy/config`.
6. Uploads the bundled GIFs into the three MiniToo custom faces.

Bluetooth discovery is cached in `~/.clauddy/detected` before Divoom login. If
you mistype the Divoom password, the retry can reuse the already discovered
Bluetooth MAC and DeviceId.

Bundled GIFs are uploaded with preserved proportions and their original GIF
timing. Square `160x160` artwork is center-cropped into the MiniToo's `160x128`
custom-face canvas instead of being vertically squashed. The MiniToo custom-face
payload supports one frame delay per uploaded face; when a GIF contains mixed
frame durations, the installer duplicates frames to preserve the original timing
as closely as the device format allows. This can make uploads larger and slower.
Frames are encoded as high-quality JPEG (`CLAUDDY_JPEG_QUALITY=95`) with
4:4:4 color sampling and nearest-neighbor resizing to reduce pixel-art
artifacts. Uploading all three faces usually takes about 1-2 minutes.

If the MiniToo plays the uploaded animation faster than expected, slow the
encoded custom-face timing without changing the GIF:

```bash
CLAUDDY_SPEED_SCALE=1.5 ./install.sh --email <DIVOOM_LOGIN>
```

You can also pin a specific per-frame delay per state:

```bash
CLAUDDY_SPEED_WORKING=300 CLAUDDY_SPEED_CHILLING=450 CLAUDDY_SPEED_ALERTING=350 ./install.sh --email <DIVOOM_LOGIN>
```

To use a smaller upload:

```bash
CLAUDDY_JPEG_QUALITY=85 ./install.sh --email <DIVOOM_LOGIN>
```

If auto-detection cannot find the device, pass the Bluetooth MAC explicitly:

```bash
./install.sh --mac <MINITOO_BLUETOOTH_MAC> --email <DIVOOM_LOGIN>
```

Credential handling:

- The password is entered through a hidden terminal prompt.
- The password is never written to disk.
- The Divoom token is kept in memory only.
- The config stores only Bluetooth MAC, DeviceId, ClockIds, and StyleIds.
- The detection cache stores only Bluetooth MAC and DeviceId.

## Switch State

```bash
./set-clauddy-state.sh working
./set-clauddy-state.sh chilling
./set-clauddy-state.sh alerting
```

If the Bluetooth helper is not already running, the script starts it and leaves
it running for faster future switches.

## Put It On PATH

```bash
mkdir -p "$HOME/.local/bin"
ln -sf /path/to/apps/clauddy/set-clauddy-state.sh "$HOME/.local/bin/set-clauddy-state.sh"
export PATH="$HOME/.local/bin:$PATH"
```

Persist the PATH line in `~/.zshrc` if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Then call from anywhere:

```bash
set-clauddy-state.sh working
```

## Wire To Claude Code Hooks

Make Claude Code drive the three states automatically by adding hooks to
`~/.claude/settings.json`. Use `clauddy-hook.sh` (not `set-clauddy-state.sh`)
as the hook command — it adds session coordination on top of the raw setter
so multiple Claude windows do not clobber each other (see next section).

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "clauddy-hook.sh working" } ] }
    ],
    "Notification": [
      { "hooks": [ { "type": "command", "command": "clauddy-hook.sh alerting" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "clauddy-hook.sh chilling" } ] }
    ]
  }
}
```

Mapping:

- `UserPromptSubmit` → `working` (Claude started the turn)
- `Notification` → `alerting` (permission prompt or idle waiting on you)
- `Stop` → `chilling` (Claude finished the turn)

Put `clauddy-hook.sh` on `PATH` the same way as `set-clauddy-state.sh`:

```bash
ln -sf /path/to/apps/clauddy/clauddy-hook.sh "$HOME/.local/bin/clauddy-hook.sh"
```

Or use an absolute path in the command. The wrapper backgrounds the actual
Bluetooth call and swallows errors, so a powered-off MiniToo never blocks a
prompt. The first call of a session may lag while the Bluetooth helper warms
up; later switches are near-instant.

## Multiple Claude Instances

The MiniToo is a single shared device with no awareness that several Claude
sessions might be talking to it. With three windows open, a `Stop` from one
session can clobber an `alerting` from another a millisecond later, and you
miss the alert.

`clauddy-hook.sh` mitigates this with a small severity model written to
`/tmp/clauddy-hook-state`:

- Severity ranks `chilling` < `working` < `alerting`. A higher-severity face
  is held against downgrades from any session for a short TTL (`alerting` for
  5s, `working` for 2s by default).
- If a downgrade arrives during the hold, it is deferred — a background retry
  re-evaluates once the hold expires, so the face still clears even if no
  further hook fires from any session.
- A request that matches the face already showing skips the Bluetooth round
  trip entirely, which keeps the device quiet under spammy `UserPromptSubmit`
  or repeated `Notification` events.

Tunables (set in your shell or `settings.json` env block):

- `CLAUDDY_ALERT_HOLD` — seconds an `alerting` face is held (default `5`).
- `CLAUDDY_WORK_HOLD` — seconds a `working` face is held (default `2`).
- `CLAUDDY_HOOK_STATE_FILE` — path to the shared state file
  (default `/tmp/clauddy-hook-state`).

This wrapper is the only Claude-Code-specific glue; nothing in
`set-clauddy-state.sh` or the daemon was changed to support it. Direct CLI
use of `set-clauddy-state.sh` still works exactly as before and bypasses the
gating logic on purpose.

## Errors

If install or switching says Bluetooth cannot connect:

1. Power on and wake the MiniToo.
2. Pair it in macOS System Settings.
3. Disconnect the official phone app from the MiniToo.
4. Confirm the Bluetooth MAC in `~/.clauddy/config`.

If `Pillow` is missing:

```bash
python3 -m pip install Pillow
```
