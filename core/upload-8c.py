#!/usr/bin/env python3
"""Upload an image via the OFFICIAL 0x8c (App new user define) pipeline.

Per https://docin.divoom-gz.com/web/#/5/296 :
  Control_Word=0 (start): [file_size_u32_LE, index_u8]
  Control_Word=1 (data):  [total_len_u32_LE, offset_u16_LE, payload (≤256B)]
  Control_Word=2 (end):   empty
After the start frame, app should WAIT for the device's `0xB1` response.

Usage:  ./upload-8c.py <image.png>
"""
import os, struct, subprocess, sys, time
from PIL import Image

HERE = os.path.dirname(__file__)
DV   = os.path.join(HERE, "dv")
PNG2EZIP = os.path.join(HERE, "ezip", "png2ezip-v2")
SLOT_INDEX = 0           # user_index slot 0
CHUNK_SIZE = 256

def encode(image_path):
    img = Image.open(image_path).convert("RGB").resize((128, 128))
    tmp_png = "/tmp/upload-8c.png"; tmp_bin = "/tmp/upload-8c.bin"
    img.save(tmp_png, format="PNG")
    if os.path.exists(tmp_bin): os.unlink(tmp_bin)
    subprocess.run([PNG2EZIP, tmp_png, tmp_bin, "rgb565", "1", "1", "2"],
                   check=True, capture_output=True)
    return open(tmp_bin, "rb").read()

def dv_raw(byte_seq):
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def main(image_path):
    blob = encode(image_path)
    print(f"encoded eZip: {len(blob)}B")

    # Control_Word = 0: start. data = [file_size_u32_LE, index_u8]
    start = bytes([0x00]) + struct.pack("<I", len(blob)) + bytes([SLOT_INDEX])
    print(f"START frame (Control_Word=0): {start.hex(' ')}")
    dv_raw(bytes([0x8C]) + start)
    time.sleep(0.5)   # wait for device 0xB1 response

    # Control_Word = 1: chunks
    n = (len(blob) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n} chunks…")
    for i in range(n):
        payload = blob[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (bytes([0x01])
                 + struct.pack("<I", len(blob))
                 + struct.pack("<H", i)
                 + payload)
        dv_raw(bytes([0x8C]) + chunk)
        time.sleep(0.06)
        if (i+1) % 5 == 0 or i == n-1:
            print(f"  chunk {i+1}/{n}")

    # Control_Word = 2: end
    print("END frame (Control_Word=2)")
    dv_raw(bytes([0x8C, 0x02]))
    time.sleep(0.5)

    print("done. watch the device for any change.")

if __name__ == "__main__":
    if len(sys.argv) != 2: print(__doc__); sys.exit(64)
    main(sys.argv[1])
