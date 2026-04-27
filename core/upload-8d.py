#!/usr/bin/env python3
"""Upload + PLAY via 0x8d (App big64 user define) — the variant with the
deterministic play-by-FileId primitive. Per official Divoom docs and ztomer's lib.

Usage:
  ./upload-8d.py upload <image.png> <file_id> <index>
  ./upload-8d.py play   <file_id> <index>
  ./upload-8d.py delete <file_id> <index>
"""
import os, struct, subprocess, sys, time
from PIL import Image

HERE = os.path.dirname(__file__)
DV   = os.path.join(HERE, "dv")
PNG2EZIP = os.path.join(HERE, "ezip", "png2ezip-v2")
CHUNK_SIZE = 256

def encode(image_path):
    img = Image.open(image_path).convert("RGB").resize((128, 128))
    tmp_png = "/tmp/upload-8d.png"; tmp_bin = "/tmp/upload-8d.bin"
    img.save(tmp_png, format="PNG")
    if os.path.exists(tmp_bin): os.unlink(tmp_bin)
    subprocess.run([PNG2EZIP, tmp_png, tmp_bin, "rgb565", "1", "1", "2"],
                   check=True, capture_output=True)
    return open(tmp_bin, "rb").read()

def dv_raw(byte_seq):
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def upload(image_path, file_id, index):
    blob = encode(image_path)
    print(f"encoded eZip: {len(blob)}B, file_id={file_id}, index={index}")

    # Control_Word=0 (Start): [file_size_LE, index_BE, file_id_BE]
    start = (bytes([0x00])
             + struct.pack("<I", len(blob))   # file_size LE
             + bytes([index & 0xFF])           # index 1 byte BE
             + struct.pack(">I", file_id))    # file_id BE
    print(f"START: {start.hex(' ')}")
    dv_raw(bytes([0x8D]) + start)
    time.sleep(0.5)

    # Control_Word=1 (Send data): [total_len_LE, offset_LE, payload]
    n = (len(blob) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n} chunks…")
    for i in range(n):
        payload = blob[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (bytes([0x01])
                 + struct.pack("<I", len(blob))
                 + struct.pack("<H", i)
                 + payload)
        dv_raw(bytes([0x8D]) + chunk)
        time.sleep(0.05)
        if (i+1) % 5 == 0 or i == n-1:
            print(f"  chunk {i+1}/{n}")

    # Control_Word=2 (End)
    print("END (Control_Word=2)")
    dv_raw(bytes([0x8D, 0x02]))
    time.sleep(0.3)
    print(f"upload done. now play with: ./upload-8d.py play {file_id} {index}")

def play(file_id, index):
    # Control_Word=4 (Play): [file_id_BE, index_BE]
    args = bytes([0x04]) + struct.pack(">I", file_id) + bytes([index & 0xFF])
    print(f"PLAY {file_id}/{index}: {args.hex(' ')}")
    dv_raw(bytes([0x8D]) + args)
    time.sleep(0.3)

def delete(file_id, index):
    # Control_Word=3 (Delete): [file_id_BE, index_BE]
    args = bytes([0x03]) + struct.pack(">I", file_id) + bytes([index & 0xFF])
    print(f"DELETE {file_id}/{index}: {args.hex(' ')}")
    dv_raw(bytes([0x8D]) + args)
    time.sleep(0.3)

if __name__ == "__main__":
    if len(sys.argv) < 2: print(__doc__); sys.exit(64)
    op = sys.argv[1]
    if op == "upload" and len(sys.argv) == 5:
        upload(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    elif op == "play" and len(sys.argv) == 4:
        play(int(sys.argv[2]), int(sys.argv[3]))
    elif op == "delete" and len(sys.argv) == 4:
        delete(int(sys.argv[2]), int(sys.argv[3]))
    else:
        print(__doc__); sys.exit(64)
