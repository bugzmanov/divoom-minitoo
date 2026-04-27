#!/usr/bin/env python3
"""Send pixel data via a configurable SPP opcode. Goal: find a non-gallery
persistence slot — SPP_SET_BOOT_GIF (0x52), SPP_SET_USER_GIF (0xB1),
SPP_APP_NEW_USER_DEFINE2020 (0x8C), etc.

Usage:
  ./boot-gif.py <image> <opcode_hex>  [--prefix N] [--flag N]

Each chunk for these opcodes uses format `[prefix_byte, payload]` instead of
SPP_LOCAL_PICTURE's `[0x01, total_len_u32_LE, chunk_idx_u16_LE, payload]`.
We test the simpler single-prefix format first (matches e3.h with p(true) or
the hVar.l([flag]) calls).
"""
import io, os, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
CHUNK_SIZE = 200
JPEG_QUALITY = 100
W, H = 160, 128
SPEED = 2000

def encode_blob(path):
    img = Image.open(path)
    frames = []
    try:
        while True:
            f = img.convert("RGB").resize((W, H))
            buf = io.BytesIO()
            f.save(buf, format="JPEG", quality=JPEG_QUALITY)
            frames.append(buf.getvalue())
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    header = bytes([0x23, len(frames), (SPEED>>8)&0xff, SPEED&0xff, H, W])
    payload = header
    for jpeg in frames:
        payload += bytes([0x01]) + struct.pack(">I", len(jpeg)) + jpeg
    return payload, len(frames)

def dv_raw(byte_seq):
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def main():
    if len(sys.argv) < 3:
        print("Usage: boot-gif.py <image> <opcode_hex> [--prefix N] [--flag N]")
        sys.exit(64)
    img = sys.argv[1]
    opcode = int(sys.argv[2], 16)
    prefix_byte = 0x00  # default flag byte in chunk prefix
    for i, a in enumerate(sys.argv):
        if a == "--prefix" and i+1 < len(sys.argv):
            prefix_byte = int(sys.argv[i+1])

    blob, n_frames = encode_blob(img)
    print(f"opcode 0x{opcode:02x}  |  {n_frames} frame(s)  |  blob {len(blob)}B  |  chunk-prefix 0x{prefix_byte:02x}")

    # Chunk format: [prefix_byte, payload]  (no total-len/index in this variant)
    n = (len(blob) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n} chunks of <={CHUNK_SIZE}B each via opcode 0x{opcode:02x}…")
    for i in range(n):
        payload = blob[i*CHUNK_SIZE:(i+1)*CHUNK_SIZE]
        chunk = bytes([prefix_byte]) + payload
        dv_raw(bytes([opcode]) + chunk)
        time.sleep(0.05)
    print(f"done. watch the screen.")

if __name__ == "__main__":
    main()
