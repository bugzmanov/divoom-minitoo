#!/usr/bin/env python3
"""Upload a single image to the Minitoo as a photo album entry, then play it.

Implements the BluePhotoModel flow from the decompiled Divoom app:

  1. Photo/NewAlbum   -> JSON, creates an album with the given ClockId
  2. Photo/LocalAddToAlbum -> JSON metadata for the incoming file
  3. SPP_LOCAL_PICTURE (0x8F) 12-byte header:
        [0x00, file_size_u32_LE, photoFlag_u32_LE, fileType_u8, totalCount_u8, fileIndex_u8]
  4. SPP_LOCAL_PICTURE 256-byte chunks, each prefixed with:
        [0x01, total_len_u32_LE, chunk_index_u16_LE]
  5. Photo/PlayAlbum {AlbumId: clockId}

See FINDINGS.md §8d for the full protocol.

Usage:  ./photo-send.py <image_path> [album_id]
"""
import io, json, os, random, struct, subprocess, sys, time
from PIL import Image

DV = os.path.join(os.path.dirname(__file__), "dv")
TARGET_SIZE = 128
CHUNK_SIZE = 256
ALBUM_DEFAULT = 7000          # any unused ClockId — album created if missing

def dv_raw(byte_seq: bytes) -> None:
    subprocess.run([DV, "raw"] + [f"{b:02x}" for b in byte_seq], check=True)

def dv_json(obj: dict) -> None:
    subprocess.run([DV, "json", json.dumps(obj, separators=(",", ":"))], check=True)

def encode_webp(path: str) -> bytes:
    img = Image.open(path).convert("RGB").resize((TARGET_SIZE, TARGET_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return buf.getvalue()

def send(image_path: str, album_id: int) -> None:
    webp = encode_webp(image_path)
    print(f"encoded WebP: {len(webp)}B ({TARGET_SIZE}x{TARGET_SIZE})")

    photo_flag = random.randint(1, 2**31 - 1)
    file_name  = f"mac-{int(time.time())}.webp"
    now_ms     = int(time.time() * 1000)

    # 1) SKIP Photo/NewAlbum — that requires Divoom cloud auth to mint a ClockId.
    #    Instead upload directly to an EXISTING album. Album 0/1 should be the
    #    built-in gallery that already contains the "Chinese people" photos.
    print(f"using existing AlbumId={album_id} (skipping NewAlbum)")

    # 2) send JSON metadata header for incoming file
    print(f"sending Photo/LocalAddToAlbum metadata… photoFlag={photo_flag}")
    dv_json({
        "Command":       "Photo/LocalAddToAlbum",
        "ClockId":       album_id,
        "FileName":      file_name,
        "PhotoFlag":     photo_flag,
        "PhotoIndex":    0,
        "PhotoTotalCnt": 1,
        "PhotoWidth":    TARGET_SIZE,
        "PhotoHeight":   TARGET_SIZE,
        "PhotoX":        0,
        "PhotoY":        0,
        "PhotoTitle":    "mac-test",
        "SendTime":      now_ms,
        "TakingTime":    now_ms,
    })
    time.sleep(0.3)

    # 3) SPP_LOCAL_PICTURE 12-byte header
    header = (
        bytes([0x00])                     # marker
        + struct.pack("<I", len(webp))     # file size
        + struct.pack("<I", photo_flag)    # session id
        + bytes([0x01])                    # fileType: 1 = photo
        + bytes([0x01])                    # totalCount
        + bytes([0x00])                    # fileIndex
    )
    assert len(header) == 12, f"header is {len(header)} bytes, expected 12"
    print(f"announce header: {header.hex(' ')}")
    dv_raw(bytes([0x8F]) + header)
    time.sleep(0.3)

    # 4) Stream 256-byte chunks, each: [0x01, total_len_u32_LE, chunk_idx_u16_LE, payload]
    n_chunks = (len(webp) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"streaming {n_chunks} chunk(s) of up to {CHUNK_SIZE}B…")
    for i in range(n_chunks):
        payload = webp[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        chunk = (
            bytes([0x01])
            + struct.pack("<I", len(webp))
            + struct.pack("<H", i)
            + payload
        )
        dv_raw(bytes([0x8F]) + chunk)
        time.sleep(0.08)
        if (i + 1) % 5 == 0 or i == n_chunks - 1:
            print(f"  sent chunk {i+1}/{n_chunks}")

    # 5) DO NOT call Photo/Enter or Photo/PlayAlbum — those have crashed the
    #    device. Just return and let the user check status.
    time.sleep(1.0)
    print("upload complete. NOT sending Photo/Enter or PlayAlbum (crash-prone).")
    print("Check device status — if still responsive, manually Photo/Enter to view.")

if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 3):
        print(__doc__); sys.exit(64)
    img = sys.argv[1]
    album = int(sys.argv[2]) if len(sys.argv) == 3 else ALBUM_DEFAULT
    send(img, album)
