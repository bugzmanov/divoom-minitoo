# Instant animation switching on Divoom MiniToo

Status: APK-backed path, partially tested on hardware. The packet format is
mapped, and user observation from the iPhone app confirms that MiniToo has three
hardware-selectable custom face pages. The remaining key test is whether we can
select those populated pages from macOS with `bd 17 <slot>`.

Goal: avoid the 3-5 second upload delay when status changes. The live
animation path (`0x8B`) works, but every status change requires pushing the
whole animation payload. The likely path for instant switching is to pre-store
several animations in the device's custom/user-defined animation slots, then
switch the active slot by ID with a tiny command.

---

## Summary

The Android APK has a separate "user define" animation protocol:

| Operation | Opcode / args | Notes |
| --- | --- | --- |
| Upload/store custom animation | `0x8C 0x00 <total_len_u32_le> <slot>` | `SPP_APP_NEW_USER_DEFINE2020` start command |
| Send stored-animation chunk | `0x8C 0x01 <total_len_u32_le> <chunk_idx_u16_le> <payload>` | 256-byte chunks, same splitter style as live `0x8B` |
| Finalize stored-animation upload | `0x8C 0x02` | Built by `CmdManager.K0()` |
| Switch active custom slot | `0xBD 0x17 <slot>` | `SPP_SECOND_USE_USER_DEFINE_INDEX` |
| Clear custom slot | `0xBD 0x16 <slot>` | Destructive |
| Query custom slot/list info | `0x8E <slot>` | `SPP_APP_GET_USER_DEFINE_INFO` |
| Query custom-slot feature flag | `0xBD 0x18` | `SPP_SECOND_GET_NEW_POWER_ON_CHANNEL` |
| Set custom-loop time | `0xBD 0x14 <time_u16_le>` | Used by custom-light settings |

If this path can be made to work on the MiniToo, runtime status changes become:

```bash
./core/dv raw bd 17 00   # show status animation 0
./core/dv raw bd 17 01   # show status animation 1
./core/dv raw bd 17 02   # show status animation 2
```

That is one small SPP frame per switch, so the visible switch should be close
to instant. Upload time still exists, but it moves to setup/startup instead of
the status-change moment. This is still a research path, not a production path.

---

## APK evidence

Main files in the jadx output:

- `/tmp/divoom-apk/sources/com/divoom/Divoom/bluetooth/CmdManager.java`
- `/tmp/divoom-apk/sources/com/divoom/Divoom/bluetooth/SppProc$CMD_TYPE.java`
- `/tmp/divoom-apk/sources/com/divoom/Divoom/bluetooth/SppProc$EXT_CMD_TYPE.java`
- `/tmp/divoom-apk/sources/com/divoom/Divoom/bluetooth/s.java`
- `/tmp/divoom-apk/sources/com/divoom/Divoom/view/fragment/light/model/LightMakeNewModel.java`
- `/tmp/divoom-apk/sources/e3/h.java`
- `/tmp/divoom-apk/sources/W2/c.java`
- `/tmp/divoom-apk/sources/com/divoom/Divoom/utils/DeviceFunction/DeviceFunction.java`

### MiniToo is on the new 2020 animation path

`DeviceFunction.java` maps `MiniToo` to:

- `NewAniSendMode2020.setNewMode()`
- `f11387E = true`
- `DevicePixelModelEnum.DevicePixel128`
- `UiArchEnum.BlueHighPixelArch`

This is the same family we used for the working live RGB animation.

### Live animation path, already proven

The working live animation path is:

- `SPP_APP_NEW_GIF_CMD2020` = decimal `139` = `0x8B`
- start: `0x8B 0x00 <total_len_u32_le>`
- chunks: `0x8B 0x01 <total_len_u32_le> <chunk_idx_u16_le> <payload>`

The MiniToo requires the `W2.c.r(...)` 160x128 payload shape:

```text
23 <frame_count> <speed_u16_be> 08 0a
01 <jpeg_len_u32_be> <jpeg_bytes>
01 <jpeg_len_u32_be> <jpeg_bytes>
...
```

The critical size bytes are `08 0a`, meaning row count 8 and column count 10.
Using a raw `80 a0` pixel payload was accepted but produced a black screen.

### Stored/custom animation path

`SppProc$CMD_TYPE.java` defines:

- `SPP_APP_NEW_GIF_CMD2020(139)` -> `0x8B`
- `SPP_APP_NEW_USER_DEFINE2020(140)` -> `0x8C`
- `SPP_APP_GET_USER_DEFINE_INFO(142)` -> `0x8E`
- `SPP_DIVOOM_EXTERN_CMD(189)` -> `0xBD`

`SppProc$EXT_CMD_TYPE.java` defines:

- `SPP_SECOND_SET_USER_DEFINE_TIME(20)` -> `0x14`
- `SPP_SECOND_CLEAR_USER_DEFINE_INDEX(22)` -> `0x16`
- `SPP_SECOND_USE_USER_DEFINE_INDEX(23)` -> `0x17`
- `SPP_SECOND_GET_NEW_POWER_ON_CHANNEL(24)` -> `0x18`

`CmdManager.N2(int slot, List list)` builds the `0x8C` stored-animation start
command:

```text
8c 00 <total_len_u32_le> <slot_u8>
```

`LightMakeNewModel.y()` prepares the chunk list for the same `0x8C` opcode:

- sets new-mode chunking
- uses 256-byte chunks
- concatenates encoded `PixelBean` payloads
- sends each chunk with opcode `0x8C`

`CmdManager.K0()` builds the stored-animation finish command:

```text
8c 02
```

`CmdManager.p1(int slot)` switches the active user-defined slot:

```text
bd 17 <slot_u8>
```

The RX handler in `s.java` recognizes `SPP_SECOND_USE_USER_DEFINE_INDEX` and
updates the active custom index in both light models. That is strong evidence
that `0xBD 0x17 <slot>` is intended as a cheap switch-by-ID command, not an
upload.

---

## Why this should carry our status animations

The encoder helper `e3.h.g(pixelBean)` routes MiniToo-sized 160x128
`PixelBean`s to `W2.c.r(pixelBean)`, the same payload family that made the RGB
live animation visible.

The important condition is:

```java
pixelBean.is160X128()  // rowCnt == 8 && columnCnt == 10
```

So the source status animations can still be GIFs or image batches on our
side, but before sending they should be converted into the same 160x128
`W2.c.r`-style encoded payload, not sent as literal GIF files.

---

## Slot model

Important correction: the APK has two different "custom" models. For non-64
custom-light editing, the UI exposes three user-defined pages:

```text
slot 0 -> custom 1
slot 1 -> custom 2
slot 2 -> custom 3
```

That path calls `CmdManager.p1(0)`, `p1(1)`, or `p1(2)`, which sends
`bd 17 <slot>`. Valid-control MiniToo tests showed no visible clock-face change
for `bd 17 00/01/02`, so this is probably not the hardware joystick's visible
clock-face carousel selector.

The hardware reality observed through the iPhone app is still important:
custom face 1 contained the creature GIF, custom faces 2 and 3 contained the
TV-static placeholder, and the physical joystick switched between these pages
instantly. The "loading borders" seen earlier were custom face frame
decorations, not a loader. One custom face can have no border, another can have
the old TV-like border, and the creature face can use the noise-level-bars
frame.

The better APK-backed model is that visible custom faces are real clock faces
with `ClockType` values `3`, `4`, and `5`, each with a real server/device
`ClockId`. Android sets `CustomPageIndex = ClockType - 3` only when opening the
custom face editor. Visible face selection goes through
`Channel/SetClockSelectId` with `ClockId=<real id>`, not `CustomPageIndex`
alone. Our earlier `Channel/SetClockSelectId` test used `ClockId=0`, so it did
not exercise the real app path.

The APK also has generic navigation support for `ClockType` `3..12`, but the
MiniToo-specific visible custom-clock cache is only three entries and is filled
only from `ClockType` `3`, `4`, and `5`. For MiniToo package work, assume three
custom status slots.

There is also a 64/custom-item model with more indices, but MiniToo is mapped
to `BlueHighPixelArch` and does not appear to set the `f11411b` 64-custom flag
in the MiniToo branch. For first experiments, treat `0..2` as the safe known
slot range.

The APK also sends `bd 17 ff` in one helper (`CmdManager.u()`). This likely
means "no active user-defined slot", "default", or "finish list sync", but it
is not mapped well enough yet. Do not rely on it until tested.

---

## Proposed protocol

### 1. Query support

Read-only check:

```bash
./core/dv raw bd 18
```

The Android handler sets `DeviceFunction.j().f11419f = true` when the response
payload contains `1`.

### 2. Query existing stored info

Read-only check:

```bash
./core/dv raw 8e 00
./core/dv raw 8e 01
./core/dv raw 8e 02
```

This should tell us whether the device knows about custom slots and whether
any are populated.

### 3. Test instant slot switching without uploading

Non-destructive, but visually changes the displayed mode if slots exist:

```bash
./core/dv raw bd 17 00
./core/dv raw bd 17 01
./core/dv raw bd 17 02
```

Expected if supported:

- device ACKs `0xBD / 0x17`
- screen changes immediately to that custom slot/page
- no multi-second transfer occurs

If the slot is empty, the screen may stay unchanged or show a blank/default
custom page. That would not disprove the switch command.

This test should now be repeated with all three pages populated by the iPhone
app or by our `Channel/SetCustom` path. Earlier no-op results for `bd 17 ff`
do not disprove this path because `ff` is the reset/default value and the test
was not run against known populated custom pages.

Retest with the iPhone-created pages still populated:

```bash
./dv raw bd 17 00
./dv raw bd 17 01
./dv raw bd 17 02
```

Wire result, later reclassified as **invalid for proving device control**: all
three frames wrote successfully, and RX showed matching `bd 17 00`, `bd 17 01`,
and `bd 17 02` frames. No upload/clean/delete command was sent. Visual result:
no visible screen change in the tested state.

A single-command retest with only `bd 17 01` also wrote cleanly and returned
`bd 17 01`, but did not visibly switch the face. Therefore this command is not
sufficient by itself for visible MiniToo custom clock/face switching.

Important correction: those RX frames were exact echoes of the TX payloads, not
normal MiniToo ACKs. A later screen off/on control check (`bd 2f 00`, then
`bd 2f 01`) also produced only exact echoes and no visible screen change. Treat
the post-iPhone-discovery macOS probes as invalid until Bluetooth control is
visually re-established.

Valid-control rerun: after reconnecting on RFCOMM port 1, `bd 2f 00` visibly
turned the screen off and `bd 2f 01` restored it. We then reran:

```bash
./dv raw bd 17 00
./dv raw bd 17 01
./dv raw bd 17 02
```

Wire result: all three frames wrote cleanly with `status=0x0`, and no exact echo
RX frames appeared. Visual result: no visible screen change. Therefore
`bd 17 <slot>` is not the visible MiniToo clock-face carousel selector, even
when Bluetooth control is confirmed and the device is already showing the
creature custom clock face.

Additional confirmed-control selector negatives while the device was on the
creature custom clock face:

| Probe | Result |
| --- | --- |
| JSON `Channel/SetCustomPageIndex` page `1` / `2` | no visible change |
| JSON `Channel/SetCustomId` `1` | no visible change |
| JSON `Channel/SetIndex` `SelectIndex=1` | no visible change |
| JSON `Channel/SetClockSelectId` `ClockId=0` | no visible change |
| raw `8a 01 05` / `06` / `07` | no visible change |
| local `face 1` helper (`45 05`, `bd 17 01`) | no visible change |
| game-key-style down press/release (`17 04`, `21 04`) | no visible change |

APK mapping note: `LightConfigFragment` maps Custom 1/2/3 startup channels to
`8a 01 05/06/07`, but these did not immediately switch the visible MiniToo
clock-face carousel.

APK game-control note: "down" maps to key code `4`, with opcode `0x17` for press
and `0x21` for release. That press/release pair did not emulate the physical
joystick's clock-face carousel movement while already in clock mode.

### 4. Upload a test animation into one slot

Do this only after choosing a slot we are willing to overwrite.

Candidate sequence:

```text
8c 00 <total_len_u32_le> <slot>
8c 01 <total_len_u32_le> <chunk_idx_u16_le> <payload_chunk_0>
8c 01 <total_len_u32_le> <chunk_idx_u16_le> <payload_chunk_1>
...
8c 02
bd 17 <slot>
```

Chunk size should be exactly 256 bytes except the final chunk. The earlier
`0x8B` experiments showed that non-256 chunking can be ACKed but reconstructed
incorrectly.

Open question: whether the device wants all `0x8C` chunks pushed sequentially,
or only when it requests a chunk index. The APK RX handler handles `0x8C`
responses where `bArr[6] == 1` by sending the requested chunk index. The
current Mac sender can start with sequential sending because it worked for
`0x8B`, but the robust implementation should listen for requested chunk IDs.

---

## Hardware attempt: 2026-04-24

We tried storing the known-good RGB `W2.c.r` payload into slot `0`.

Raw sequence:

```text
8c 00 62 18 00 00 00
8c 01 62 18 00 00 00 00 <payload chunk 0>
...
8c 01 62 18 00 00 18 00 <payload chunk 24>
8c 02
bd 17 00
```

Send command:

```bash
./dv rawfile /tmp/minitoo-rgb-8c-slot0.raw 40
```

Mac-side result:

- 28 frames sent.
- elapsed time: `1170ms`.
- all writes returned `status=0x0`.
- no device response for `0x8C`.
- `raw 8e 00` produced no response.
- repeated `raw bd 17 00` produced no response.
- `raw bd 18` still responded with:

```text
01 07 00 04 bd 55 18 01 36 01 02
```

Interpretation:

- The Bluetooth link was healthy.
- The device still reports the new/custom animation support flag.
- The `0x8C` slot upload was not confirmed and should not be treated as
  working yet.
- The chunk shape was not the issue: the working `0x8B` chunks already use
  `opcode 01 total_len index payload`, and the `0x8C` test reused that shape.

Follow-up activation probe:

```text
8a 01 05
bd 17 00
```

`8a 01 05` is `SPP_SET_POWER_CHANNEL` with the Custom 1 channel index inferred
from `LightConfigFragment`. Both frames wrote successfully, but neither
produced a response frame. Visual result: no change; the device stayed on the
RGB custom face with its configured frame border. So this did not activate a
different custom slot/page in that context.

Likely missing piece: the device may need to be in a specific custom-light /
custom-channel state before `0x8C` storage and `BD 17` slot selection become
active, or this user-define path may not target the same full-screen renderer
as MiniToo's working `0x8B` path.

Later user inspection with the iPhone app changed the interpretation: the
visible borders were frame decorations, and the custom pages were in fact
populated. Therefore the old `bd 17 00` no-response result should be retested
against known populated pages and watched visually; lack of an ACK alone may not
mean the page switch failed.

---

## Negative result: fake `FileId` switching is not instant

We also tested whether the `Channel/SetCustom` + `0xBE` server-file path can be
used as a quick switcher. The visible borders in that path are now understood
as custom face frame decoration, not loading UI.

Setup:

```text
mac-status-rgb-1    -> known RGB animation, 25 BE chunks
mac-status-block-1  -> simple solid color-block animation, 5 BE chunks
```

Sequence:

```text
Channel/SetCustom FileId=mac-status-block-1
Channel/SetCustom FileId=mac-status-rgb-1
Channel/SetCustom FileId=mac-status-block-1
```

Result: every switch caused the device to request the file again with
`bd 55 30 <FileId>`. Even the second request for `mac-status-block-1` in the
same Bluetooth session triggered a fresh `be 00` + chunk upload.

Measured chunk-send times:

- `mac-status-block-1`: about `226ms` for 5 chunks.
- `mac-status-rgb-1`: about `1096ms` for 25 chunks.

Conclusion: fake `FileId` switching is not a true cached switch-by-ID path.
It can be made faster by making animations tiny, but the upload still happens
on every status change.

Follow-up visual observation: using different `CustomId`s on the same
`CustomPageIndex` creates rotation behavior. In the test, RGB was written as
`CustomId=0` and the purple/green block animation as `CustomId=1`; the device
then played RGB a few times and the purple/green animation once, repeating.
So `Channel/SetCustom` is adding/replacing entries in a custom-page gallery,
not switching the page to one exclusive animation.

Implication for a status display: either always overwrite the same `CustomId`,
or clear/delete the previous custom entry before adding the new one. Different
statuses should not be placed as separate `CustomId`s in one page unless we
want the device to rotate through them.

Follow-up cleanup result: `Channel/CleanCustom` with `CustomPageIndex=0`
immediately cleared the rotating custom page. The device switched to an empty
custom-page placeholder that visually looks like an old TV no-signal / static
screen. The command sent was:

```json
{"Command":"Channel/CleanCustom","CustomPageIndex":0,"ClockId":0,"ParentClockId":0,"ParentItemId":"","DeviceId":<YOUR_DEVICE_ID>}
```

This makes `CleanCustom` the best-known reset step before setting one active
status animation through the `SetCustom` / `0xBE` path.

Clean-then-set follow-up: after clearing the page, we sent a single
`Channel/SetCustom` for `CustomPageIndex=0`, `CustomId=0`, and
`FileId=mac-status-block-1`. The device requested the file, accepted the start
frame, received 5 chunks in about `220ms`, and returned the normal
`bd 55 13 01 05 00` completion frame. Visual confirmation: the device showed
only the purple/green/blue block animation, with no return to RGB. This
confirms `CleanCustom` + one `SetCustom` can force a single active status
animation through the `0xBE` path.

Detailed-asset test: `~/creature.gif` was converted into an aspect-preserving
160x128 `0x23` payload with black side padding, 8 frames, 100ms frame speed,
and JPEG quality 80. Encoded payload size was `28,923` bytes (`113` chunks).
Using the same `CleanCustom` + `SetCustom` path with 20ms chunk pacing, the
device accepted the transfer and returned `bd 55 13 01 05 00`; chunk-send time
was about `2.77s`. Visual result is still pending user confirmation, but this
is the first realistic detailed-status-pose latency datapoint.

Faster pacing with the same payload:

| Chunk pacing | Chunks | Chunk-send time | Result |
| --- | ---: | ---: | --- |
| 20ms | 113 | ~2.77s | Completed |
| 10ms | 113 | ~1.43s | Completed |
| 5ms | 113 | ~0.76s | Completed |

So the upload portion can be pushed below 1 second for this detailed 8-frame
asset. End-to-end status switching still needs a follow-up test with the
post-`CleanCustom` wait reduced or removed; the earlier runs used a conservative
1-second gap before `SetCustom`.

Keyboard switcher UX note: `core/status-keys.py` now uses the confirmed
`Channel/SetClockSelectId` path. It no longer uploads animation data on
keypress.

- left arrow / `1` -> `ClockId=986` (`Custom 2`)
- right arrow / `2` -> `ClockId=984` (`Custom1`, creature)
- `3` -> `ClockId=988` (`Custom 3`)

Live `0x8B` creature follow-up: the same `~/creature.gif` payload was converted
from the working `0xBE` custom rawfile into live-animation chunks:

- Payload: `28,923` bytes.
- Chunks: `113` chunks at 256-byte max.
- Announce: `8b 00 fb 70 00 00`.
- Rawfile: `/tmp/minitoo-creature-q80-8b-256-chunks.raw`.
- Transfer time at 5ms pacing: about `745ms`.
- Device ACKed the announce with `8b 55 00 01` and requested chunk indices with
  `8b 55 01 <idx_u16_LE>`.

Visual result is pending. If this renders without the custom loading frame, the
left/right app should be moved from `Channel/SetCustom` + `0xBE` to an ACK-aware
live `0x8B` uploader.

---

## Expected latency

Upload:

- still depends on animation size
- likely similar to the fast live upload path: seconds for a large animation
- should happen at setup/startup, not during status changes

Switch:

- one `0xBD` frame
- should be sub-second and likely visually instant
- this is the path that preserves the "status display" illusion

---

## Risks and caveats

1. Not yet hardware-confirmed.
   The APK evidence is strong, but the first MiniToo `0x8C` upload attempt did
   not produce a confirmation response or a proven visual switch.

2. Existing custom slots may be overwritten.
   `0x8C` upload is a write operation. Query and switch tests are safer first.

3. Slot persistence is unknown.
   The custom-slot naming strongly implies persistence, but we should verify
   whether uploaded slots survive reboot.

4. Unknown custom face IDs can make switch tests look like no-ops.
   `Channel/SetClockSelectId` must be tried with real custom-face `ClockId`
   values. `ClockId=0` was not a valid test of the Android selection path.

5. `0xBD 0x17` should be treated as the wrong path for visible custom face
   switching unless new evidence appears. It belongs to the custom-light
   user-defined slot path, and valid-control tests did not move the MiniToo
   visible clock face.

---

## Recommended next experiments

1. Discover the real `ClockId` values for the three custom faces currently on
   the device. Use `python3 core/fetch-clock-ids.py` so credentials stay
   local and only clock IDs are printed.
   Done: Custom face 1 = `984`, Custom face 2 = `986`, Custom face 3 = `988`.
2. Test `Channel/SetClockSelectId` with a real custom-face `ClockId`, not `0`.
   Done: `ClockId=986` switched the MiniToo to Custom 2.
3. Use three preloaded custom faces as the production status slots.
4. Keep `0x8C` as a side research path only after the visible `ClockId` switch
   path is resolved.
5. Build a tiny status-switching CLI/app around `984`, `986`, and `988`.

The confirmed runtime architecture is:

```text
startup/setup:
  install/preload "idle" animation as Custom face 1
  install/preload "busy" animation as Custom face 2
  install/preload "error" animation as Custom face 3

runtime:
  status=idle  -> Channel/SetClockSelectId ClockId=984
  status=busy  -> Channel/SetClockSelectId ClockId=986
  status=error -> Channel/SetClockSelectId ClockId=988
```
