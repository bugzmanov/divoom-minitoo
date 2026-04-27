#!/usr/bin/env python3
"""Encode a static image into Divoom's pixel-blob format and push it to the
Minitoo via the running dv daemon.

Protocol (from APK decompile, see FINDINGS.md §8):

  Divoom pixel blob:
    [0x1F, frameCount, speed_hi, speed_lo, rowCnt, colCnt]       # 6-byte header
    then for each frame:
      [jpeg_length_LE_u32] [jpeg_bytes]

  Over BT we:
    1. Send 'Draw/LocalEq' JSON (via dv json) with any FileId to arm LOADING.
    2. Send the initial SPP_LOCAL_PICTURE announce frame:
         opcode 0x8F, args = [0x00, total_size_u32_LE]
    3. Stream 256-byte chunks, each wrapped in SPP_LOCAL_PICTURE:
         opcode 0x8F, args = [0x01, total_len_u32_LE, chunk_index_u16_LE, ...payload...]
    4. Device reassembles and renders.

Usage:
    ./pixel-send.py <image_path>      # any image PIL can open (PNG, JPG, GIF frame)
"""
import io, os, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
TARGET_SIZE = 128           # Minitoo is DevicePixel128, assume 128x128
CHUNK_SIZE = 256
JPEG_QUALITY = 80
FRAME_SPEED_MS = 100

def encode_pixel_blob(image_path: str) -> bytes:
    img = Image.open(image_path).convert("RGB").resize((TARGET_SIZE, TARGET_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg = buf.getvalue()
    # 6-byte header: magic, frameCount, speed (big-endian u16), rows, cols
    header = bytes([
        0x1F,
        1,                          # frameCount
        (FRAME_SPEED_MS >> 8) & 0xFF,
        FRAME_SPEED_MS & 0xFF,
        TARGET_SIZE,
        TARGET_SIZE,
    ])
    frame = struct.pack("<I", len(jpeg)) + jpeg
    blob = header + frame
    print(f"blob: header={len(header)}B + frame={len(frame)}B (jpeg={len(jpeg)}B) => total {len(blob)}B")
    return blob

def dv_raw_hex(hex_bytes: str) -> None:
    subprocess.run([DV, "raw"] + hex_bytes.split(), check=True)

def dv_json(payload: str) -> None:
    subprocess.run([DV, "json", payload], check=True)

def send_blob(blob: bytes) -> None:
    # 1. Arm loading state
    print("arming Draw/LocalEq…")
    dv_json('{"Command":"Draw/LocalEq","FileId":"mac-test-1"}')
    time.sleep(0.4)

    # 2. Announce total size via SPP_LOCAL_PICTURE: [0x00, size_u32_LE]
    size_bytes = struct.pack("<I", len(blob))
    announce_args = bytes([0x00]) + size_bytes
    print(f"announce: size={len(blob)} → args {announce_args.hex(' ')}")
    dv_raw_hex("8f " + " ".join(f"{b:02x}" for b in announce_args))
    time.sleep(0.3)

    # 3. Stream chunks: [0x01, total_len_u32_LE, chunk_index_u16_LE, ...payload...]
    total = len(blob)
    n_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n_chunks} chunks of up to {CHUNK_SIZE}B…")
    for i in range(n_chunks):
        start = i * CHUNK_SIZE
        payload = blob[start:start + CHUNK_SIZE]
        chunk_args = (bytes([0x01])
                      + struct.pack("<I", total)
                      + struct.pack("<H", i)
                      + payload)
        dv_raw_hex("8f " + " ".join(f"{b:02x}" for b in chunk_args))
        time.sleep(0.12)
        if (i + 1) % 10 == 0 or i == n_chunks - 1:
            print(f"  sent chunk {i+1}/{n_chunks}")

    print("done. watch the Minitoo screen.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(64)
    blob = encode_pixel_blob(sys.argv[1])
    send_blob(blob)
