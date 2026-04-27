#!/usr/bin/env python3
"""Upload an image as a real Divoom photo (eZip-encoded) to the Minitoo.

Uses our `ezip/png2ezip` macOS bridge that calls SiFli's official eZIPSDK
ImageConvertor to produce eZip/RGB565 binary output — the format the Minitoo
firmware actually expects on the photo-album upload pipeline (where WebP/JPEG
were silently rejected and crashed the device on display).

Pipeline (from BluePhotoModel decompile, see FINDINGS §8d):

  1. JSON metadata: Photo/LocalAddToAlbum {ClockId, FileName, PhotoFlag,
     PhotoIndex, PhotoTotalCnt, PhotoWidth, PhotoHeight, ...}
  2. Binary header SPP_LOCAL_PICTURE (0x8F):
        [0x00, file_size_u32_LE, photoFlag_u32_LE,
         fileType_u8=1, totalCount_u8=1, fileIndex_u8=0]
  3. Stream 256-byte chunks of eZip body, each:
        [0x01, total_len_u32_LE, chunk_index_u16_LE, payload]

Usage:  ./photo-ezip.py <image.png> [album_id]
"""
import io, json, os, random, struct, subprocess, sys, time
from PIL import Image

HERE = os.path.dirname(__file__)
DV   = os.path.join(HERE, "dv")
PNG2EZIP = os.path.join(HERE, "ezip", "png2ezip-v2")
TARGET_W = int(os.environ.get("EZIP_W", "128"))
TARGET_H = int(os.environ.get("EZIP_H", "128"))
CHUNK_SIZE = 256
ALBUM_DEFAULT = 1
# eZip params — overridable via env vars to probe what Minitoo expects
ECOLOR     = os.environ.get("EZIP_COLOR", "rgb565")
ETYPE      = os.environ.get("EZIP_ETYPE", "1")     # 0=keep alpha, 1=no alpha
BINTYPE    = os.environ.get("EZIP_BINTYPE", "1")   # 0=with rotation (uncompressed), 1=no rotation (compressed)
BOARDTYPE  = os.environ.get("EZIP_BOARD", "2")     # 0=55X, 1=56X, 2=52X

def encode_ezip(image_path: str) -> bytes:
    img = Image.open(image_path).convert("RGB").resize((TARGET_W, TARGET_H))
    tmp_png = "/tmp/photo-ezip-in.png"
    tmp_bin = "/tmp/photo-ezip-out.bin"
    img.save(tmp_png, format="PNG")
    if os.path.exists(tmp_bin): os.unlink(tmp_bin)
    subprocess.run(
        [PNG2EZIP, tmp_png, tmp_bin, ECOLOR, ETYPE, BINTYPE, BOARDTYPE],
        check=True, capture_output=True)
    print(f"  encoder params: eColor={ECOLOR} eType={ETYPE} binType={BINTYPE} board={BOARDTYPE}")
    return open(tmp_bin, "rb").read()

def dv_raw(byte_seq: bytes) -> None:
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def dv_json(obj: dict) -> None:
    subprocess.run([DV, "json", json.dumps(obj, separators=(",", ":"))], check=True)

def main(image_path: str, album_id: int) -> None:
    ezip = encode_ezip(image_path)
    print(f"encoded eZip: {len(ezip)}B ({TARGET_W}x{TARGET_H})")

    photo_flag = random.randint(1, 2**31 - 1)
    file_name  = f"mac-{int(time.time())}.webp"   # extension always .webp per app
    now_ms     = int(time.time() * 1000)

    # 1) JSON metadata
    print(f"sending Photo/LocalAddToAlbum metadata (photoFlag={photo_flag})…")
    dv_json({
        "Command":       "Photo/LocalAddToAlbum",
        "ClockId":       album_id,
        "FileName":      file_name,
        "PhotoFlag":     photo_flag,
        "PhotoIndex":    0,
        "PhotoTotalCnt": 1,
        "PhotoWidth":    TARGET_W,
        "PhotoHeight":   TARGET_H,
        "PhotoX":        0, "PhotoY": 0,
        "PhotoTitle":    "mac-test",
        "SendTime":      now_ms,
        "TakingTime":    now_ms,
    })
    time.sleep(0.3)

    # 2) Binary header — 12 bytes
    header = (bytes([0x00])
              + struct.pack("<I", len(ezip))
              + struct.pack("<I", photo_flag)
              + bytes([0x01, 0x01, 0x00]))   # fileType=photo, totalCount=1, fileIndex=0
    print(f"announce header: {header.hex(' ')}")
    dv_raw(bytes([0x8F]) + header)
    time.sleep(0.3)

    # 3) Chunks
    n_chunks = (len(ezip) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n_chunks} eZip chunks…")
    for i in range(n_chunks):
        payload = ezip[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (bytes([0x01])
                 + struct.pack("<I", len(ezip))
                 + struct.pack("<H", i)
                 + payload)
        dv_raw(bytes([0x8F]) + chunk)
        time.sleep(0.04)
        if (i + 1) % 5 == 0 or i == n_chunks - 1:
            print(f"  chunk {i+1}/{n_chunks}")

    print("upload complete. NOT triggering Photo/Enter (crashed before with WebP).")
    print("Watch device — image should be in the gallery rotation now (and might")
    print("be displayed full-screen if it became the most recent).")

if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 3):
        print(__doc__); sys.exit(64)
    img   = sys.argv[1]
    album = int(sys.argv[2]) if len(sys.argv) == 3 else ALBUM_DEFAULT
    main(img, album)
