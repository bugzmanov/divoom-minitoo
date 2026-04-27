# Divoom Minitoo — Bluetooth Reverse Engineering Findings

Status: **working draft**. Reflects what's been verified against a real Minitoo (firmware 2.4.0) over macOS Classic Bluetooth, plus what was learned from decompiling the Divoom Android app v3.x.

---

## 1. Device fingerprint

| Field | Value |
| --- | --- |
| Marketing name | Divoom Minitoo |
| BT advertised name | `Divoom MiniToo-Audio` |
| Vendor ID / Product ID | `0x05D6 / 0x000A` |
| Firmware (observed) | 2.4.0 |
| SoC family | **Jieli (JL)** — service names are `JL_SPP`, `JL_HFP`, `JL_HID`, `JL_A2DP` |
| BT class | Bluetooth 5.3, **Classic only** (no WiFi; BLE not used for commands) |
| Display | 1.77" pixel screen. App classifies it as `DevicePixel128` + `BlueHighPixelArch` |
| Audio profiles | HFP, A2DP, AVRCP, HID (standard speaker stack) |

Two identical `JL_SPP` records show up on SDP: one on RFCOMM **channel 1**, one on **channel 10**. Both accept the Divoom protocol; the mobile app uses `createRfcommSocketToServiceRecord(UUID)` with the standard SPP UUID `00001101-0000-1000-8000-00805F9B34FB` and picks whichever channel SDP surfaces first.

## 2. Transport

- **Classic RFCOMM over SPP** (not BLE / GATT).
- **One client at a time.** While your Mac holds the channel open, the Divoom iOS/Android app cannot see the device as pairable. There is no broadcast-to-multiple-clients.
- **macOS TCC gotcha:** a bare Mach-O binary hitting `IOBluetooth` is killed by TCC with *"app's Info.plist must contain an NSBluetoothAlwaysUsageDescription key"*. The fix is to build the binary inside an `.app` bundle, codesign ad-hoc, and launch it via **LaunchServices** (`open ...app`). Direct `./app/Contents/MacOS/bin` still fails — macOS only resolves the Info.plist when the binary is launched through LaunchServices.

### Keeping the BT icon quiet

Every open / close of the RFCOMM channel flashes the macOS Bluetooth menu icon. Solution: run one long-lived **daemon** process (launched once via `open -g`), feed commands over a FIFO (`/tmp/divoom.fifo`). One connect at startup, zero icon flashes thereafter.

## 3. Frame format

```
┌──────┬──────────┬──────────┬────────┬──────────┬──────────┬──────────┬──────┐
│ 0x01 │  len_lo  │  len_hi  │ opcode │  args…   │ csum_lo  │ csum_hi  │ 0x02 │
└──────┴──────────┴──────────┴────────┴──────────┴──────────┴──────────┴──────┘
```

- `len` = little-endian, value is `args.count + 3` (opcode + 2 length bytes).
- `checksum` = `sum(len_lo, len_hi, opcode, args…) & 0xFFFF`, little-endian.
- `0x01` / `0x02` are literal frame delimiters, **not** escaped in new firmware.
- Old firmware (Aurabox, Timebox-Mini, Timebox original) escapes any `0x01`/`0x02`/`0x03` in the payload with `0x03` followed by `byte + 0x03`. Minitoo does **not** need escaping — confirmed by matching the Android app's `k()` encoder (new path) rather than `l()` (legacy escaped path).

### Response framing

Device → host responses use the same outer envelope but have their own internal layout:

```
01 [len_lo] [len_hi]  04  [01] [55]  {JSON body}  [csum] 02
```

- Outer opcode `0x04` = `SPP_COMMAND_CHECK` — the firmware's generic response wrapper.
- `01 55` prefix is a constant marker that precedes JSON payloads.
- JSON is the same shape the cloud REST API uses: `{"Command": "...", ...fields... }`.

There are also short ACK frames for simple commands:

```
01 06 00 04 XX 55 YY ZZ [csum] 02
```

where `XX` is the echoed command opcode and `YY` is the value the device applied. Example after `SetBrightness=50`: `01 06 00 04 32 55 32 C3 00 02`.

## 4. Opcode directory

Extracted from `com.divoom.Divoom.bluetooth.SppProc$CMD_TYPE`. Only the ones actually relevant/tested are listed here — the full enum has ~100 entries; see `sppcmd-full.md` (TODO) for the complete dump.

### Command opcodes (host → device)

| Hex | Dec | Name | Purpose | Minitoo? |
| --- | --- | --- | --- | --- |
| `0x01` | 1 | **SPP_JSON** | Carries a UTF-8 JSON command body | ✅ **works** |
| `0x05` | 5 | SPP_CHANGE_MODE | Switches audio source (BT/FM/LINE/SD/UAC) | not tested — audio only |
| `0x32` | 50 | SPP_LIGHT_ADJUST_LEVEL | Legacy brightness `[0–100]` | ✅ works |
| `0x45` | 69 | SPP_SET_BOX_MODE | Set display mode on Ditoo/Pixoo-class devices | ❌ ignored by Minitoo |
| `0x72` | 114 | **SPP_SET_TOOL_INFO** | Activate a Tool view (stopwatch / countdown / scoreboard / noise) | ✅ works |
| `0x74` | 116 | SPP_SET_SYSTEM_BRIGHT | Newer brightness opcode | not visible on Minitoo; `0x32` is the one |
| `0xBD` | 189 | SPP_DIVOOM_EXTERN_CMD | Dispatcher for extended commands (see EXT_CMD_TYPE) | partial |

### Extension commands (sent under `0xBD`)

First arg of a `0xBD` frame is an `EXT_CMD_TYPE` value, then its own args.

| Ext hex | Dec | Name | Notes |
| --- | --- | --- | --- |
| `0x17` | 23 | SPP_SECOND_USE_USER_DEFINE_INDEX | Switch to a saved custom face/page. Earlier MiniToo no-op was tested in the wrong context; retest with populated custom pages. |
| `0x2F` | 47 | SPP_SECOND_OPEN_SCREEN_CTRL | Screen control, arg is mode. App calls this with `2` in one path — semantics not fully mapped. |
| `0x34` | 52 | SPP_SECOND_APP_SET_VOL | Volume set |
| `0x36` | 54 | SPP_SECOND_APP_SET_MUSIC_PLAY_PAUSE | Pause/play |

## 5. Verified working commands

### 5.1 Brightness (JSON)

Sends a `SetBrightness` JSON via SPP_JSON. **Works reliably on Minitoo**, ~100 distinct levels 0-100.

```
# frame bytes for brightness=50:
01 36 00 01 7b 22 43 6f 6d 6d 61 6e 64 22 3a 22 43 68 61 6e 6e 65 6c 2f 53 65 74 42 72 69 67 68 74 6e 65 73 73 22 2c 22 42 72 69 67 68 74 6e 65 73 73 22 3a 35 30 7d <cs_lo> <cs_hi> 02
```

JSON body: `{"Command":"Channel/SetBrightness","Brightness":50}`

### 5.2 Brightness (legacy binary, opcode 0x32)

```
01 04 00 32 [value] <cs_lo> <cs_hi> 02
```

Also works. Same effect as the JSON path, 2 bytes shorter. Good for latency-sensitive pulses/fades.

### 5.3 Screen on/off (JSON)

```json
{"Command":"Channel/OnOffScreen","OnOff":0}  // screen goes fully dark
{"Command":"Channel/OnOffScreen","OnOff":1}  // screen returns (to whatever view was last active)
```

**Confirmed visually.** Audio is not affected.

### 5.4 Tool views (raw opcode 0x72)

Opcode `0x72 SPP_SET_TOOL_INFO`. **Ground-truth tool-type mapping from `ToolModel.TYPE` enum in the app**:

```java
enum TYPE {
    STOPWATCH(0),
    SCOREBOARD(1),
    NOISESTATUS(2);
}
// tool 3 = COUNTDOWN (inferred from CmdManager.q3)
```

First arg of the frame is the tool type, remaining args are tool-specific:

| Tool type | Tool | Full arg layout | Example |
| --- | --- | --- | --- |
| `0x00` | **Stopwatch** | `[on, min_lo, min_hi, sec_lo, sec_hi]` | ⚠️ alarm when crossing minute |
| `0x01` | **Scoreboard** | `[on, red_lo, red_hi, blue_lo, blue_hi]` — scores are 2-byte LE uint | ✅ silent |
| `0x02` | **Noise meter** (NOISESTATUS) | `[on, ?_lo, ?_hi]` — 2 bytes, meaning not confirmed | ✅ silent |
| `0x03` | **Countdown** | `[on, min, sec]` | ⚠️ alarm at zero |

All tool views are **confirmed visually** on Minitoo. Turning off a tool (`on=0`) **zeros the display but does not exit the tool view** — see §5.6.

#### Scoreboard (tool 1) — confirmed layout

```
01 07 00 72 01 [on] [red_lo] [red_hi] [blue_lo] [blue_hi] <cs_lo> <cs_hi> 02
```

- **Blue** score is on the **top** of the screen; **red** is on the **bottom**. Each has a "+" increment button (touch-sensitive on device).
- Scores are 2-byte little-endian uint16.
- Example — red=7, blue=3: `01 07 00 72 01 01 07 00 03 00 8C 00 02`
- Example — red=100, blue=255: `01 07 00 72 01 01 64 00 FF 00 E0 00 02`
- Sending fewer than 5 arg bytes → firmware reads past the buffer and shows garbage numbers.

#### Stopwatch (tool 0) — confirmed name, partial layout

Sending `72 00 00` while in another tool view switches to stopwatch in **stopped position**.  
⚠️ **Alarms**: fires loud audio when the stopwatch crosses a minute boundary or is stopped. **Avoid at night.**

#### Noise meter (tool 2) — confirmed visible

Frame `01 07 00 72 02 01 [?] [?] [?] [?] <cs> 02` shows a **real-time sound level meter** on screen. Silent (doesn't produce audio, it *measures* audio from the mic).

Arg semantics not yet mapped — the bytes after `on` probably control color / sensitivity / range.

#### Countdown (tool 3) — confirmed

`[on, min, sec]`, 3 bytes. ⚠️ **Alarms** loudly when the timer hits zero. **Avoid at night.**

### 5.5 Scoreboard/tool OFF doesn't exit the view

Setting `on=0` in any tool command only **zeros the displayed values** — the tool view stays active. Example: `01 07 00 72 01 00 00 00 00 00 <cs> 02` leaves you looking at a scoreboard displaying `0 / 0`, not at the clock face.

### 5.6 There is no software "return to clock face" command

Confirmed from the decompile and by probing: **the official Divoom app never sends any opcode to exit a tool view.** The `onDestroy()` of each tool fragment (`StopwatchFragment`, `NoiseFragment`, `ScoreboardFragment`, `CountDownFragment`) sends **nothing** to the device. Exiting a tool is a **hardware button press on the Minitoo itself.**

Opcodes probed as candidates — all no-ops on Minitoo in tool view:

| Probe | Result |
| --- | --- |
| `raw bd 17 ff` (USE_USER_DEFINE_INDEX = -1, Ditoo reset pattern) | no change |
| `raw bd 16 00` (CLEAR_USER_DEFINE_INDEX) | no change |
| `raw bd 21 00` / `21 01` (SPP_SECOND_TOUCH, unused by app) | no change |
| `raw bd 2f 03` (OPEN_SCREEN_CTRL unknown arg) | screen went **dark** (acts like `0`) |
| `raw 84` (RESET_NOTIFICATIONS) | no change |
| `raw 1a` (STOP_SEND_GIF) | no change |
| `raw 3e` (MOVE_RESET_IFRAME) | no change |
| `Danmaku/SendBlueText` JSON | no visible effect |

**Design implication for the library:** any function that enters a tool view should warn the caller that a hardware button press is required to return.

### 5.7 Screen on/off — the confirmed opcode map

Two overlapping ways to control the backlight:

**JSON:** `{"Command":"Channel/OnOffScreen","OnOff":0|1}` — works.

**Binary (OPEN_SCREEN_CTRL, ext 0x2F under 0xBD):**

| Arg | Behavior on Minitoo |
| --- | --- |
| `0` | Screen OFF |
| `1` | Screen ON (restores whatever view was active — clock face, scoreboard, etc.) |
| `2` | No visible effect |
| `3` | Screen OFF (same as 0) |

The view underneath is **preserved** across off→on cycles — this is screen-backlight control, not a mode switch.

## 6. Commands that do NOT work on Minitoo (even though they're in the app)

The Android app has code for these, but either routes them over HTTP (cloud-only) or the Minitoo firmware doesn't implement them:

- `Channel/SetIndex` (cloud/WiFi devices only — Pixoo64, Times Gate, etc.)
- `Channel/SetClockSelectId` (app sends via HTTP; not BT-wired for Minitoo)
- `Channel/SetCustomPageIndex`
- `Channel/SetClockStyle`, `Channel/ResetClock`
- `Tools/SetTimer` / `Tools/SetStopWatch` / `Tools/SetScoreBoard` as **JSON** — the JSON command is silently dropped by the firmware; the equivalent **binary** opcode `0x72` is the working path.
- `Device/GetClockInfo`, `Channel/GetAll`, `Channel/GetConfig`, `Channel/GetClockInfo` — all GET probes got zero Channel/* response.
- Naive `Tomato/Set`, `WhiteNoise/Set`, `Alarm/Listen`, `Danmaku/SendBlueText` — no visible effect when the device is in clock-face mode. They may require a prior view-switch we haven't found yet.

## 7. Known responses and broadcasts

### 7.1 GET commands that actually respond

Most JSON GET probes silently go nowhere. The following are confirmed to produce a JSON reply over SPP_JSON:

**`Device/GetStorageStatus`** →
```json
{"Command":"Device/GetStorageStatus","Full":0}
```

**`WhiteNoise/Get`** →
```json
{"Command":"WhiteNoise/Get","OnOff":0,"Time":0,"EndStatus":0,"Volume":[0,0,0,0,0,0,0,0]}
```
Notable: **8-channel `Volume` array** — the Minitoo has 8 separate white-noise channels (rain, fire, waves, etc. — channel-to-sound mapping not yet confirmed).

### 7.2 GETs that do NOT respond

These were probed and produced **no JSON reply** (only the background Tomato keepalive continued):
`Channel/GetAmbientLight`, `Tomato/GetList`, `Tomato/GetFocusList`, `Sys/DevUpdateConf`, `Device/GetUpdateInfo`, `Channel/GetConfig`, `Tools/GetStopWatch`, `Tools/GetScoreBoard`, `Tools/GetNoiseStatus`, `Tools/GetTimer`, `Channel/GetIndex`, `Channel/GetClockInfo`, `Device/GetClockInfo`, `Channel/GetAll`, `Device/GetDispClassify`, `Device/GetDispItemList`.

Either the Minitoo firmware doesn't implement these command names, or it does but the responses go somewhere other than the SPP JSON channel (e.g. only to cloud / MQTT handlers that we're not impersonating).

### 7.3 Unsolicited broadcasts

**Keepalive (17 bytes):**
```
01 0D 00 04  F7 55  4E 6F 62 02 D0 49 41 00  D8 03 02
```
- Decodes as: wrapper `[04][F7][55]` then 8-byte payload `4E 6F 62 02 D0 49 41 00`.
- ASCII `Nob·ÐIA·` — looks like a device identifier or sequence number. Emitted every few seconds.

**Pomodoro state (`Tomato/FocusAction` JSON):**
```json
{"Command":"Tomato/FocusAction","TomatoId":143341,"StartTime":1772064536,"EndTime":1772066036,"FocusTime":25}
```
Broadcast periodically even with no active pomodoro. Appears to be the firmware's "current pomodoro context" snapshot.

**Short-form ACK** (after `SetBrightness`/`SetToolInfo`):
```
01 06 00 04 [cmd_echo] 55 [value] [status?] <cs> 02
```
Example after `brightness=50`: `01 06 00 04 32 55 32 C3 00 02`. The `55` byte is a consistent magic marker for app-protocol frames.

**Tool state broadcast** (after any 0x72 command):
```
01 09 00 04 71 55 [tool_type] [on] [arg0_lo] [arg0_hi] <cs> 02
```
Example after countdown 30s set: `01 09 00 04 71 55 03 01 01 00 D8 00 02` → tool=3 (countdown), on=1, first arg=0x0001.

## 8. Custom pixel / GIF display — the real path

**✨ Major finding (confirmed empirically):** the Minitoo firmware *does* have a direct, BT-only pixel upload pipeline. Sending `{"Command":"Draw/LocalEq","FileId":"<anything>"}` puts the screen into a **"LOADING…" state with an hourglass** — the device is awaiting chunked pixel data. If we deliver the right bytes, it will render whatever we send.

### 8.1 End-to-end flow (from `DesignSendModel` + `CmdManager.Z()` + `BluePixelPictureModel`)

Two BT paths exist; the Minitoo uses the second because its `UiArchEnum = BlueHighPixelArch`:

**Path A — Ditoo/Pixoo class (DevicePixel16/64):**  
`CmdManager.s1(pixelBean)` → single-frame pixel bean sent inline. Not the Minitoo path.

**Path B — Blue-high-pixel class (DevicePixel128 → Minitoo):**  
1. Encode the image(s) as JPEG frames with a Divoom header (see §8.2).
2. Announce total size: send `SPP_LOCAL_PICTURE` (opcode `0x8F`) with args `[0x00, <size_u32_LE>]`.
3. Split the encoded blob into 256-byte chunks, wrap each in `SPP_LOCAL_PICTURE` frames with chunk-index metadata (produced by `e3/h.d()`).
4. Stream chunks with ~100 ms pacing (the official app throttles progress updates to 100 ms).
5. Device reassembles, validates, and renders.

Notably, **no Divoom cloud is required** for this path — the confusing detour via `Channel/SetCustom` (cloud → FileId → BT) is one *specific* code path the app uses when the user picks from the cloud gallery. For library use, we skip the cloud entirely and drive path B directly.

### 8.2 Pixel encoding (`W2.c.m(pixelBean, 0)`)

Per the decompile:

```
Header (6 bytes):
  [0]   = 0x1F                    // magic
  [1]   = validCnt (frame count)
  [2-3] = speed                   // BIG-endian uint16, inter-frame delay in ms
  [4]   = rowCnt                  // pixel rows
  [5]   = columnCnt               // pixel cols

Per frame (one JPEG):
  [0-3] = jpeg_length              // LITTLE-endian uint32
  [4…]  = JPEG-encoded bitmap

Optional appended text:
  [0-3] = text_length              // LITTLE-endian uint32
  [4…]  = UTF-8 bytes
```

The JPEG path iterates up to 8 times, stepping quality down by 5% each iteration, trying to fit `jpeg_length <= target_size` (where target_size is derived from a caller-provided budget `i9` divided by `validCnt`). Minitoo `rowCnt`/`columnCnt` is likely `128`/`128` but not yet confirmed — we should send a test frame and observe.

Each frame ends up as a real JPEG — the firmware decodes with a standard JPEG decoder and blits to its 128-pixel display.

### 8.3 Chunking (`e3/h.d()` with default config)

- Chunk size: **256 bytes** (set via `hVar.q(256)` in `CmdManager.Z()`).
- Header per chunk (depends on device pixel-model):
  - `DevicePixel128` → `[total_len_u32_LE, chunk_index_u16_LE]` prepended to payload.
  - `DevicePixel16` → `[total_len_u16_LE, chunk_index_u8]` (old devices).
- There's also an optional flag `f30375j` that switches the header to `[chunk_size_u16]` instead — set in the "big" image case.

The chunked data is wrapped in standard framing (`0x01 … 0x02`) with opcode `SPP_LOCAL_PICTURE`.

### 8.4 What the library has to implement

Rough work estimate:

1. **PixelBean abstraction** — frame list + speed + rowCnt/columnCnt. (Trivial.)
2. **Divoom-format encoder** — input = list of `NSImage`/`CGImage`/PNG frames, output = JPEG-packed byte blob with the §8.2 header. (Medium — needs a JPEG encoder with quality-targeting loop. macOS has `NSBitmapImageRep` → JPEG.)
3. **Chunk splitter** — `[total_size_header] + [per_chunk_index_header + chunk_body]`. (Easy once §8.2 encoding is right.)
4. **Upload driver** — fire the size-announcement frame, then stream chunks every ~100 ms over the existing SPP_JSON / raw-opcode transport we already have.

### 8.5 Stopping the LOADING screen

**⚠️ Correction from earlier draft:** `Draw/LocalEq` is the **audio equalizer / music visualizer** upload path, not the "set a custom face" path. We triggered it in testing and the device:
1. Entered a **LOADING screen** awaiting pixel chunks.
2. Replied with `01 12 00 04 BD 55 28 <len> <FileId bytes>` — the firmware is actively **requesting the file by ID** and will continue requesting until the chunks arrive or it times out.
3. When we fed it ~16 chunks of our Divoom-formatted JPEG blob, the device **entered photo-album slideshow mode** — playing back pre-existing gallery photos. Our upload either got rejected and the device defaulted to gallery, or our upload was accepted and joined the album rotation (inconclusive).

Known exits from LOADING:

- `raw 8f 00 00 00 00 00` (SPP_LOCAL_PICTURE with `[0x00, size_u32=0]`) → LOADING flashed for ~1s then returned to clock face. **Works for LOADING but not for the subsequent album-slideshow mode.**
- **Hardware button** on the Minitoo is the universal reset.
- The device retains the file-request state across probe cancels — even after the zero-size cancel, it keeps emitting `request FileId` frames for a while.

### 8.6 Corrected understanding of the "set custom display" path

The product-level requirement "show different pictures for different states" likely does NOT go through `Draw/LocalEq`. Evidence:
- `Draw/LocalEq` = equalizer — triggers EQ mode.
- `Draw/*` namespace in general = pixel-art drawing tool (user's paint canvas), not face selection.
- `Channel/SetCustom` = what the WiFi devices use (cloud FileId flow).
- What actually works for Minitoo is likely the **Photo Album path** — see §8c below.

---

## 8c. View-mode switchers — confirmed on Minitoo

These are the **confirmed, visually-verified** top-level view switchers. The Minitoo maintains a **"current mode" stack** — entering a new mode replaces the active one, and exiting some modes returns to the *previous* mode rather than to the default clock face. (Reboot / hardware button restores the clock face as the default.)

### JSON `*/Enter` commands (opcode 0x01 SPP_JSON)

| Command | Effect | Verified |
| --- | --- | --- |
| `{"Command":"Photo/Enter"}` | Switch to photo gallery slideshow (plays built-in photos if no custom album) | ✅ |
| `{"Command":"Lyric/Enter"}` | Switch to **animated astronaut screensaver** (also used for music lyric overlay) | ✅ |
| `{"Command":"Google/EnterCalendar"}` | No visible effect on Minitoo | ❌ no-op |
| `{"Command":"Outlook/EnterCalendar"}` | Not tested; WiFi-only likely | — |

### Binary game-enter (SPP_SET_GAME = opcode 0xA0)

Minitoo uses a **binary** opcode, not JSON, for games. The JSON `Game/Enter` is silently dropped — the `GameModel.b()` code in the app splits on `WifiBlueArchEnum`: WiFi devices get the JSON, BT-arch devices (Minitoo) get the binary opcode.

```
01 05 00 A0 [on_flag] [game_id] <cs> 02
```

| Frame | Effect | Verified |
| --- | --- | --- |
| `raw a0 01 00` | Enter **Tetris** start screen | ✅ |
| `raw a0 01 01` | Enter a different Tetris variant | ✅ |
| `raw a0 01 05` | Different game (unknown variant) | ✅ |
| `raw a0 01 0A` | Different game | ✅ |
| `raw a0 00 00` | **Exit game** → falls back to previous mode (NOT to clock face) | ✅ |

So `game_id` selects among the device's built-in game ROMs; valid range is likely 0–15 or 0–31 (not exhaustively mapped). `on_flag=0` exits game mode but preserves the prior mode stack.

### Still no direct "return to clock face"

Confirmed exhaustively: **the firmware has no command to jump back to the default clock/dog face**. Only paths:
- Hardware button on the device.
- Device reboot.
- Firing another `*/Enter` cycles to a known mode, but never to the clock face.

The scoped-exit commands (`Game/Exit`, `Channel/ExitNightPreview`, `Draw/ExitSync`, `Sleep/ExitTest`) all drop back to the *previous* mode, not the clock face.

### Animated "states" inventory — what we can actually drive

For a state indicator that cycles between **distinguishable visual modes**, all without any pixel upload:

| Slot | Mode | Command |
| --- | --- | --- |
| Default | Clock / dog face | hardware button or reboot |
| 1 | Astronaut screensaver | `{"Command":"Lyric/Enter"}` |
| 2 | Photo slideshow (built-in photos) | `{"Command":"Photo/Enter"}` |
| 3 | Tetris | `raw a0 01 00` |
| 4 | Game 2 | `raw a0 01 01` |
| 5 | Game 5 | `raw a0 01 05` |
| 6 | Scoreboard `<red>/<blue>` | `raw 72 01 01 <r_lo r_hi b_lo b_hi>` |
| 7 | Noise meter | `raw 72 02 01 <2 bytes>` |
| — | Dim/bright overlay on any of the above | `Channel/SetBrightness 0–100` |
| — | Screen off / on | `raw bd 2f 00` / `raw bd 2f 01` |

**For the "custom GIF per state" requirement** (the user's actual goal), this inventory isn't enough — the user wants *their own* animations, not Divoom's built-ins. That requires the photo-upload-to-custom-album path, documented next.

### Photo album — the probable path for custom state images

The Minitoo has a **photo-album feature** (plays a list of stored images in slideshow). APIs:

| JSON Command | Purpose |
| --- | --- |
| `Photo/NewAlbum` `{ClockId, ClockName}` | Create a new album |
| `Photo/LocalAddToAlbum` (complex fields) | Add a photo locally (BT) — fields include `FileName`, `PhotoFlag`, `PhotoIndex`, `PhotoTotalCnt`, `Photo{Width,Height,X,Y}`, `PreviewFileName`, etc. |
| `Photo/DevicePhotoToAlbum` `{PhotoList, ToClockId}` | Copy already-on-device photos into an album |
| `Photo/PlayAlbum` `{AlbumId}` | Play a specific album as slideshow |
| `Photo/DeletePhoto`, `Photo/DeleteAlbum`, `Photo/RemovePhotoFromAlbum` | cleanup |
| `Photo/Enter` | Switch to photo view (required before PlayAlbum likely) |

This means for **state-dependent images on the Minitoo**:
1. One-time setup: create N albums (one per state), upload one or more photos per album.
2. Runtime: on state change, your Mac app fires `Photo/Enter` + `Photo/PlayAlbum {AlbumId: N}` over our BT daemon.
3. Exit: hardware button or swap to another `*/Enter` mode.

The photo-upload protocol is still to be mapped (similar chunking to §8.3). This is the recommended next investigation.

### Observations from `Photo/PlayAlbum` probes

- `{"Command":"Photo/PlayAlbum","AlbumId":1}` while on clock face → no visible effect (clock stays).
- `{"Command":"Photo/Enter"}` → switches to slideshow of built-in photos. This is what *does* work.
- `{"Command":"Photo/PlayAlbum","AlbumId":0}` while already in photo view → still a slideshow but we can't tell if it's a different album set.

Leading hypothesis: `Photo/PlayAlbum` only has effect *after* the device is in photo view, **and** only if the specified `AlbumId` actually exists (which for stock Minitoo means either album 0 = built-ins, or any IDs we create via `Photo/NewAlbum`).

### Known-silent-to-Minitoo photo commands

These got no JSON response when probed (device ignored them):
`Photo/GetAlbumList`, `Photo/GetPhotoList`.

## 8d. Photo upload — full protocol (decoded from `BluePhotoModel.java`)

**This is the BT-native pipeline for the Minitoo (not the WiFi `uploadFileToLocalDevice` path).** It's what we need to display arbitrary images on the screen.

### Flow

1. **Create album** (one-time setup, per state):
   `{"Command":"Photo/NewAlbum","ClockId":<id>,"ClockName":"<label>"}`
2. **Send JSON metadata header**:
   ```json
   {
     "Command": "Photo/LocalAddToAlbum",
     "ClockId": <albumId>,
     "FileName": "<userid>-<timestamp>.webp",
     "PhotoFlag": <random_u32>,      // per-batch session id
     "PhotoIndex": 0,
     "PhotoTotalCnt": 1,
     "PhotoWidth": 128,
     "PhotoHeight": 128,
     "PhotoX": 0, "PhotoY": 0,
     "PhotoTitle": "",
     "SendTime": <ms>, "TakingTime": <ms>
   }
   ```
3. **Send binary header via `SPP_LOCAL_PICTURE` (0x8F)** — this is the **12-byte header** we originally got wrong:

   ```
   01 [len_lo len_hi]  8F
     00                         # 1 byte marker
     [file_size_u32_LE]         # 4 bytes: total photo bytes
     [photoFlag_u32_LE]         # 4 bytes: must match JSON PhotoFlag
     [fileType_u8]              # 1 byte: 1=photo, 3=video frame
     [totalCount_u8]            # 1 byte: same as JSON PhotoTotalCnt
     [fileIndex_u8]             # 1 byte: same as JSON PhotoIndex
   [cs_lo cs_hi]  02
   ```

4. **Stream 256-byte chunks**, each wrapped in `SPP_LOCAL_PICTURE`:

   ```
   01 [len_lo len_hi]  8F
     01                         # 1 byte chunk marker
     [total_len_u32_LE]         # 4 bytes: same file_size as step 3
     [chunk_index_u16_LE]       # 2 bytes: 0, 1, 2, …
     [payload bytes (up to 256)]
   [cs_lo cs_hi]  02
   ```

   The app paces these with ~100 ms progress updates; in practice we can blast faster but keeping ~20 ms between chunks is safe.

5. **Play the album**: `{"Command":"Photo/PlayAlbum","AlbumId":<albumId>}`  
   (possibly also `Photo/Enter` first to make sure photo view is active — confirmed).

### Image format

The app uploads **WebP** by default (`.webp` FileName extension). The file bytes are the raw WebP file, no Divoom header wrapper on the photo data itself (the 12-byte SPP_LOCAL_PICTURE header is the only wrapper). The Minitoo has a WebP decoder in firmware.

Whether the firmware also accepts JPEG/PNG is an open question — simplest strategy is to always encode to WebP (Python `Pillow` supports this out of the box).

### Config from `BluePhotoModel.n()` (the setup helper)

```java
h hVar = new h();
hVar.l(new byte[]{1});   // chunk prefix byte = 0x01
hVar.i(true);            // f30374i=true → 2-byte chunk index
hVar.q(256);             // chunk size = 256
```

And chunk-header sizes for DevicePixel128 (Minitoo) derived in `e3.h.f()`:
- Total-length field = **4 bytes LE** (i9 = 4)
- Chunk-index field = **2 bytes LE** (i11 = 2, because `hVar.i(true)` set it)

### Earlier failure explained

In the session we tried an SPP_LOCAL_PICTURE upload with a **5-byte header** (`[0x00, size_u32_LE]`) — that was from the simpler `CmdManager.Z()` path (used by `BluePixelPictureModel` for pixel-art, not by `BluePhotoModel` for photos). The extra 7 bytes (`photoFlag`, `fileType`, `totalCount`, `fileIndex`) are **mandatory for the photo pipeline**. That's why the device drifted into the gallery playback — it received chunks whose outer framing didn't match an active file-upload session.

### Still-open for full photo upload

- [ ] Exact minimum set of JSON fields that `Photo/LocalAddToAlbum` actually *reads* (the base class has a lot of cruft like `LcdIndependence`/`LcdIndex`/`ParentClockId` that may be ignored).
- [ ] What the device broadcasts back during the upload (ACKs? progress? error codes?). `raw BD 55 28` broadcasts we've seen so far are "please send the file" pings.
- [ ] Required chunk pacing — did `BluePhotoModel` throttle for flow control, or just for UI progress updates?
- [ ] Minitoo's actual photo display dimensions (we've been assuming 128×128 based on `DevicePixel128` but it could be non-square).
- [ ] The `BluePixelPictureModel` 5-byte header path (`CmdManager.Z`) — is there a separate "pixel art drawing" pipeline that *does* work on Minitoo and we haven't hit yet?

Once those are filled in, creating custom screens-per-state reduces to: one-time `Photo/NewAlbum` per state + one `Photo/LocalAddToAlbum` per frame, then `Photo/PlayAlbum` at runtime.

## 9. Per-opcode Minitoo support matrix (from systematic doc-driven probe)

After referencing the official Divoom docs (§8z), every documented opcode was probed against Minitoo with a no-side-effect arg. The matrix below records empirical results — not protocol assumptions. Rule: **only document what works**; non-working opcodes are noted but should not be relied on, since Minitoo likely has its own equivalents we haven't found yet.

### ✅ GETs that actually respond on Minitoo

| Opcode | Doc name | Response shape | Decoded |
| --- | --- | --- | --- |
| `0x06` | get sd play name | `01 05 00 04 06 55 [val]` | 1-byte payload (0x64 = 100 observed) |
| `0x09` | Get vol | `01 06 00 04 09 55 [vol]` | 1 byte, 0–15 (observed 0x08 = 8) |
| `0x0b` | Get play status | `01 06 00 04 0b 55 [status]` | 1 byte (observed 0x00 = paused) |
| `0x13` | Get working mode | `01 06 00 04 13 55 [mode]` | 1 byte (observed 0x00 = BT mode) |
| `0x71` | Get tool info | `01 06 00 04 71 55 [byte]` | 1 byte (observed 0x74) |
| `0x76` | Get device name | `01 06 00 04 76 55 [len][name…]` | 1 byte (0x00 = no name set) |
| `0xa2` | Get sleep scene | `01 0f 00 04 a2 55 0a 01 00 00 00 32 ff 55 00 32` | 10-byte rich payload (scene cfg + 0x32=50 vol) |
| `0xb4` | Get sd music info | `01 0e 00 04 b4 55 00 00 00 00 00 00 00 08 00` | 8-byte payload (status + counters) |
| `0x15` | Send sd card status | `01 06 00 04 15 55 00` | 1-byte status (0x00 = no SD) |
| `0x07` | Get sd music list | `01 05 00 04 14 55 72` | Replies via opcode `0x14 Send sd list over` with 1 byte |
| `0x47` | App need get music list | `01 05 00 04 47 55 a5` | 1-byte payload |

The standard response envelope is `01 [len] 04 [echoed_opcode] 55 [data…] [csum] 02`. The `0x55` byte is the constant marker for app-protocol responses.

### ✅ EXT commands (`0xBD <ext_op>`) that respond on Minitoo

The `0xBD` wrapper opcode carries a second-level opcode. From the `probe-ext.sh` sweep (39 documented EXT commands), these respond with non-keepalive body:

| EXT op | Doc name | Response shape | Decoded |
| --- | --- | --- | --- |
| `0x13` | SECOND_SET_GIF_TYPE | `04 bd 55 13 01 05 00` | Fixed 3-byte reply regardless of arg (tested `00..03`); likely a capability code, not state. Does **not** change displayed face. |
| `0x18` | SECOND_GET_NEW_POWER_ON_CHANNEL | `04 bd 55 18 01 36` | 2-byte payload: `0x01` (flag) + `0x36` (power-on channel id) |
| `0x27` | SECOND_SUPPORT_MORE_ANCS | `04 bd 55 27 01 45` | 2-byte payload: capability bits — likely `0x01` (supported) + `0x45` |
| `0x2b` | SECOND_GET_DEVICE_INFO | `04 bd 55 2b eb 54 c4 23 ab 95 5f 69 00 01 80` | 11-byte rich payload — likely MAC-like identifier + version bits |

**Face change during probe-ext.sh**: user reported the probe sequence briefly changed the clock face. Candidate culprits among responding commands: `0x13` (ruled out — tested separately with 4 arg values, response identical, no visible change per 4-value test) or a side effect of `0x2f OPEN_SCREEN_CTRL` which toggled screen off+on. **Non-responding EXT commands are not pursued** per the "only document what works" rule.

### ⚠️ DO NOT PROBE — bricks the device until power-cycle

These were sent during `probe-system.sh`. Each is silent (no ACK), but **collectively** they put Minitoo into a "sleep monitoring" state: the screen goes to a black rectangle, the joystick stops responding, and the device starts emitting an unsolicited periodic `0xa2` sleep-scene broadcast (`rx[19]: 01 0f 00 04 a2 55 0a 01 00 00 00 32 00 b1 00 00 f8 01 02`). None of `Channel/OnOffScreen`, `Lyric/Enter`, `Photo/Enter`, `Channel/SetBrightness`, `0xa0 00 00`, or `0xbd 0x2f 01` recovers. **Only a hardware power-cycle restores the device.**

| Opcode | Doc name | Suspected effect |
| --- | --- | --- |
| `0x40` | Set sleep auto off | enters sleep monitor |
| `0xa3` | Set sleep scene listen | enters sleep monitor |
| `0xa4` | Set scene vol | likely benign alone, but compounds |
| `0xad` | Set sleep color | may set background colour to black |
| `0xae` | Set sleep light | likely turns the display backlight off in sleep mode |

The exact culprit within this group hasn't been narrowed down (probing more would brick the device again). Treat the whole sleep family as off-limits until/unless we understand the exit path. If you must probe one, do it alone, with a hardware power-button reachable.

### ✅ SETs verified on Minitoo

| Opcode | Doc name | Args | Effect |
| --- | --- | --- | --- |
| `0x01` | SPP_JSON (UTF-8 JSON body) | `{Command, …}` | Carries `Channel/SetBrightness`, `Channel/OnOffScreen`, `Lyric/Enter`, `Photo/Enter` |
| `0x32` | Set lightness | `[0–100]` | Brightness, with JSON ack `Channel/SetBrightness` |
| `0x72` | Set tool info | `[tool_type, …]` | Switches tool view (0=stopwatch, 1=scoreboard, 2=noise, 3=countdown) |
| `0xa0` | Set game | `[on_flag, game_id]` | Enter game mode (Tetris etc.); `[0,0]` exits to previous mode |
| `0xbd 0x2f` | OPEN_SCREEN_CTRL (ext under 0xBD) | `[arg]` | `0`=screen off, `1`=screen on (restores prev), `3`=off, `2`=no-op |
| `0x8f` | SPP_LOCAL_PICTURE (undocumented officially) | header + chunks | Uploads photo into gallery rotation |

### Silent on Minitoo (probed with valid args, no ACK and no visible effect)

These are documented opcodes that the Minitoo firmware does **not** implement (or implements over a different command we haven't found). Silent here ≠ "ignored permanently" — it just means our standard probe didn't elicit a response. **Do not rely on these.**

`0x42` Get alarm time, `0x46` Get light mode, `0x53` Get memorial time, `0x59` Get device temp, `0x73` Get net temp disp, `0x7d` Get sd music list total num, `0xa8` Get sound ctrl, `0xac` Get auto power off, `0xb3` Get low power switch, `0x8e` App get user define info, `0x16` Set gif speed, `0x2b` Set temp type, `0x2c` Set hour type, `0x74` Set brightness (Minitoo uses `0x32`), `0x5d/0x5e/0x5f` temperature commands, `0x83` Set song display, `0x8c` App new user define, `0x8d` App big64 user define, `0x6b/0x6c/0x6d/0x6e/0x6f` Drawing-pad family, `0x44` Set light pic, `0x49` Set light phone gif (untried but expected silent — needs `divoom_image_encode_encode_pic` we don't have).

### Probe tooling

`core/probes/probe-gets.sh` and `core/probes/probe-sets.sh` send batches of opcodes; `core/parse-probe.py` parses `/tmp/divoom-send.log` and pairs each TX with the RX frames that followed (filtering out the 17-byte keepalive and the periodic Tomato/FocusAction broadcast).

To extend the matrix: add `(opcode_hex|name|args_hex)` lines to either probe script, run, then `./parse-probe.py`.

---

## 8z. Divoom OFFICIAL developer documentation (referenced post-hoc)

A GitHub search for distinctive opcode names led to [`ztomer/divoom_lib`](https://github.com/ztomer/divoom_lib), which **scraped Divoom's official developer docs** at [`https://docin.divoom-gz.com/web/`](https://docin.divoom-gz.com/web/) — 93 pages covering essentially every SPP command. We didn't know this existed earlier; if you're starting fresh this is the canonical reference.

Cloned to `/tmp/ztomer-divoom/api_scraper/divoom_docs/`. Top-level files:
- `light.md` — pixel-art / image / GIF / drawing-pad opcodes (the meaty one)
- `system_settings.md` — brightness, time, device name, etc.
- `tool.md` — stopwatch / scoreboard / noise / countdown
- `alarm_memorial.md`, `game.md`, `music_play.md`, `sleep.md`, `timeplan.md`
- `divoom_api_full.json` — same content, parseable

The docs confirm and extend our reverse engineering:

### Key "play arbitrary artwork by id" primitive — `0x8d` (App big64 user define)

Per the official doc, opcode `0x8d` has **6 control words**:

| Control_Word | Effect | data |
| --- | --- | --- |
| 0 | Start sending. Wait for device response | `[file_size_u32_LE, index_u8, file_id]` |
| 1 | Send data chunk | `[total_len_u32_LE, offset_u16_LE, payload up to 256B]` |
| 2 | Terminate sending | empty |
| **3** | **Delete a specific artwork** | `[file_id, index_u8]` |
| **4** | **PLAY a specific artwork** | `[file_id, index_u8]` |
| **5** | **Delete all files of a specific index** | `[index_u8]` |

This is **the deterministic image-selection primitive we've been hunting** — upload to a slot, then `0x8d Control_Word=4 [file_id, index]` to display it. The docs technically describe this for 64×64 devices; needs testing on Minitoo.

### Companion: `0x8e` (App get user define info) — enumeration

Send `[user_index]`, device responds with the list of `file_id`s stored at that index. This is how we'd discover what's already on the device.

### `0x8c` (App new user define) — the simpler upload variant

For the user-defined animation slot. **Same protocol shape as 0x8d but no play/delete control words documented.** The control words 0/1/2 (start/send/end) are identical. Our `pixel-art.py` was using `0x8f SPP_LOCAL_PICTURE` (which is **not in the official docs at all** — newer/undocumented), but `0x8c` is the documented form and worth re-attempting.

### Documented opcodes inventory (light.md only — full list)

```
0x16  Set gif speed
0x1b  App send eq gif
0x34  Sand paint ctrl
0x35  Pic scan ctrl
0x44  Set light pic
0x45  Set light mode
0x46  Get light mode
0x49  Set light phone gif
0x58  Drawing pad ctrl
0x5a  Drawing pad exit
0x5b  Drawing mul encode single pic
0x5c  Drawing mul encode pic
0x6b  Drawing mul encode gif play
0x6c  Drawing encode movie play
0x6d  Drawing mul encode movie play
0x6e  Drawing ctrl movie play
0x6f  Drawing mul pad enter
0x87  Set light phone word attr
0x8b  App new send gif cmd
0x8c  App new user define
0x8d  App big64 user define   ← has Control_Word 3/4/5
0x8e  App get user define info
0xb1  Set user gif (legacy)
0xb6  Modify user gif items
0xb7  Set rhythm gif
0x3a  Drawing mul pad ctrl
0x3b  Drawing big pad ctrl
```

### Sibling project worth checking
[`DavidVentura/divoom`](https://github.com/DavidVentura/divoom) also has decompiled-sources and a Python implementation — for cross-referencing.

## 8h. The eZip native lib — **bridged to macOS** ✅

**Status: working ✅.** SiFli's eZIPSDK (the proprietary encoder the photo-pipeline needs) **runs natively on Apple Silicon Macs**, no Frida/QEMU/SDK rebuild required.

### How

GitHub search for `sifliEzipUtil` surfaces [`shixin627/sifli_ezip`](https://github.com/shixin627/sifli_ezip), a Flutter plugin that vendors the official **`eZIPSDK.framework`** under `ios/Frameworks/`. The framework binary is a static `.a` archive built for iOS arm64; the relevant object files (`ImageConvertor.o`, `eZIP_core.o`, `lz4.o`, `lodepng.o`, `gif.o`, `parse_px.o`, `ezip.o`, `FileValidator.o`) have **no UIKit/iOS-only dependencies** — only Foundation `NSData/NSString/NSArray` and standard C/C++.

Linking it into a macOS arm64 binary fails by default because each `.o` carries `LC_VERSION_MIN_IPHONEOS`. Workaround: patch the load-command type byte in each object from `0x25` (`IPHONEOS`) to `0x24` (`MACOSX`) — same struct size, no relocations needed. After that, `clang++ -arch arm64` links cleanly with `-framework Foundation -ObjC` (and you need `clang++` for the C++ runtime: lodepng + parse_px are C++).

**Tooling delivered**: `core/ezip/png2ezip` — a 170 KB macOS arm64 binary that takes a PNG and writes the eZip output.

```bash
./png2ezip /tmp/in.png /tmp/out.bin
# logs:
#   EBinFromPNGData version=2.4.5,color=rgb565,color type=1,binType=1,boardType=2
#   output: <N> bytes ezip
```

### Public API (from `ImageConvertor.h`)

```objective-c
+ (NSData *)EBinFromPNGData:(NSData *)pngData
                     eColor:(NSString *)eColor      // "rgb565" / "rgb565A" / "rgb888" / "rgb888A"
                      eType:(uint8_t)eType          // 0 = keep alpha, 1 = no alpha
                    binType:(uint8_t)binType        // 0 = with rotation, 1 = no rotation
                  boardType:(SFBoardType)boardType; // 0 = 55X, 1 = 56X, 2 = 52X (Minitoo uses 52X)

+ (NSData *)EBinFromPngSequence:(NSArray<NSData *> *)pngDatas      // for animations
                         eColor:... eType:... binType:... boardType:...
                       interval:(uint32_t)interval;                // ms between frames
```

The args are taken straight from `BluePhotoModel.AbstractC0522n.c` in the decompile — `("rgb565", 1, 1, 2, 1000)`. Sequence variant gives us animations.

### What this unlocks

The photo-pipeline upload (`Photo/LocalAddToAlbum` + 12-byte SPP_LOCAL_PICTURE header + chunks, see §8d) was previously crashing the device because we were sending WebP/JPEG bytes where the firmware expected eZip. With the bridge running we can now feed real eZip bytes; empirical test sent a 2430-byte cyan-with-X frame **without crash**, confirming the format is correct.

The next step is to validate the image **renders** (not just survives the upload) and then to test the multi-frame `EBinFromPngSequence` path for animated state indicators.

### Reproducing the bridge

```bash
# 1. clone the Flutter plugin
git clone --depth 1 https://github.com/shixin627/sifli_ezip.git /tmp/sifli_ezip

# 2. extract objects from the iOS framework
mkdir /tmp/objs && cd /tmp/objs
ar -x /tmp/sifli_ezip/ios/Frameworks/eZIPSDK.framework/eZIPSDK

# 3. patch each .o: LC_VERSION_MIN_IPHONEOS (0x25) → LC_VERSION_MIN_MACOSX (0x24)
python3 - <<'PY'
import struct, glob, os
for o in sorted(glob.glob('*.o')):
    d = bytearray(open(o,'rb').read())
    if struct.unpack('<I', d[:4])[0] != 0xFEEDFACF: continue
    ncmds = struct.unpack('<I', d[16:20])[0]
    off = 32
    for _ in range(ncmds):
        cmd, sz = struct.unpack('<II', d[off:off+8])
        if cmd == 0x25: d[off:off+4] = struct.pack('<I', 0x24)
        off += sz
    open(o,'wb').write(d)
PY

# 4. repack
ar -rcs eZIPSDK_macos.a *.o

# 5. build a bridge from C/ObjC → CLI
clang++ -o png2ezip png2ezip.m \
    -I /tmp/sifli_ezip/ios/Frameworks/eZIPSDK.framework/Headers \
    eZIPSDK_macos.a -framework Foundation -arch arm64 -fobjc-arc -ObjC
```

The full bridge source is `core/ezip/png2ezip.m` in the toolchain.

---

## 8f. Custom image display on Minitoo — gallery path works (not status path)

**Status:** uploading `W2.c.r`-formatted JPEGs over `SPP_LOCAL_PICTURE` **successfully adds images to the Minitoo's photo-gallery rotation, rendered at full color on the display.** Confirmed empirically in this session — uploaded a purple solid and a cyan "OK" image, both appeared in the device's slideshow.

This is **not** the right path for status animation. It enters / pollutes the gallery and we still cannot select or pin a specific gallery entry. The direct status-animation path is the live `0x8B` path in §8i.

### Working format (verified)

**Divoom pixel blob (W2.c.r style):**
```
Header (6 bytes):
  [0x23, frameCount, speed_BE_u16, rowCnt=128, colCnt=160]

Per frame:
  [flag_u8 = 0x01]         # 1 = JPEG (the other option, 0x00 = MiniLZO, is native-only)
  [length_u32_BE]          # BIG-endian frame length
  [jpeg_bytes]             # baseline JPEG at quality 100
```

**Wire protocol (same as §8.3):**
1. Announce: `SPP_LOCAL_PICTURE` (0x8F) with 5-byte header `[0x00, total_size_u32_LE]`.
2. Device replies with `SPP_LOCAL_PICTURE b10=0` ("send chunks").
3. Stream 256-byte chunks, each wrapped in `SPP_LOCAL_PICTURE` with `[0x01, total_len_u32_LE, chunk_idx_u16_LE, payload]`.
4. Device reassembles, decodes JPEG, shows on screen (adds to gallery).

Tested canvas: **160 × 128 pixels** (`rowCnt=128, colCnt=160`). JPEG quality 100. Speed (`speed_BE_u16`) = `2000` (ms between frames for animations; single-frame ignores it).

### The caveat

Uploaded images land in the **photo-gallery slideshow**, not as a direct "replace current view" display. If the device is already on clock face when we upload, it switches to gallery. The gallery cycles through all previously-uploaded images plus the factory defaults.

**For "different image per state" this means:**
- ✅ Custom images can be displayed.
- ⚠️ We currently can't choose *which one* shows at a given moment — the gallery cycles through all of them.
- Open question: can we `Photo/DeletePhoto` old entries / `Photo/DeleteAlbum` the default album, so the gallery contains only the image for the current state? (Then uploading a new one replaces it.)

### Why the "native lib wall" I earlier documented was wrong

I initially thought `W2.c.r` / `W2.c.f` / eZip all required native-encoded payloads. The empirical test contradicted that: a plain JPEG with the right `0x23` header + `flag=1` routed cleanly through the firmware's JPEG decoder. The native libs are used in the Android app for **speed / compression / fallback paths**, not because the firmware rejects uncompressed formats. JPEG with the JPEG flag is a valid first-class input.

### What still needs figuring out

- [ ] Exactly how long a single-frame / animation stays on the main screen before the device falls back to gallery (empirically observed to be some seconds — needs measurement).
- [ ] Whether we can "pin" an upload so the device never falls back.
- [ ] Whether re-uploading the same animation every N seconds gives an effectively persistent display (low-cost heartbeat refresh).
- [ ] Deleting the factory-default photos so the fallback gallery is empty / shows nothing.
- [ ] Exact budget/size limits before the firmware drops frames.

### State-dependent display — partial success, state-dependent behavior

**Empirical findings from this session's uploads:**

| Pre-upload device state | Upload content | Observed behavior |
| --- | --- | --- |
| Clock face (just rebooted) | 5-frame rainbow animation | **Standalone animation playback** (frames cycled 1→5), then fell back to Chinese-people gallery |
| Gallery (Chinese people playing) | 5-frame rainbow animation | **No standalone playback** — frames joined the gallery rotation randomly |
| Gallery | single frame (TIMER, orange-A) | Image joined gallery rotation; no standalone play |
| Astronaut (Lyric/Enter) | 5-frame rainbow | Showed brief "LOADING" hourglass during upload, then frames mixed into subsequent gallery |

**So: "standalone animation playback" only happens once after a fresh boot/clock-face state.** After any gallery activation, further uploads just add to the rotation.

Even when standalone playback fires, the device **falls back to gallery after playing the uploaded animation**. There is no observed way to "pin" an upload as the permanent display.

### The gallery control problem (UNSOLVED — the blocker)

Minitoo's photo gallery ships with pre-installed stock photos ("Chinese people" — likely factory-loaded content). Every upload joins this rotation, so even successful custom uploads are hidden among ~dozens of stock photos.

The real need is one of:
- **Delete stock photos** so the gallery is empty/controllable. `Photo/DeletePhoto {ClockId, PhotoList}` exists but we don't know the factory PhotoList IDs. `Photo/GetPhotoList` returns no response.
- **Play a specific image/album by ID.** `Photo/PlayAlbum {AlbumId}` is the obvious command but it's **HTTP-only in the app** — never sent over BT to Minitoo. No BT-native equivalent found yet.
- **Pin one image as the permanent main-screen display** (replacing gallery/clock entirely). Candidate opcodes `SPP_SET_USER_GIF` (0xB1) and `SPP_SET_BOOT_GIF` (0x52) exist but their exact arg layouts are deep in CmdManager and not yet verified.

**These remain unknown for gallery control.** For state-driven custom animations, use §8i instead.

---

## 8j. Text notification with preset app icon — **WORKS reliably** ✅

**Status: confirmed, no crashes, no pixel upload required.** Single BT frame displays a notification on screen with one of 24 preset app icons (Instagram, WhatsApp, Facebook, Discord, Telegram, …) + up to 128 bytes of custom UTF-8 text.

This is the cleanest path discovered so far for state indication. Great for status messages ("DONE", "READY", "IDLE", etc.) — each state can have its own icon + text combination.

### Wire format

```
01 [len_lo] [len_hi]  50  [cmd_code_u8] [text_len_u8] [text_utf8_bytes…]  [cs_lo cs_hi] 02
```

- Opcode: **`0x50` (SPP_SET_ANDROID_ANCS)** with text payload (not pixel)
- `cmd_code` = the app/icon slot (see table below)
- `text_len` = byte length of UTF-8 text (firmware caps at 128)

Source: `CmdManager.V(int i9, String str)` in the decompiled APK. UTF-8 encoding is the standard `.getBytes("UTF-8")` — no Divoom-specific transformation (`K.z()` is just a debug printer).

### Icon slot (`cmd_code`) table — from `Constant.NOTIFICATION` enum

| cmd_code | App | cmd_code | App |
| --- | --- | --- | --- |
| `0x00` | Kakao Talk | `0x0D` | Divoom / TimeBox |
| `0x01` | **Instagram** ✓ tested | `0x0E` | Viber |
| `0x02` | Snapchat | `0x0F` | Messenger |
| `0x03` | **Facebook** ✓ tested | `0x10` | OK |
| `0x04` | Twitter | `0x11` | VK |
| `0x07` | **WhatsApp** ✓ tested | `0x12` | **Telegram** ✓ tested |
| `0x09` | Skype | `0x13` | TikTok |
| `0x0A` | Line | `0x14` | **Discord** ✓ tested |
| `0x0B` | WeChat | `0x15` | GroupMe |
| `0x0C` | QQ | `0x16` | Douyin |
|  |  | `0x17` | TamTam |

### Example — "HELLO" with Instagram icon

```
./dv raw 50 01 05 48 45 4c 4c 4f
# frame:  01 09 00 50 01 05 48 45 4c 4c 4f 52 01 02
#                   └ op  └ IG └─len─┴──"HELLO"──┘
```

Empirical test: four distinct icon+text pairs (WhatsApp+"WORKING", Facebook+"FOCUS", Discord+"READY", Telegram+"DONE") all rendered correctly with the correct icon and text.

### Empirical behavior (measured)

- **Persistence:** each notification flashes for **~1–3 seconds** then the device reverts to its previous view (clock / gallery / etc.).
- **Queueing:** rapid back-to-back sends (~300 ms apart) **queue**; the device plays all of them in order (FIFO). There is no dedup or replace-in-place.
- **No reboots, no crashes** from any of the combinations tested so far.

### Implications for state-indicator design

- Ideal for **state-change notifications** — flash "READY" / "DONE" / "NEW MSG" / etc. when something transitions.
- **Not suitable** for persistent status display (the 1-3 s timeout is baked into the firmware; no opcode found to extend it).
- For persistent status, combine with `0x8B` live animation (§8i) — use animation for the steady-state view, use `0x50` flashes for event moments.

### Open follow-ups

- [ ] Can any field or separate opcode extend the notification duration?
- [ ] Can `cmd_code` be made to use a custom icon (via the separate `0x3C SPP_SET_ANCS_NOTICE_PIC` pixel-upload flow) — tested: **crashes the device** (see §8k below).
- [ ] What is the max text length that renders cleanly (firmware caps at 128 bytes per the app code, but the display width is probably the practical limit).

---

## 8k. `SPP_SET_ANCS_NOTICE_PIC` (`0x3C`) custom pixel icon — crashes

Attempted the full `CmdManager.W()`+`CmdManager.X()`+`a0()` flow to upload a custom icon via opcode `0x3C`. Every variation rebooted the device:
- JSON (not a candidate — 0x3C expects binary).
- JPEG blob with pixel dims (128, 160) as rowCnt/colCnt.
- JPEG blob with cells (8, 10) as rowCnt/colCnt (the confirmed-good format for `0x8B`).
- With and without the `SPP_SECOND_SUPPORT_MORE_ANCS` handshake (`raw bd 27`) first.
- With and without the post-upload trigger `raw 50 <event_id>`.

The handshake reliably ACKs (`01 07 00 04 bd 55 27 01 45 01 02`), and the pixel chunk writes individually succeed on the wire, but the device resets mid-stream or at the trigger step.

**Hypothesis:** the firmware's ANCS pic pipeline is meant to be triggered by an actual Android Notification Accessibility Service event (from a real phone), and pushing custom pixels into that path without a corresponding event triggers a fault in the rendering step. The preset-icon path (§8j) bypasses this by referencing firmware-bundled icon resources.

**Conclusion:** for a custom icon we'd need to (a) understand what "real ANCS event" state the firmware expects before pixel upload, or (b) find a different pipeline. §8j (preset icon + text) is the working path; §8i (full-screen animation) is the other working path.

### Why this is the recommended state-indicator primitive

Compared to the `0x8B` live-animation pipeline in §8i:
- No pixel encoding needed (no JPEG/eZip round-trip).
- Single frame = a few bytes over BT (vs. KBs).
- Device-side processing is trivial (text + lookup icon) — no decoder crashes.
- Each call is independent, no "setup handshake" or "teardown" needed.

Trade-off: limited to the 24 preset icons. If you need a fully custom icon alongside the text, §8i remains the path — but §8j is the fast-and-safe default for the common case.

---

## 8i. Live status animation via `SPP_APP_NEW_GIF_CMD2020` (`0x8B`) — WORKS

**Status: confirmed visually.** A 3-frame red/green/blue 160x128 animation was sent over opcode `0x8B`; the device displayed the RGB animation. This is the best path for the actual product requirement: "depending on status state, show our custom animation."

### APK path

The Android call chain for live play is:

```
DesignSendModel.playToDevice()
  -> playByBlue()
  -> playAniMulti(pixelBean)
  -> sendToOneDevice(pixelBean)
  -> CmdManager.n(pixelBean)
```

`CmdManager.n(pixelBean)` uses `SPP_APP_NEW_GIF_CMD2020`, whose enum value is `139` (`0x8B`). For MiniToo, `DeviceFunction` sets `BlueHighPixelArch`, `DevicePixel128`, `f11387E=true`, and `f11414c0=false`; `e3.h` therefore encodes 160x128 animations via `W2.c.r(pixelBean)`.

### Wire protocol

Same chunk shape as the gallery upload, but **different opcode**:

```
Announce:
  raw 8b 00 <total_len_u32_LE>

Each chunk:
  raw 8b 01 <total_len_u32_LE> <chunk_index_u16_LE> <payload_chunk>
```

Chunk payload is up to 256 bytes. The outer Divoom frame wrapper is still the normal `01 [len_le16] [opcode] [args...] [checksum_le16] 02`.

### Payload format (`W2.c.r`)

For MiniToo live animation, the 6-byte blob header must use the app's cell dimensions, not raw pixel dimensions:

```
Header:
  23 <frame_count> <speed_u16_BE> 08 0a
  # 0x23 = W2.c.r magic
  # 0x08,0x0a = rowCnt=8, columnCnt=10 -> 160x128 pixels

Per frame:
  01 <jpeg_len_u32_BE> <jpeg_bytes>
  # 01 = JPEG fallback flag
```

Important false start: the earlier probe used `80 a0` (`128,160`) in the header. The firmware ACKed the transfer and switched the screen to a black rectangle, but did not render pixels. The successful RGB test used `08 0a`.

### Confirmed experiment

Successful test:

- Blob header: `23 03 01 f4 08 0a` (`3` frames, `500ms`, `8x10` cells).
- Payload: three JPEG frames at 160x128.
- Total payload: `5477` bytes.
- Transport: `0x8B` announce + `22` data chunks.
- TX result: `23` writes, `0` write errors.
- Device ACK for announce:

```
01 07 00 04 8b 55 00 01 ec 00 02
```

The earlier black-screen attempt is also useful: black means the device accepted `0x8B` and entered the live animation surface, but the blob header / frame encoding was wrong.

### Faster upload experiment

The original working sender used one FIFO command per chunk:

```
./dv raw 8b 00 ...
./dv raw 8b 01 ...
./dv raw 8b 01 ...
...
```

That path is slow because the daemon intentionally waits between FIFO commands
(`DIVOOM_GAP_MS`, default `600ms`) and `sendFrames()` also had per-frame pacing.
For a 20-40 chunk animation this makes the upload take tens of seconds even
though the Bluetooth link can accept data much faster.

The faster experiment added a `rawfile <path> [delay_ms]` command to
`divoom-send.swift` / `dv`. The file contains one raw opcode line per command,
but the daemon parses the whole file from a single FIFO request and sends all
frames over the already-open RFCOMM channel:

```
./dv rawfile /tmp/minitoo-rgb-8b-256-chunks.raw 40
```

Important correction: chunks must be split at **256 bytes**, matching Android's
`hVar.q(256)` path. A first batch test accidentally used 250-byte chunks; because
the protocol carries only `chunk_index`, the firmware likely reconstructs using
`index * 256`, so 250-byte chunks corrupt every chunk after the first.

Confirmed faster sequence:

1. Send announce:

   ```
   raw 8b 00 <total_len_u32_LE>
   ```

2. Wait for the device to enter receive mode. The observed ACK is:

   ```
   01 07 00 04 8b 55 00 01 ec 00 02
   ```

3. Stream all chunks from one `rawfile` batch at 40ms pacing:

   ```
   raw 8b 01 <total_len_u32_LE> <chunk_idx_u16_LE> <256-byte-or-smaller payload>
   ```

Empirical result for the 3-frame RGB test after device control was restored:

- Payload: `6242` bytes.
- Chunks: `25` chunks at 256-byte max.
- Chunk batch log: `sendFrames: count=25 delay=40ms`.
- Chunk batch elapsed: `1048ms`.
- Device ACKed the announce and chunk indices (`8b 55 01 <idx_u16_LE>`).
- Device visibly rendered the RGB animation.
- Perceived screen update was still about `3-5s`, so the transport is much
  faster but not yet illusion-grade.

Creature-sized follow-up using the same live `0x8B` framing:

- Source asset: `~/creature.gif`, encoded as the same MiniToo `0x23` payload used
  in the working `0xBE` custom test.
- Payload: `28,923` bytes.
- Chunks: `113` chunks at 256-byte max.
- Announce: `8b 00 fb 70 00 00`.
- Rawfile: `/tmp/minitoo-creature-q80-8b-256-chunks.raw`.
- Chunk batch elapsed at 5ms pacing: about `745ms`.
- Device ACKed the announce with `8b 55 00 01` and requested chunk indices with
  `8b 55 01 <idx_u16_LE>`.
- Visual result is still pending user confirmation. This is the critical test for
  avoiding the custom-channel loading UI because it does not use `Channel/SetCustom`
  or the `0xBE` server-file responder.

Likely next optimization: replace the fixed wait with an ACK-aware sender that
sends the announce, waits specifically for `8b 55 00 01`, then immediately
streams chunks. Also reduce payload size: fewer frames, lower JPEG quality, and
smaller visual changes directly reduce chunk count.

### Implications for status animation

Use this for status states:

1. Pre-render each status as a short 160x128 GIF or frame batch.
2. Encode frames as JPEG.
3. Build the `W2.c.r` blob with header `23 frame_count speed_BE 08 0a`.
4. Split into 256-byte chunks.
5. Send over opcode `0x8B` using the announce/chunk protocol above.
6. Prefer the `rawfile` batch path over FIFO-per-chunk sends.
7. On status change, send the new animation.

Open items:

- Measure loop / timeout behavior: does live `0x8B` loop indefinitely, play once, or return to another view?
- Test whether `raw bd 1b ff ff` (`SPP_SECOND_SET_GIF_PLAY_TIME_CFG = 0xffff`) extends live-play duration.
- Implement a proper ACK-aware `0x8B` uploader. The experimental two-step
  `raw` + `rawfile` flow works, but still has a fixed wait and perceived
  `3-5s` update latency.
- Wrap the successful temporary sender into a reusable tool with an explicit `cells` header mode. Existing ad-hoc scripts that use `128,160` in the `0x23` header can black-screen on the live path.

## 8l. `Channel/SetCustom` server-file path (`BD 30` + `0xBE`) — WORKS FOR CUSTOM PAGES

**Status: protocol verified and visually explained.** The device can be tricked
into asking the Mac for a fake app/server `FileId`, and it accepts the same
`W2.c.r` RGB payload over opcode `0xBE`. The RGB animation renders as a custom
clock/face page. What looked like loading/waiting UI borders were later
identified in the iPhone app as the custom face's configurable frame decoration.

### APK path

The relevant Android app path is:

```
Device receives JSON:
  Channel/SetCustom with FileId

Firmware asks app for file:
  0xBD 0x30 <fileId_len> <fileId>
  # SPP_SECOND_GET_ZSTD_DECODE_FILE_INFO

App answers with server-file upload:
  0xBE ...
  # SPP_SECOND_SEND_SERVER_FILE_INFO
```

`f.java` builds the `0xBE` transfer using `e3.h` with 256-byte chunks. For
MiniToo 160x128 content, `e3.h.g(pixelBean)` still routes to `W2.c.r(pixelBean)`,
the same payload family that made the live `0x8B` RGB animation visible.

### Wire protocol

The tested start frame is:

```
be 00 <encoded_len_u32_LE> <fileId_len_u8> <fileId_ascii>
```

The tested chunk frames are:

```
be 01 <encoded_len_u32_LE> <chunk_index_u16_LE> <256-byte-or-smaller payload>
```

Important correction from the APK and hardware test: the device response
`be 55 00 ...` means **"start sending chunks now"**, not "upload complete".
The correct sequence is:

```
Mac -> JSON Channel/SetCustom with fake FileId
Device -> bd 55 30 <len> <FileId>
Mac -> be 00 <total_len> <len> <FileId>
Device -> be 55 00 ...
Mac -> be 01 <total_len> <chunk_idx> <payload>  # all chunks
Device -> bd 55 13 01 05 00                    # SET_GIF_TYPE / 2020 mode response
```

Earlier attempts sent `be 00` and all chunks immediately after `BD 30`; that
caused a repeated `BD 30` request loop. After changing the sender to wait for
`be 55 00` before streaming chunks, the repeated `BD 30` loop stopped.

### Confirmed experiment

Tested fake FileId:

```
mac-status-rgb-1
```

Observed identity probe first:

```
bd 2b 00
=> DeviceId = <YOUR_DEVICE_ID>
=> DevicePassword = <YOUR_DEVICE_PASSWORD>
```

Then sent:

```json
{"Command":"Channel/SetCustom","CustomPageIndex":0,"CustomId":0,"FileId":"mac-status-rgb-1","ClockId":0,"ParentClockId":0,"ParentItemId":"","LcdIndependence":0,"LcdIndex":0,"Language":"en","DeviceId":<YOUR_DEVICE_ID>}
```

The device requested the file:

```
01 17 00 04 bd 55 30 10 6d 61 63 2d 73 74 61 74 75 73 2d 72 67 62 2d 31 35 07 02
```

Decoded:

```
bd 55 30 10 "mac-status-rgb-1"
```

The corrected Mac responder then logged:

```
autocustom: sending start for mac-status-rgb-1 reason=BD30
delegate: rx[11]: 01 07 00 04 be 55 00 01 1f 01 02
autocustom: sending 25 chunks for mac-status-rgb-1 reason=BE00
delegate: rx[13]: 01 09 00 04 bd 55 13 01 05 00 38 01 02
```

Visual result:

- RGB animation displays.
- Loading/waiting borders remain visible on the right and left.
- This strongly suggests the pixel file is accepted/rendered, but the
  surrounding custom-channel state machine is still not fully satisfied.

### Mac-side responder

The experimental responder is implemented in:

```
core/divoom-send.swift
core/dv
```

Start command used in the successful run:

```bash
./dv start-custom <YOUR_MAC> mac-status-rgb-1 /tmp/minitoo-rgb-be-mac-status.raw <YOUR_DEVICE_ID> 40
./dv json '{"Command":"Channel/SetCustom","CustomPageIndex":0,"CustomId":0,"FileId":"mac-status-rgb-1","ClockId":0,"ParentClockId":0,"ParentItemId":"","LcdIndependence":0,"LcdIndex":0,"Language":"en","DeviceId":<YOUR_DEVICE_ID>}'
```

The rawfile shape is one `be 00` start line followed by `be 01` chunk lines.
The responder splits those internally into:

- start frame sent only after `BD 30`
- chunk frames sent only after `BE 55 00`
- single chunk resend support for `BE 55 01 <chunk_idx>`

Important black-screen finding from the Custom 2 working-face upload: the
`0xBE` custom-face path has the same `W2.c.r` header requirement as live
`0x8B`. The MiniToo header must be:

```text
23 <frame_count> <speed_u16_BE> 08 0a
```

An ad-hoc encoder wrote `80 a0` (`128,160` raw pixels) into the blob header.
The device accepted the transfer and still rendered the custom face frame, but
the animation center was black. Temporarily changing Custom 2 from
`StyleId=828` to rimless `StyleId=798` kept the center black, proving the
noise-level frame was not the cause. Regenerate affected rawfiles with `08 0a`
cell dimensions before debugging styles or Bluetooth transport.

### Interpretation

This path proves that a Mac process can emulate the Android app's "server file"
role well enough to make the firmware render our uploaded RGB asset. It does
not yet prove that we can cleanly switch into a finished custom slot/page.

Earlier suspected missing pieces, now lower priority after the frame-decoration
correction:

- Some extra JSON response the Android app normally returns after the file
  transfer, possibly around `Channel/GetOneCustom`.
- A final command/state update that tells the firmware the custom page is now
  resolved.
- A mismatch in the `Channel/SetCustom` fields (`CustomId`, `ClockId`,
  page/index fields).

For status animation, the earlier "loading chrome" interpretation was wrong.
User inspection in the iPhone app showed those right/left borders are the
custom face's configured frame decoration. One custom face used the old border
that looked like a leftover loading UI, another had no border, and the creature
face was changed to a noise-level-bars frame. This means `Channel/SetCustom`
successfully populates persistent custom clock/face pages, not a temporary
loader surface.

### Quick-switch/cache experiment

Because the frame borders are custom-face decoration rather than a loader, we tested
whether multiple fake `FileId`s could be switched quickly after first use.

Mac-side setup:

```
mac-status-rgb-1    -> 25 BE chunks, known RGB animation
mac-status-block-1  -> 5 BE chunks, solid color-block animation
```

The Mac responder was extended to serve both IDs in one Bluetooth session.
Sequence tested:

```
Channel/SetCustom FileId=mac-status-block-1
Channel/SetCustom FileId=mac-status-rgb-1
Channel/SetCustom FileId=mac-status-block-1
```

Observed:

- First block request:
  - device sent `bd 55 30 ... "mac-status-block-1"`
  - Mac sent `be 00`, then 5 chunks
  - chunk batch elapsed about `226ms`
- RGB request:
  - device sent `bd 55 30 ... "mac-status-rgb-1"` again
  - Mac sent `be 00`, then 25 chunks
  - chunk batch elapsed about `1096ms`
- Second block request:
  - device again sent `bd 55 30 ... "mac-status-block-1"`
  - Mac again sent `be 00`, then 5 chunks
  - chunk batch elapsed about `226ms`

Conclusion: this fake `FileId` / `0xBE` path does **not** behave like an
instant cached switch-by-ID path. The firmware requests the file bytes every
time we set the custom entry, even for a `FileId` it just received in the same
session. It can be made fairly quick for tiny/simple animations, but larger
animations still incur the upload cost.

Follow-up visual observation: after setting RGB as `CustomId=0` and the
purple/green block animation as `CustomId=1` on the same `CustomPageIndex=0`,
the device plays both animations in succession. RGB appears to loop a few times,
then the purple/green animation plays once. This strongly suggests
`Channel/SetCustom` is populating a custom-page gallery/playlist, not replacing
the entire page display. For status use, we should avoid accumulating multiple
`CustomId`s in the same page unless rotation is desired.

Next protocol variant to test: keep `CustomPageIndex=0` and always write to the
same `CustomId` (probably `0`) with a new `FileId`, or call
`Channel/CleanCustom` / `Channel/DeleteCustom` before adding the next item. If
same-`CustomId` replacement works, the visible behavior may feel instant enough
even though bytes are still uploaded.

Cleanup follow-up: sending `Channel/CleanCustom` for `CustomPageIndex=0`
immediately cleared the rotating RGB / purple-green custom page and made the
device show an empty custom-page placeholder that looks like an old TV
no-signal / static screen. No response frame was observed for the JSON command,
but the visual effect was immediate. The exact command sent was:

```json
{"Command":"Channel/CleanCustom","CustomPageIndex":0,"ClockId":0,"ParentClockId":0,"ParentItemId":"","DeviceId":<YOUR_DEVICE_ID>}
```

The intended follow-up `Channel/SetCustom` was not sent in that run because the
visual state changed before it was needed. This is strong evidence that
`CleanCustom` is the correct reset primitive for collapsing a custom-page
playlist before installing a single status animation.

Clean-then-set follow-up: with the device already on the empty custom-page
placeholder, we started a responder for only `mac-status-block-1`, sent
`Channel/CleanCustom` again, waited about one second, then sent
`Channel/SetCustom` with `CustomPageIndex=0`, `CustomId=0`, and
`FileId=mac-status-block-1`. The device requested the file with `bd 55 30`,
accepted `be 00`, received 5 `be 01` chunks, and ended with
`bd 55 13 01 05 00`. Chunk-send time was about `220ms`. Visual result was
confirmed: the device showed only the purple/green/blue block animation, and
the earlier RGB animation did not return. So `CleanCustom` + one `SetCustom`
collapses the page to a single status animation.

Detailed-asset follow-up: converted `~/creature.gif` into the same `0x23`
MiniToo payload with aspect-preserving contain-to-160x128, black side padding,
8 frames, 100ms frame speed, and JPEG quality 80. The resulting payload was
`28,923` bytes, split into `113` chunks. We sent it through the same
`CleanCustom` + `SetCustom` path as `FileId=mac-status-creature-q80`, but with
20ms chunk pacing instead of 40ms. The device requested the file, accepted
`be 00`, received all 113 chunks in about `2.77s`, and returned
`bd 55 13 01 05 00`. Visual result is pending user confirmation. This shows
that detailed status-pose assets are feasible on wire, but upload latency scales
with encoded JPEG payload size.

Faster pacing follow-up with the exact same creature payload:

| Chunk pacing | Chunks | Chunk-send time | Result |
| --- | ---: | ---: | --- |
| 20ms | 113 | ~2.77s | Completed, `bd 55 13 01 05 00` |
| 10ms | 113 | ~1.43s | Completed, `bd 55 13 01 05 00` |
| 5ms | 113 | ~0.76s | Completed, `bd 55 13 01 05 00` |

This means sub-second upload is possible for a detailed 8-frame creature asset
on the current `0xBE` path, at least at the wire/protocol level. The remaining
status-change latency comes from the JSON clean/set overhead and any deliberate
gap after `CleanCustom`; the previous experiments used a conservative 1-second
gap that should be reduced or removed in the next end-to-end test.

Frame-count / payload-size stress follow-up:

All rows below use the same temporary test method: duplicate/scramble frames
from the bundled working GIF, add a small changing pixel marker so frames do not
coalesce, encode with `W2.c.r`-compatible header `23 <frames> 00 c8 08 0a`,
JPEG quality 80, stretch-to-160x128, 200ms frame speed, and upload to Custom 3
through the `0xBE` custom-face path.

| Frames | GIF bytes | Encoded payload bytes | BE chunks | Result |
| ---: | ---: | ---: | ---: | --- |
| 20 | 55,173 | 76,398 | 299 | Uploaded and rendered; user confirmed working. |
| 50 | 138,730 | 190,936 | 746 | Upload command completed and switched to Custom 3. |
| 100 | 277,042 | 381,099 | 1,489 | Upload command completed and switched to Custom 3. |
| 150 | 415,902 | 572,005 | 2,235 | Upload command completed and switched to Custom 3. |
| 200 | 554,948 | 763,069 | 2,981 | Unsafe: user observed the MiniToo restart during upload; no final upload ACK was captured. |

Interpretation: `150` frames / `572,005` encoded payload bytes is inside the
observed working envelope. `200` frames / `763,069` encoded payload bytes is the
first observed unsafe point and can reboot the device during upload. This is not
yet a precise firmware limit: the true boundary is somewhere between those
payload sizes.

Keyboard switcher UX note: a simple terminal app lives at
`core/status-keys.py`. The original version used the
`daemon-custom-multi` fake-`FileId` responder and switched by `SetCustom`; that
was too slow/noisy for status changes. After the real custom-face `ClockId`
path was confirmed, the tool was changed to use `Channel/SetClockSelectId`
only:

- left arrow / `1` -> `ClockId=986` (`Custom 2`)
- right arrow / `2` -> `ClockId=984` (`Custom1`, creature)
- `3` -> `ClockId=988` (`Custom 3`)

This makes keypresses small-command switches rather than animation uploads.

Critical user observation from the iPhone app: MiniToo exposes three custom
clock/face pages, and the hardware joystick switches between them instantly.
After our experiments, custom face 1 contained the creature GIF, while custom
faces 2 and 3 contained the TV-static/no-signal placeholder. This strongly
supports a different production strategy:

1. Preload one status animation per custom face page (`CustomPageIndex` 0, 1, 2),
   with a single `CustomId` inside each page.
2. At runtime, switch the active page instead of uploading a new animation.
3. Retest the APK-backed page switch command `bd 17 <slot>` with populated pages:

   ```bash
   ./dv raw bd 17 00
   ./dv raw bd 17 01
   ./dv raw bd 17 02
   ```

The APK confirms this mapping: `LightCustomFragment` page selection calls
`CmdManager.p1(i)`, and `CmdManager.p1` sends `SPP_DIVOOM_EXTERN_CMD` with
`SPP_SECOND_USE_USER_DEFINE_INDEX`, i.e. `bd 17 <slot>`. Our earlier `bd 17 ff`
probe was not sufficient because it used the reset/default value and was run
outside this populated custom-page scenario.

Slot-switch retest from macOS with the iPhone-created custom faces still
populated:

```bash
./dv raw bd 17 00
./dv raw bd 17 01
./dv raw bd 17 02
```

Wire result, later reclassified as **invalid for proving device control**:

- all three frames wrote successfully
- each command returned a matching frame: `bd 17 00`, `bd 17 01`, `bd 17 02`
- no upload, clean, or delete command was sent
- visual result: no visible screen change in the tested state

Important correction: these matching RX frames were byte-for-byte echoes of the
TX payloads, not normal MiniToo ACKs. A real app-protocol response usually uses
the response envelope `01 <len> 00 04 <cmd> 55 ... <cs> 02`. Because a later
screen off/on control check also produced only exact echoes and no visible
screen change, all macOS probes after the iPhone custom-face discovery should be
treated as "Bluetooth not actually controlling the device" until reconnection is
visually verified.

Single-command retest:

```bash
./dv raw bd 17 01
```

Result: the frame wrote cleanly and RX showed `bd 17 01`, but the user reported
no visible change. Because the RX frame was an exact echo, this does **not**
prove that the device accepted the command. Retest only after a visible control
check, such as `bd 2f 00` making the display go dark and `bd 2f 01` restoring
it.

Valid-control rerun: after reconnecting on RFCOMM port 1, `bd 2f 00` visibly
turned the screen off and `bd 2f 01` restored it. In that confirmed-control
session we reran:

```bash
./dv raw bd 17 00
./dv raw bd 17 01
./dv raw bd 17 02
```

Wire result: all three frames wrote cleanly with `status=0x0`; unlike the
invalid port-10 run, there were no byte-for-byte echo RX frames. Visual result:
no visible screen change. Therefore `bd 17 <slot>` is not the visible MiniToo
clock-face carousel selector, even when Bluetooth control is confirmed and the
device is showing the creature custom clock face. It is likely limited to the
custom-light editor/page model used inside the Android app.

Additional confirmed-control selector probes while the device was visibly on the
creature custom clock face:

| Probe | Result |
| --- | --- |
| JSON `Channel/SetCustomPageIndex` with `CustomPageIndex=1` | write OK, no visible change |
| JSON `Channel/SetCustomPageIndex` with `CustomPageIndex=2` | write OK, no visible change |
| JSON `Channel/SetCustomId` with `CustomId=1` | write OK, no visible change |
| JSON `Channel/SetIndex` with `SelectIndex=1` | write OK, no visible change |
| JSON `Channel/SetClockSelectId` with `ClockId=0` | write OK, no visible change |
| raw `8a 01 05` / `8a 01 06` / `8a 01 07` | write OK, no visible change |
| local `face 1` helper (`45 05` then `bd 17 01`) | write OK, no visible change |
| game-key-style down press/release (`17 04`, `21 04`) | write OK, no visible change |

The `8a` probes are still useful as a mapping result: APK
`LightConfigFragment` maps Custom 1/2/3 startup channels to indices `5/6/7`
via `CmdManager.U2(i)` (`8a 01 <i>`), but on MiniToo these appear to configure
a startup/preference channel rather than immediately moving the visible
clock-face carousel.

The game-key-style probe is also a mapping result: APK game controls map "down"
to key code `4`, with `CmdManager.t1(4)` = opcode `0x17` press and
`CmdManager.u1(4)` = opcode `0x21` release. This does not emulate the MiniToo
hardware joystick's clock-face carousel action while the device is in clock mode.

### APK static trace: custom face pages vs visible clock selection

The Android APK distinguishes two concepts that we previously conflated:

1. `CustomPageIndex` is the **editing page** inside the custom clock feature.
2. The visible clock/face selection is driven by real server/device `ClockId`
   values.

Relevant APK paths:

- `MyClockMainFragment` selects a visible face by calling
  `WifiChannelModel.G().b0(clockListItem.getClockId())`, then records history
  through `WifiChannelModel.G().l(clockId)`.
- `WifiChannelModel.b0(int)` builds `WifiChannelSetClockSelectIdRequest` and
  sends `Channel/SetClockSelectId` with `ClockId=<real id>`.
- `BaseParams.postSync()` routes `Channel/SetClockSelectId` as a
  `DeviceAndServerCmd`: local device HTTP when available, MQTT in connected
  WiFi mode, or cloud/server otherwise. It is not just a fixed raw SPP opcode.
- `MyClockModel.a(int)` adds a clock to the user's "My Clock" list through
  `Channel/MyClockAdd`, then immediately calls `WifiChannelModel.G().b0(id)`.
- If the device asks the app for the user's clock list with
  `Channel/DeviceGetMyClock`, `bluetooth/f.java` calls `MyClockModel.m()`,
  which fetches `Channel/MyClockGetList` from the server and replies over SPP
  JSON with `{"Command":"Channel/DeviceGetMyClock","ClockList":[...]}`.
- `JumpControl` routes custom clock types `3..12` into
  `WifiChannelCustomFragment` and sets the edit page as
  `CustomPageIndex = ClockType - 3`.
- `WifiChannelModel.R()` fetches the store clock list and maps custom clock
  types `3`, `4`, and `5` into `f13155f[0..2]`; `WifiChannelModel.A(page)`
  returns the real `ClockId` for that custom page.
- `Channel/SetCustom` uses both concepts: it sends `CustomPageIndex=<page>` to
  choose which custom clock page to edit, and sends `ClockId=<real custom clock
  id>` when Android knows it.

Confirmed conclusion: the three user-visible custom faces are three custom
**clock IDs** with clock types `3`, `4`, and `5`, not three raw
`CustomPageIndex` slots that can be selected by `bd 17 <slot>`.
`CustomPageIndex` edits a custom face; `Channel/SetClockSelectId` with the real
`ClockId` selects the visible face.

Scope note: APK navigation code has a generic branch for `ClockType` `3..12`
and maps those to `CustomPageIndex = ClockType - 3`. That does **not** mean the
MiniToo exposes ten custom faces. The MiniToo-visible ID cache in
`WifiChannelModel` is `new int[3]`, `WifiChannelModel.R()` only fills entries
for `ClockType` `3`, `4`, and `5`, and this account's `Channel/MyClockGetList`
returned exactly those three custom entries. Treat three as the MiniToo limit
unless future cloud/device data proves otherwise.

### Local auth probe for real custom clock IDs

Added `core/fetch-clock-ids.py` to reproduce only the cloud-auth pieces
needed for the next test without pasting reusable credentials into chat.

It mirrors the Android path:

1. Prompt locally for Divoom account email/password.
2. POST `UserLogin` with the app's MD5 password transform.
3. Use the returned `UserId` / `Token` only in memory.
4. Fetch `Channel/MyClockGetList`.
5. Fetch `Channel/StoreClockGetClassify`, then the first
   `Channel/StoreClockGetList`.
6. Print `ClockId` / `ClockType` / display metadata and highlight clock types
   `3`, `4`, and `5` as custom-face candidates.

The script deliberately does not print the numeric auth token. Expected use:

```
python3 core/fetch-clock-ids.py
```

If it returns `CUSTOM_CLOCK_IDS=a,b,c`, the next live experiment is to send
`Channel/SetClockSelectId` with one of those real IDs instead of `ClockId=0`.

Result from the authenticated probe:

| Custom face | ClockId | ClockType | Name |
| --- | ---: | ---: | --- |
| Custom face 1 | `984` | `3` | `Custom1` |
| Custom face 2 | `986` | `4` | `Custom 2` |
| Custom face 3 | `988` | `5` | `Custom 3` |

These IDs also appear at the top of `Channel/MyClockGetList`, so they are both
store custom-clock IDs and installed "My Clock" entries for this account.

First real-ID live selector sent over SPP JSON:

```json
{"Command":"Channel/SetClockSelectId","ClockId":986,"DeviceId":<YOUR_DEVICE_ID>,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}
```

Visual result: **confirmed success**. The MiniToo switched to Custom 2
(`ClockId=986`). This validates the instant/small-command runtime path:
preload animations into the three custom faces using the official app or our
upload path, then switch status by sending `Channel/SetClockSelectId` with
`984`, `986`, or `988`.

## 8m. Stored user-defined animation (`0x8C` + `BD 17`) — APK path found, hardware not proven

**Status: APK-backed, first hardware upload attempt inconclusive / likely not
accepted.** This is still the most plausible path for truly instant status
switching, but the MiniToo has not yet confirmed that it accepted our custom
slot upload.

### APK path

The Android app's non-64 "custom light" path stores user-defined animations
with `SPP_APP_NEW_USER_DEFINE2020`:

```
8c 00 <encoded_len_u32_LE> <slot_u8>                 # start slot upload
8c 01 <encoded_len_u32_LE> <chunk_index_u16_LE> ...   # 256-byte chunks
8c 02                                                 # finalize
bd 17 <slot_u8>                                      # switch selected slot
```

Static references:

- `CmdManager.N2(int slot, List list)` builds `8c 00`.
- `LightMakeNewModel.y()` builds/sends `8c 01` chunks with `e3.h`, 256-byte
  chunking, and the same `W2.c.r` 160x128 payload family used by working `0x8B`.
- `CmdManager.K0()` builds `8c 02`.
- `CmdManager.p1(int slot)` sends `bd 17 <slot>`.
- `s.java` handles `bd 55 17 ...` by updating the active custom index in
  `LightMakeNewModel` / `LightMake64Model`.

Important correction: our known-good `0x8B` chunk rawfile already uses the same
envelope shape (`opcode 01 total_len index payload`). Replacing opcode `8b`
with `8c` did **not** create a malformed chunk envelope.

### Hardware attempt: slot 0 RGB payload

Generated rawfile:

```
8c 00 62 18 00 00 00
8c 01 62 18 00 00 00 00 <payload chunk 0>
...
8c 01 62 18 00 00 18 00 <payload chunk 24>
8c 02
bd 17 00
```

Sent via normal Mac daemon:

```bash
./dv start <YOUR_MAC>
./dv rawfile /tmp/minitoo-rgb-8c-slot0.raw 40
```

Observed:

- `sendFrames: count=28 delay=40ms`
- `sendFrames: done elapsed=1170ms`
- every write completed with `status=0x0`
- no `8c` response frames were received
- follow-up `raw 8e 00` produced no response
- follow-up `raw bd 17 00` produced no response
- follow-up `raw bd 18` **did** respond:

```
01 07 00 04 bd 55 18 01 36 01 02
```

That `bd 18` response proves the Bluetooth link was still healthy and the
device still reports the new/custom animation support flag. The failure is
specific to the `0x8C` upload/query/switch path, not a transport failure.

Also tried the APK's custom-channel index idea:

```
8a 01 05   # SPP_SET_POWER_CHANNEL, Custom 1 according to LightConfigFragment
bd 17 00
```

Both frames wrote cleanly, but neither produced a response frame. Visual result
confirmed unchanged: the device stayed on the RGB custom face with its
configured frame border. So this activation probe did not enter a different
custom-slot view in that context.

Later user inspection with the iPhone app changed the interpretation: those
borders were frame decorations, and the custom pages were populated. Therefore
the old `bd 17 00` no-response result was not enough by itself. A later
confirmed-control visual retest with populated custom faces still showed no
visible change for `bd 17 00/01/02`, so `bd 17 <slot>` is now likely the
custom-light editor/user-define selector rather than the MiniToo visible
clock-face carousel selector.

### Interpretation

Possible explanations:

- `0x8C` may only be valid while the device is in the app's custom-light page
  state, and our current channel/UI state is not enough.
- `0x8C` may need a preceding custom-page negotiation command that the APK
  normally sends indirectly through UI state.
- The device may accept `0x8C` silently but only display it when the custom
  channel is fully active; this is not confirmed.
- The `0x8C` user-define storage may be a different feature from the
  full-screen MiniToo channel renderer despite sharing the `W2.c.r` payload.

Current conclusion: do **not** depend on `0x8C + bd17` for product behavior
yet. Keep it as the main instant-switch research path, but the reliable path
remains live `0x8B` (§8i), and the server-file path remains partial (§8l).

## 8g. OLD (outdated) — "The native-library wall" notes

Retained for historical value; the conclusions below were superseded by §8f once empirical upload of a JPEG-flagged `0x23` blob succeeded.



| Path | App code | Native lib | macOS viable? |
| --- | --- | --- | --- |
| **Photo upload** (via `Photo/LocalAddToAlbum`) | `AbstractC0522n.a()` → `sifliEzipUtil.b()` | `lib/arm64-v8a/libezip.so` (394KB) | ❌ |
| **Pixel art 160x128** (via `BluePixelPictureModel`, `CmdManager.Z()`) | `W2.c.r()` — uses MiniLZO with JPEG fallback, *also native* | `lib/arm64-v8a/libtimebox.so` (3.5MB) | ❌ |
| **Pixel art default (128 grid)** | `W2.c.f()` → `nDKMainJ.pixelEncodeBlueHigh(...)` | same `libtimebox.so` | ❌ |
| **Pixel art 16/64** (older Ditoo family) | `nDKMainJ.pixelEncode(...)` / `PixelEncode128` | same | ❌ |

**The apparently-simple W2.c.m() encoder** (magic `0x1F`, pure JPEG) is NOT used by Minitoo — I (the reverse engineer in this session) misread the code paths and briefly thought it was. Tests confirmed: sending JPEG-only blobs with magic `0x1F` (or later `0x23`) reached the device as SPP_LOCAL_PICTURE frames and were ACK'd wire-level, but the firmware silently routed them to photo-gallery mode without ever displaying our content. That matches the decompile — the photo-arrival code path is what the firmware triggers when it receives SPP_LOCAL_PICTURE with unrecognized header bytes, not a display.

### The magic bytes by encoder

| Magic | Encoder | Purpose | Compression |
| --- | --- | --- | --- |
| `0x1F` | `W2.c.m` | Ditoo/Pixoo-class, single JPEG frames | none (raw JPEG) |
| `0x23` | `W2.c.r` | 160×128 layout (8×10 cells) | MiniLZO with JPEG fallback |
| `0x25` | `W2.c.f` ZSTD path | BlueHighPixelArch (Minitoo default) | ZSTD |
| `0x22` | `W2.c.f` JPEG fallback | same, when ZSTD exceeds budget | JPEG via `pixelEncodeBlueHigh` native |
| `0x27` | `W2.c.n` | Multi-layer ZSTD variant | ZSTD, layered |

### Ways to break the wall

Ranked by effort / success likelihood:

1. **Use OpenSiFli SDK.** [https://github.com/OpenSiFli/SiFli-SDK](https://github.com/OpenSiFli/SiFli-SDK) is the open-source SDK from SiFli. Very likely contains the eZip source (Minitoo uses a SiFli SoC). If so, we can compile for macOS and call it from Swift/Python. **Best shot — a few hours' setup.**
2. **Frida on a real Android device.** Install the Divoom app on an Android phone, use Frida to call `PixelEncode128()` / `pixelEncodeBlueHigh()` / `sifliEzipUtil.b()` with our input bitmap, extract the encoded byte blob, POST to our Mac daemon to relay via BT. Bypasses all reverse engineering. **One-day setup if you have or can borrow an Android phone.**
3. **QEMU user-mode emulation.** Extract `libtimebox.so` + `libezip.so`, load them under QEMU aarch64 with a stub Android libc. Call the encoders. **Hard — Android native libs depend on a lot of system services.**
4. **Reimplement from Ghidra disassembly.** Open the .so files in Ghidra, trace `pixelEncodeBlueHigh` and friends, port to C. **Days-to-weeks, depends on code complexity.**
5. **Cut losses on custom pixels** — ship with the 6+ built-in visual modes we already have (astronaut, gallery, games, scoreboard, noise meter) + brightness. Good enough for many state-indicator use cases.

### Empirical summary of what Minitoo accepts on `SPP_LOCAL_PICTURE`

- Our 12-byte photo-pipeline header (with random photoFlag, WebP body) → firmware ACKs the header, streams complete, then **reboots** when a display trigger comes (Photo/Enter or Photo/PlayAlbum). Suggests the eZip decoder is crashing on non-eZip data.
- Our 5-byte pixel-picture header (with W2.c.m magic `0x1F` or W2.c.r magic `0x23`, JPEG bodies) → firmware ACKs, streams complete, **device enters photo-gallery view** but our image doesn't appear in the rotation. Suggests the firmware's pixel decoder silently rejects our format and falls through to gallery display.
- Neither encoding is right without the native libs.

## 8e. Known-good "cancel" for the LOADING / file-request state

When the device enters a "loading / awaiting file data" state (from `Draw/LocalEq` or similar), it will continue broadcasting `01 11 00 04 BD 55 28 <len> <FileId bytes>` (`SPP_SECOND_GET_DECODE_FILE_INFO` asking for our file) for tens of seconds.

Sending `raw 8f 00 00 00 00 00` (SPP_LOCAL_PICTURE with 0-size header) clears the LOADING screen visually — **but the device keeps emitting the file-request broadcasts for a while**, which can interfere with subsequent probes. The clean reset is still to hardware-button back to clock face.

---

## 8b. The preset-face-switching wall (unchanged)

**Short version:** switching to a preset clock face (the stock 70+ faces shipped with the device) *still* requires a `FileId` minted by Divoom's cloud — those faces are addressable by `ClockId` in the mobile app, but the mapping from `ClockId` → pixel data lives cloud-side. Local BT-only control cannot pick a preset by name/ID without account credentials.

However, §8 shows we can **push our own custom GIFs directly** as the "face" for a given state — which covers the real product need (state indicator) even if we never figure out how to select *Divoom's* presets.

What we pieced together from the decompile:
1. User taps a face in the app → `MyClockMainFragment.onItemClick` fires.
2. App hits the Divoom cloud via HTTP: `POST Channel/SetCustom` with a `CustomId` and pixel data reference.
3. Cloud responds with a `FileId`.
4. App sends `q.s().B(wifiChannelSetCustomRequest)` over BT — a JSON with `FileId`, `CustomId`, `CustomPageIndex`.
5. Minitoo firmware pulls pixel data from storage by `FileId` and displays it.

Step 3 is the blocker. The cloud is authenticated (`BaseRequestJson` carries `Token`, `UserId`, `DeviceId`, `DevicePassword`), and we have none of that state.

## 8p. Custom-face frame/border metadata

**Status: APK path mapped; noise-bars `StyleId` confirmed as `828`.** The APK
path is known, the current live style IDs for this account are known, and a live
Bluetooth sweep on the physical device showed that `StyleId=828` is the desired
noise-level bars frame. `StyleId=824` is `Widgets 7`, but physical-device
inspection showed it is not the desired frame.
The visible borders around custom faces are not part of the uploaded GIF/JPEG
payload. They are persistent per-clock "style" metadata. Re-uploading a GIF with
`CleanCustom` + `Channel/SetCustom` preserves the existing border for that
custom clock slot.

Observed target state:

- Custom 1 / `ClockId=984`: idle/chilling animation, should have no border.
- Custom 2 / `ClockId=986`: working animation, should have the noise-meter bars
  border.
- Custom 3 / `ClockId=988`: message animation, should have no border.

Verified current style state from authenticated `Channel/GetClockStyle`:

| Custom face | ClockId | Current StyleId | Style name | Meaning |
| --- | ---: | ---: | --- | --- |
| Custom 1 | `984` | `798` | `Rimless` | no border |
| Custom 2 | `986` | `828` | `Widgets 11` | desired noise-level bars |
| Custom 3 | `988` | `798` | `Rimless` | no border |

Desired border arrangement:

```text
Custom 1: StyleId 798 (Rimless)
Custom 2: StyleId 828 (Widgets 11 / noise-level measuring bars)
Custom 3: StyleId 798 (Rimless)
```

Current evidence:

- `Channel/SetCustom` with a new `FileId` updates the animation but does not
  reset or change the border.
- Rewriting all three slots with real `ClockId` values (`984`, `986`, `988`)
  repaired joystick/carousel selection, but left border metadata unchanged.
- A live Bluetooth sweep of `Channel/SetClockStyle` for `ClockId=986` confirmed
  that `StyleId=828` (`Widgets 11`,
  `group1/M00/26/DD/eEwpPWVF2COEBTgLAAAAAGYBN8I3886526`) is the desired
  noise-level bars frame.
- User-provided before/after authenticated snapshots showed **no change** in
  `Channel/MyClockGetList`, `PhotoFrame/GetList`, `Channel/GetAll`, or
  `Channel/GetConfig`. That means the first probe was looking at the wrong
  endpoints.
- Static trace of Divoom Android `3.8.14` (`com.divoom.Divoom`, version code
  `614`, APK SHA256
  `005377c6dbd8786507ad638bb1c51ce97b778d04fed04f1bfbe9835e60074010`)
  maps the custom-face "Frame" row to `WifiChannelClockStyleFragment`, not to
  `PhotoFrame/GetList`.
- `WifiChannelCustomFragment` opens the style picker with the current
  `ClockId`. `WifiChannelClockStyleFragment` loads:

```json
{"Command":"Channel/GetClockStyle","ClockId":984,"StartNum":1,"EndNum":30,"Language":"en","CountryISOCode":"US"}
```

Response schema from the APK:

```json
{
  "CurStyleId": 0,
  "CurStylePixelImageId": "...",
  "StyleList": [
    {"StyleId": 0, "StyleName": "...", "StylePixelImageId": "..."}
  ]
}
```

- Pressing the app's check/save button calls
  `WifiChannelModel.c0(styleId, clockId)`, which sends:

```json
{"Command":"Channel/SetClockStyle","ClockId":984,"StyleId":123}
```

with the normal `BaseChannelRequest` fields (`DeviceId`, `Language`,
`ParentClockId=0`, `ParentItemId=""`, `PageIndex=0`, `LcdIndependence=0`,
`LcdIndex=0`).

- `BaseParams._postSync()` confirms this is a **server + Bluetooth relay**
  command: after the server POST succeeds, if a Bluetooth device is bound and
  connected, the app calls `q.s().B(request)`, which writes the same JSON over
  `SPP_JSON` (`0x01`) to the MiniToo. So a complete Mac helper should do both:
  persist via cloud `Channel/SetClockStyle`, then relay the same JSON over BT
  for immediate device update.

What `PhotoFrame/GetList` and `Channel/SetFrame` mean now:

- `PhotoFrame/GetList` is a separate client-side frame compositor used by the
  cloud/local pixel-art "add frame" feature. `CloudPhotoFrameFragment` loads a
  frame bitmap, overlays the pixel foreground at `PixelStartX/Y`, then exports a
  new baked image/GIF. It is not the custom-face border setting.
- `ChannelSetFrameRequest` exists in the APK with `ChannelIndex` and
  `FrameUserDataID`, but `Channel/SetFrame` is not in `HttpCommand` and earlier
  probes returned `ReturnCode=10`. Treat it as legacy/dead for MiniToo custom
  faces.

Tooling update:

```bash
cd <repo>/core

# List current style/frame IDs and available style catalog for all 3 custom faces.
./probe-frame-metadata.py styles --email <divoom-login>

# Or include style data in before/after snapshots.
./probe-frame-metadata.py dump --label before-style --email <divoom-login>
./probe-frame-metadata.py dump --label after-style --email <divoom-login>
./probe-frame-metadata.py diff /tmp/divoom-frame-before-style.json /tmp/divoom-frame-after-style.json
```

Known assignments:

```bash
# Rimless/no border is known.
./probe-frame-metadata.py set-style --email <divoom-login> --clock-id 984 --style-id 798
./probe-frame-metadata.py set-style --email <divoom-login> --clock-id 988 --style-id 798

# Working/noise-bars style.
./probe-frame-metadata.py set-style --email <divoom-login> --clock-id 986 --style-id 828

# Do not use 824 for noise bars. The device showed 824 is a different border.
```

If the cloud POST succeeds but the device does not update immediately, relay the
printed JSON through the existing daemon:

```bash
./dv start <YOUR_MAC>
./dv json '{"Command":"Channel/SetClockStyle","ClockId":986,"StyleId":828,"DeviceId":<YOUR_DEVICE_ID>,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}'
./dv stop
```

The live BT relay changes the device immediately, but the durable setup should
still persist `StyleId=828` through `probe-frame-metadata.py set-style` so the
cloud/account metadata matches the device state.

The older before/after workflow still works, but now captures style data too:

```bash
cd <repo>/core

# 1. Before changing a border in the official app.
./probe-frame-metadata.py dump --label before --email <divoom-login>

# 2. In the iPhone app, change exactly one thing:
#    e.g. Custom 1 border from noise bars -> none. Do not change the GIF.

# 3. After the app saves/syncs.
./probe-frame-metadata.py dump --label after --email <divoom-login>

# 4. Diff the redacted snapshots.
./probe-frame-metadata.py diff /tmp/divoom-frame-before.json /tmp/divoom-frame-after.json
```

The script calls:

- `Channel/MyClockGetList`
- `Channel/GetClockStyle` for `ClockId=984`, `986`, and `988`
- `PhotoFrame/GetList` with both `StartNum=1` and `StartNum=0`
- `Channel/GetAll`
- `Channel/GetConfig`
- `Channel/GetCurrent`

It prompts for credentials locally and writes redacted JSON snapshots; it does
not print or save the password/token.

## 9. Architecture constraints that fall out of this

- **Face selection: cloud-dependent.** No face picker without auth.
- **Screen state (on/off): local.** `Channel/OnOffScreen` is fine to automate.
- **Brightness: local.** Fine to automate, 0–100.
- **Tool views: local but noisy.** Stopwatch/countdown crash through an audible alarm; scoreboard/noise quieter.
- **Notifications (SMS/MMS channel 17, ANCS):** advertised in SDP, not probed yet — could potentially display text.

## 10. Gap list — what still needs mapping

Marked by importance for the library.

### Closed / resolved

- [x] ~~Return-to-clock-face opcode~~ — **answered: there isn't one.** The official app never sends one either. Hardware button is the only exit (§5.6).
- [x] ~~Scoreboard byte layout~~ — confirmed `[on, red_lo, red_hi, blue_lo, blue_hi]` (§5.4).
- [x] ~~Is `0x01 0x55` marker needed for request JSON?~~ — **no.** Requests are raw JSON bytes after the opcode; the `0x01 0x55` prefix is response-frame-only.
- [x] ~~Confirmed tool-type mapping~~ — from `ToolModel.TYPE` enum: 0=Stopwatch, 1=Scoreboard, 2=NoiseStatus, 3=Countdown.
- [x] ~~Screen on/off opcode semantics~~ — `0xBD 0x2F 0` = off, `=1` = on/restore, `=2` = no-op, `=3` = off (§5.7).

### Critical (before library v0.1)

- [ ] **Noise meter argument layout** — `[on, ?, ?, ?, ?]`. Silent to probe; just need a confirmed byte-to-visual mapping.
- [ ] **Stopwatch argument layout** — `[on, min_lo, min_hi, sec_lo, sec_hi]` inferred from `s3()`. ⚠️ Each probe risks triggering the alarm — daytime only.
- [ ] **Brightness stability** — we've only tested a few levels end-to-end. Verify full 0–100 sweep with device feedback (JSON ACK).

### Nice to have (library v0.2)

- [ ] **`Danmaku/SendBlueText`** — tested in both clock mode and scoreboard mode — silent in both. Likely needs the device in a specific "danmaku view" which may not be a thing on Minitoo.
- [ ] **`Alarm/Listen`** — probably makes the speaker beep. AVOID at night. Test during the day.
- [ ] **`Photo/PlayAlbum`** — slideshow capability; untested.
- [ ] **`Memorial/Set`** with full fields — probably displays a named date. Untested.
- [ ] **ANCS / phone-notification display** — `SPP_SET_ANCS_NOTICE_PIC` (0x3C) and `SPP_SET_ANDROID_ANCS` (0x50). Device showed Instagram-looking icons during the blind probe, so the pipeline works, but it requires pixel-art data alongside the notification metadata. Non-trivial.
- [ ] **SMS/MMS RFCOMM channel 17** — advertised in SDP, never probed. Might be a separate text-forwarding path.
- [ ] **`WhiteNoise/Set`** — structure known (`OnOff`, `Time`, `EndStatus`, `Volume[8]`). Audio-producing, so daytime only.

### Cloud-dependent (probably never)

- [ ] Face switching by `ClockId` — requires a cloud-minted `FileId`.
- [ ] Custom pixel-art upload (`DrawLocalEqRequest` path).
- [ ] `Channel/SetCustom` / fake `FileId` path — partially mapped (§8l). The
      device requests `BD 30`, accepts `0xBE` data, and renders RGB, but loading
      borders remain visible.

### Experimental local paths

- [ ] Stored user-defined animation slots (`0x8C` + `BD 17`) — APK path mapped
      and first MiniToo attempt sent successfully over Bluetooth, but no
      `0x8C` / `0x8E` / `BD17` responses were observed (§8m).

### Protocol questions still open

- [ ] Decode the 8-byte keepalive body `4E 6F 62 02 D0 49 41 00` — device ID? Uptime? Sequence?
- [ ] Why do only `Device/GetStorageStatus` and `WhiteNoise/Get` among many `Get` probes respond? Is there a registry the firmware exposes?
- [ ] Is there a binary equivalent for `Channel/OnOffScreen`, or is `0xBD 0x2F` already that and the JSON command just wraps it?
- [ ] Port 1 vs port 10 — any protocol difference? Both accept commands.
- [ ] What triggers the periodic `Tomato/FocusAction` broadcast even without an active pomodoro? It's emitted every few seconds with static values.

## 11. Tooling delivered so far

In `/core/`:

- `divoom-send.swift` — 330-line Swift CLI. Does SDP enumeration, RFCOMM open on port 1/10, SPP_JSON, raw binary opcodes, the four helper commands (`brightness`, `face`, `clock`, `raw`), plus a `daemon` mode.
- `divoom-send.app` + `build.sh` — wraps the binary in a bundle with an Info.plist so macOS TCC allows it through. Ad-hoc codesigned.
- `dv` — bash wrapper. `./dv start <MAC>` launches the daemon via `open -g`, `./dv <cmd>` writes to the FIFO, `./dv stop` exits cleanly. It also has `start-custom` and `start-custom-multi` modes for serving one or more fake `FileId` assets over the `0xBE` path.
- `fetch-clock-ids.py` — local cloud-auth probe. Prompts for Divoom credentials,
  keeps token/password out of output, and prints the real custom-face
  `ClockId` candidates needed for the next `Channel/SetClockSelectId` test.
- `probe.sh` + `analyze.py` — bulk opcode probe (was useful but noisy — opcodes 0x00–0xFF with a single-byte arg, then grep for novel `Command` strings in responses).

## 12. Open questions / things I'm not sure about

- Whether BT **channel 10** is the "preferred" channel (SDP lists it first in one ordering) or if they're functionally identical. Both accept commands; we've pinned port 1.
- Whether the firmware speaks a different protocol version when connected via channel 10 vs channel 1.
- Whether the Minitoo has any BLE-exposed characteristics we haven't even tried. The SDP scan only covers Classic services.
- Whether cloud auth can be bootstrapped locally (e.g. sniff the mobile app's login once, extract token) — this would unlock face switching but is not a clean path.

---

**TL;DR:** We have a solid, reproducible BT protocol (`SPP_JSON` opcode `0x01` + raw binary opcodes like `0x32`, `0x72`). We can change brightness, turn the screen off/on, and force-display tool views. We cannot natively switch to a preset face (cloud-gated). There's a short list of unexplored commands that could meaningfully expand the library; face switching via cloud is the biggest open frontier.
