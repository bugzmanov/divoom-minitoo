#!/usr/bin/env python3
"""Upload a still image / GIF to the Minitoo via the pixel-picture pipeline
(NOT the photo pipeline, which needs SiFli eZip native code we don't have).

Pipeline (from BluePixelPictureModel + CmdManager.Z + e3.h.f + W2.c.m):

  1. Encode image(s) into the Divoom JPEG pixel-blob:
        [0x1F, frameCount, speed_hi, speed_lo, rowCnt, colCnt]   # 6-byte header
        then per frame:
          [jpeg_len_u32_LE] [jpeg_bytes]

  2. Send announce frame: SPP_LOCAL_PICTURE (0x8F) with args [0x00, total_len_u32_LE]

  3. Device responds with SPP_LOCAL_PICTURE b10=0 ("ready, send me chunks").

  4. Stream chunks, each wrapped in SPP_LOCAL_PICTURE:
         [0x01, total_len_u32_LE, chunk_index_u16_LE, payload]

  5. Device reassembles and displays on the main screen — no Enter/Play needed.

Usage:
  ./pixel-art.py <image_path> [speed_ms] [size]
"""
import io, os, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
DEFAULT_SPEED_MS = 2000   # matches BluePixelPictureFragment.lazyLoad() which sets 2000
DEFAULT_W = 160           # Minitoo may use 160x128 (is160X128() branch in app)
DEFAULT_H = 128
CHUNK_SIZE = 256
JPEG_QUALITY = 100        # W2.c.m uses quality=100 when i9==0 (no size budget)

def encode_divoom_blob(image_path: str, speed_ms: int, width: int, height: int) -> bytes:
    """Matches W2.c.r() — the 160x128 BlueHighPixelArch encoder for Minitoo.
    Header: [0x23, frameCount, speed_BE_u16, rowCnt, colCnt]
    Per frame: [compression_flag_u8] [length_u32_BE] [frame_data]
      flag = 0 for MiniLZO, 1 for JPEG. We always use JPEG (simpler)."""
    img = Image.open(image_path)
    frames = []
    try:
        while True:
            f = img.convert("RGB").resize((width, height))
            buf = io.BytesIO()
            f.save(buf, format="JPEG", quality=JPEG_QUALITY)
            frames.append(buf.getvalue())
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    assert frames, "no frames extracted"

    header = bytes([
        0x23,                                      # W2.c.r magic
        len(frames) & 0xFF,
        (speed_ms >> 8) & 0xFF, speed_ms & 0xFF,   # speed = big-endian u16
        height,                                    # rowCnt
        width,                                     # columnCnt
    ])
    payload = header
    for jpeg in frames:
        payload += bytes([0x01])                   # 1 = JPEG flag
        payload += struct.pack(">I", len(jpeg))    # length = BIG-endian u32
        payload += jpeg

    print(f"encoded {len(frames)} frame(s), total {len(payload)}B "
          f"(0x23 header + JPEG frames), size {width}x{height}, speed {speed_ms}")
    return payload

def dv_raw(byte_seq: bytes) -> None:
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def send_pixel_art(image_path: str, speed_ms: int, width: int, height: int) -> None:
    blob = encode_divoom_blob(image_path, speed_ms, width, height)

    # 1) Announce with 5-byte header: [0x00, total_len_u32_LE]
    announce = bytes([0x00]) + struct.pack("<I", len(blob))
    print(f"announce: {announce.hex(' ')}")
    dv_raw(bytes([0x8F]) + announce)
    time.sleep(0.4)   # give device time to respond "ready"

    # 2) Stream chunks: [0x01, total_len_u32_LE, chunk_idx_u16_LE, payload]
    n_chunks = (len(blob) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n_chunks} chunk(s) at {CHUNK_SIZE}B each…")
    for i in range(n_chunks):
        payload = blob[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (bytes([0x01])
                 + struct.pack("<I", len(blob))
                 + struct.pack("<H", i)
                 + payload)
        dv_raw(bytes([0x8F]) + chunk)
        time.sleep(0.02)    # aggressively fast — the 100ms in the app is for UI progress
        if (i + 1) % 5 == 0 or i == n_chunks - 1:
            print(f"  chunk {i+1}/{n_chunks}")
    print("done. watch the Minitoo — image should render on the main screen.")

if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 5):
        print(__doc__); sys.exit(64)
    path  = sys.argv[1]
    speed = int(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_SPEED_MS
    w     = int(sys.argv[3]) if len(sys.argv) >= 4 else DEFAULT_W
    h     = int(sys.argv[4]) if len(sys.argv) == 5 else DEFAULT_H
    send_pixel_art(path, speed, w, h)
