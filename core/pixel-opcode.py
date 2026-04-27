#!/usr/bin/env python3
"""Upload pixel data via a configurable opcode using the same chunked protocol
as pixel-art.py (which works for SPP_LOCAL_PICTURE=0x8F).

Format:
  Announce:  [opcode] [0x00] [total_len_u32_LE]                      # 5 bytes args
  Chunks:    [opcode] [0x01] [total_len_u32_LE] [chunk_idx_u16_LE] [payload]

Pixel blob:  [0x23, frameCount, speed_BE_u16, rowCnt=128, colCnt=160]
             per frame: [0x01 flag] [len_u32_BE] [jpeg]

Usage:  ./pixel-opcode.py <image> <opcode_hex>    e.g.  ./pixel-opcode.py a.png 8c
"""
import io, os, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
CHUNK_SIZE = 256

def dv_raw(byte_seq):
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def encode_blob(path, w=160, h=128, speed=2000, q=100):
    img = Image.open(path)
    frames = []
    try:
        while True:
            f = img.convert("RGB").resize((w, h))
            buf = io.BytesIO()
            f.save(buf, format="JPEG", quality=q)
            frames.append(buf.getvalue())
            img.seek(img.tell()+1)
    except EOFError:
        pass
    hdr = bytes([0x23, len(frames), (speed>>8)&0xff, speed&0xff, h, w])
    payload = hdr
    for j in frames:
        payload += bytes([1]) + struct.pack(">I", len(j)) + j
    return payload

def send(path, opcode):
    blob = encode_blob(path)
    print(f"blob {len(blob)}B, opcode 0x{opcode:02x}")
    # announce
    dv_raw(bytes([opcode, 0x00]) + struct.pack("<I", len(blob)))
    time.sleep(0.3)
    # chunks
    n = (len(blob)+CHUNK_SIZE-1)//CHUNK_SIZE
    for i in range(n):
        payload = blob[i*CHUNK_SIZE:(i+1)*CHUNK_SIZE]
        chunk = bytes([opcode, 0x01]) + struct.pack("<I", len(blob)) + struct.pack("<H", i) + payload
        dv_raw(chunk)
        time.sleep(0.04)
    print(f"sent {n} chunks via 0x{opcode:02x}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(64)
    send(sys.argv[1], int(sys.argv[2], 16))
