#!/usr/bin/env python3
"""Upload a photo to the Minitoo using the FULL two-file BluePhotoModel pipeline:
   File 0 (fileType=0): WebP-encoded preview at full resolution
   File 1 (fileType=1): eZip-encoded main at 72×72 (DeviceFunction.f11434m0)

Sequence (from BluePhotoModel.p() + .n() + .q()):

  1. Photo/LocalAddToAlbum JSON metadata (with both PhotoFlag and PreviewFileName)
  2. SPP_LOCAL_PICTURE 12-byte header for FILE 0 (fileType=0, fileIndex=0)
  3. Stream WebP chunks
  4. (device should send b10=2 = "next file"; we just stream the next batch)
  5. SPP_LOCAL_PICTURE 12-byte header for FILE 1 (fileType=1, fileIndex=0 still)
  6. Stream eZip chunks
"""
import io, json, os, random, struct, subprocess, sys, time
from PIL import Image

HERE = os.path.dirname(__file__)
DV   = os.path.join(HERE, "dv")
PNG2EZIP = os.path.join(HERE, "ezip", "png2ezip-v2")
PREVIEW_W, PREVIEW_H = 160, 128       # WebP preview at full screen size
MAIN_SIZE = 72                         # eZip main at 72×72 per f11434m0
CHUNK_SIZE = 256

ECOLOR    = "rgb565"
ETYPE     = "1"
BINTYPE   = "1"
BOARDTYPE = "2"

def encode_webp_preview(image_path: str) -> bytes:
    img = Image.open(image_path).convert("RGB").resize((PREVIEW_W, PREVIEW_H))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80, lossless=False)
    return buf.getvalue()

def encode_ezip_main(image_path: str) -> bytes:
    img = Image.open(image_path).convert("RGB").resize((MAIN_SIZE, MAIN_SIZE))
    tmp_png = "/tmp/photo-ezip2-in.png"
    tmp_bin = "/tmp/photo-ezip2-out.bin"
    img.save(tmp_png, format="PNG")
    if os.path.exists(tmp_bin): os.unlink(tmp_bin)
    subprocess.run([PNG2EZIP, tmp_png, tmp_bin, ECOLOR, ETYPE, BINTYPE, BOARDTYPE],
                   check=True, capture_output=True)
    return open(tmp_bin, "rb").read()

def dv_raw(byte_seq: bytes) -> None:
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def dv_json(obj: dict) -> None:
    subprocess.run([DV, "json", json.dumps(obj, separators=(",", ":"))], check=True)

def send_one_file(file_bytes: bytes, photo_flag: int, file_type: int, file_index: int):
    """Send one file (preview or main) — header + chunks."""
    # 12-byte SPP_LOCAL_PICTURE header
    header = (bytes([0x00])
              + struct.pack("<I", len(file_bytes))
              + struct.pack("<I", photo_flag)
              + bytes([file_type, 0x01, file_index]))   # totalCount=1 photo
    print(f"  → header (fileType={file_type}, len={len(file_bytes)}): {header.hex(' ')}")
    dv_raw(bytes([0x8F]) + header)
    time.sleep(0.3)
    # Chunks
    n_chunks = (len(file_bytes) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"  → streaming {n_chunks} chunks…")
    for i in range(n_chunks):
        payload = file_bytes[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (bytes([0x01])
                 + struct.pack("<I", len(file_bytes))
                 + struct.pack("<H", i)
                 + payload)
        dv_raw(bytes([0x8F]) + chunk)
        time.sleep(0.04)

def main(image_path: str, album_id: int):
    webp_preview = encode_webp_preview(image_path)
    ezip_main    = encode_ezip_main(image_path)
    print(f"preview WebP: {len(webp_preview)}B ({PREVIEW_W}×{PREVIEW_H})")
    print(f"main eZip:    {len(ezip_main)}B ({MAIN_SIZE}×{MAIN_SIZE})")

    photo_flag = random.randint(1, 2**31 - 1)
    main_name    = f"mac-{int(time.time())}.webp"
    preview_name = f"preview-mac-{int(time.time())}.webp"
    now_ms       = int(time.time() * 1000)

    # 1) JSON metadata with BOTH file names
    print("\n=== Photo/LocalAddToAlbum metadata ===")
    dv_json({
        "Command":          "Photo/LocalAddToAlbum",
        "ClockId":          album_id,
        "FileName":         main_name,
        "PreviewFileName":  preview_name,
        "PhotoFlag":        photo_flag,
        "PhotoIndex":       0,
        "PhotoTotalCnt":    1,
        "PhotoWidth":       PREVIEW_W,
        "PhotoHeight":      PREVIEW_H,
        "PhotoX":           0, "PhotoY": 0,
        "PhotoTitle":       "mac",
        "SendTime":         now_ms,
        "TakingTime":       now_ms,
    })
    time.sleep(0.4)

    # 2) Send file 0 (preview WebP)
    print("\n=== File 0 — preview (WebP) ===")
    send_one_file(webp_preview, photo_flag, file_type=0, file_index=0)

    # 3) Brief pause to let device process file 0 ack
    time.sleep(0.6)

    # 4) Send file 1 (main eZip)
    print("\n=== File 1 — main (eZip) ===")
    send_one_file(ezip_main, photo_flag, file_type=1, file_index=0)

    print("\nupload complete. watch the device.")

if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 3):
        print(__doc__); sys.exit(64)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) == 3 else 1)
