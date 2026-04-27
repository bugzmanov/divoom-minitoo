#!/usr/bin/env python3
"""Send a custom image as an ANCS phone-notification icon on Minitoo.

Pipeline (from CmdManager.W() + CmdManager.X()):
  1. METADATA frame — opcode 0x3C with args [event_id_u8, id_b0, id_b1, id_b2]
     (event_id is a notification-category slot, id is a per-notification id)
  2. PIXEL CHUNKS — opcode 0x3C with args
     [event_id, total_len_u32_LE, chunk_idx_u16_LE, payload]
     (same chunk format as SPP_LOCAL_PICTURE but event_id as prefix instead of 0x01)

Pixel blob uses W2.c.r format (magic 0x23, 160x128 JPEG, BE length per frame).

Usage:  ./ancs-notify.py <image> [event_id]
"""
import io, os, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
W, H = 160, 128           # pixel dimensions for the JPEG we encode
CELL_ROWS, CELL_COLS = 8, 10   # header uses CELLS (8x10 = 128x160 px), confirmed by §8i
CHUNK = 256

def dv_raw(byte_seq):
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def encode_blob(path, speed=2000, q=100):
    img = Image.open(path)
    frames = []
    try:
        while True:
            f = img.convert("RGB").resize((W, H))
            buf = io.BytesIO()
            f.save(buf, format="JPEG", quality=q)
            frames.append(buf.getvalue())
            img.seek(img.tell()+1)
    except EOFError:
        pass
    # W2.c.r header must use CELLS not pixels: 8 rows × 10 cols = 128×160 px
    hdr = bytes([0x23, len(frames), (speed>>8)&0xff, speed&0xff, CELL_ROWS, CELL_COLS])
    payload = hdr
    for j in frames:
        payload += bytes([1]) + struct.pack(">I", len(j)) + j
    return payload

def send(path, event_id=1):
    blob = encode_blob(path)
    print(f"blob {len(blob)}B, event_id={event_id}")

    # STEP 1: SUPPORT_MORE_ANCS handshake — tells firmware we support multi-ANCS.
    # ext cmd 0x27 under SPP_DIVOOM_EXTERN_CMD (0xBD).
    print("→ step 1: support-more-ANCS handshake (raw bd 27)")
    dv_raw(bytes([0xBD, 0x27]))
    time.sleep(0.3)

    # STEP 2: W metadata (set color for this slot). color=0x000000 (black).
    print(f"→ step 2: W metadata set-color (raw 3c {event_id:02x} 00 00 00)")
    dv_raw(bytes([0x3C, event_id & 0xFF, 0x00, 0x00, 0x00]))
    time.sleep(0.3)

    # STEP 3: X pixel chunks via opcode 0x3C with prefix=[event_id].
    prefix = event_id + 1 if event_id >= 8 else event_id
    n = (len(blob) + CHUNK - 1) // CHUNK
    print(f"→ step 3: {n} pixel chunks via opcode 0x3c, prefix 0x{prefix:02x}…")
    for i in range(n):
        payload = blob[i*CHUNK:(i+1)*CHUNK]
        chunk = bytes([0x3C, prefix]) + struct.pack("<I", len(blob)) + struct.pack("<H", i) + payload
        dv_raw(chunk)
        time.sleep(0.05)

    # STEP 4: a0(event_id) — trigger display of that slot via SPP_SET_ANDROID_ANCS (0x50).
    time.sleep(0.4)
    play_id = event_id + 1 if event_id >= 8 else event_id
    print(f"→ step 4: play notification slot {event_id} (raw 50 {play_id:02x})")
    dv_raw(bytes([0x50, play_id & 0xFF]))
    print(f"done. notification at slot {event_id} should display.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(64)
    path = sys.argv[1]
    ev = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
    send(path, ev)
