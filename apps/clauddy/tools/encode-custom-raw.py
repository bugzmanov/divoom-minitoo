#!/usr/bin/env python3
"""Encode a GIF into the MiniToo custom-face rawfile served by dv start-custom."""

from __future__ import annotations

import argparse
import io
import struct
import sys
from functools import reduce
from math import gcd
from pathlib import Path

try:
    from PIL import Image, ImageSequence
except ImportError as exc:  # pragma: no cover - exercised by shell installer
    raise SystemExit("error: Pillow is required. Install it with: python3 -m pip install Pillow") from exc


WIDTH = 160
HEIGHT = 128
CELL_ROWS = 8
CELL_COLS = 10
CHUNK_SIZE = 256
MIN_SPEED_MS = 40
MAX_FRAMES = 255
RESAMPLE_MODES = {
    "nearest": Image.Resampling.NEAREST,
    "lanczos": Image.Resampling.LANCZOS,
}


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def render_frame(frame: Image.Image, fit: str, resample: Image.Resampling) -> Image.Image:
    rgba = frame.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    bg.alpha_composite(rgba)
    rgb = bg.convert("RGB")

    if fit == "stretch":
        return rgb.resize((WIDTH, HEIGHT), resample)

    if fit == "contain":
        canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        copy = rgb.copy()
        copy.thumbnail((WIDTH, HEIGHT), resample)
        x = (WIDTH - copy.width) // 2
        y = (HEIGHT - copy.height) // 2
        canvas.paste(copy, (x, y))
        return canvas

    if fit == "cover":
        scale = max(WIDTH / rgb.width, HEIGHT / rgb.height)
        resized = rgb.resize(
            (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
            resample,
        )
        x = (resized.width - WIDTH) // 2
        y = (resized.height - HEIGHT) // 2
        return resized.crop((x, y, x + WIDTH, y + HEIGHT))

    raise ValueError(f"unknown fit mode: {fit}")


def apply_timing(frames: list[bytes], durations: list[int], speed_ms: int | None, speed_scale: float) -> tuple[list[bytes], int]:
    nonzero_durations = [duration for duration in durations if duration > 0]

    if speed_ms is not None:
        chosen_speed = round(speed_ms * speed_scale)
        return frames, chosen_speed

    if not nonzero_durations:
        source_speed = round(sum(nonzero_durations) / len(nonzero_durations)) if nonzero_durations else 200
        return frames, round(source_speed * speed_scale)

    scaled_durations = [
        max(1, round((duration if duration > 0 else nonzero_durations[0]) * speed_scale))
        for duration in durations
    ]
    base_speed = reduce(gcd, scaled_durations)
    base_speed = max(MIN_SPEED_MS, base_speed)

    expanded: list[bytes] = []
    for jpeg, duration in zip(frames, scaled_durations):
        repeats = max(1, round(duration / base_speed))
        expanded.extend([jpeg] * repeats)

    if len(expanded) > MAX_FRAMES:
        raise ValueError(
            "GIF timing expands "
            f"{len(frames)} source frames into {len(expanded)} encoded frames, "
            f"exceeding the MiniToo {MAX_FRAMES}-frame header limit. "
            "Simplify the GIF timing or use --speed-ms for one fixed delay."
        )
    return expanded, base_speed


def encode_payload(input_path: Path, speed_ms: int | None, speed_scale: float, quality: int, fit: str, resample_name: str, max_payload_bytes: int) -> tuple[bytes, int, int, int]:
    im = Image.open(input_path)
    frames: list[bytes] = []
    durations: list[int] = []
    resample = RESAMPLE_MODES[resample_name]

    for frame in ImageSequence.Iterator(im):
        durations.append(int(frame.info.get("duration") or 0))
        rendered = render_frame(frame, fit, resample)
        buf = io.BytesIO()
        rendered.save(buf, format="JPEG", quality=quality, subsampling=0)
        frames.append(buf.getvalue())

    if not frames:
        raise ValueError(f"no frames found in {input_path}")
    source_frame_count = len(frames)

    frames, chosen_speed = apply_timing(frames, durations, speed_ms, speed_scale)
    if len(frames) > MAX_FRAMES:
        raise ValueError(f"MiniToo header has one-byte frame count; got {len(frames)} frames")
    if chosen_speed <= 0 or chosen_speed > 65535:
        raise ValueError(f"speed must fit uint16 milliseconds, got {chosen_speed}")

    payload = bytes([
        0x23,
        len(frames) & 0xFF,
        (chosen_speed >> 8) & 0xFF,
        chosen_speed & 0xFF,
        CELL_ROWS,
        CELL_COLS,
    ])
    for jpeg in frames:
        payload += bytes([0x01])
        payload += struct.pack(">I", len(jpeg))
        payload += jpeg

    if max_payload_bytes > 0 and len(payload) > max_payload_bytes:
        raise ValueError(
            f"payload is {len(payload):,} bytes, above limit {max_payload_bytes:,}. "
            "Lower --quality or raise --max-payload-bytes if you accept the risk."
        )

    return payload, source_frame_count, len(frames), chosen_speed


def write_rawfile(payload: bytes, file_id: str, output_path: Path) -> int:
    file_id_bytes = file_id.encode("ascii")
    if len(file_id_bytes) > 255:
        raise ValueError("file id is too long for the protocol")

    lines: list[str] = []
    start = bytes([0xBE, 0x00]) + struct.pack("<I", len(payload)) + bytes([len(file_id_bytes)]) + file_id_bytes
    lines.append(start.hex(" "))

    chunks = 0
    for index in range((len(payload) + CHUNK_SIZE - 1) // CHUNK_SIZE):
        chunk = payload[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
        frame = bytes([0xBE, 0x01]) + struct.pack("<I", len(payload)) + struct.pack("<H", index) + chunk
        lines.append(frame.hex(" "))
        chunks += 1

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Encode a GIF for the MiniToo 0xBE custom-face upload path.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--speed-ms", type=positive_int, help="Override the GIF's original timing with one fixed frame delay in ms.")
    parser.add_argument("--speed-scale", type=positive_float, default=1.0, help="Multiplier applied to the chosen frame speed. Values >1 slow playback.")
    parser.add_argument("--quality", type=int, default=95)
    parser.add_argument("--fit", choices=("stretch", "contain", "cover"), default="cover")
    parser.add_argument("--resample", choices=tuple(RESAMPLE_MODES), default="nearest", help="Resize filter. nearest is best for pixel art.")
    parser.add_argument("--max-payload-bytes", type=int, default=0, help="Optional safety limit. 0 disables the size guard.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"error: missing input GIF: {args.input}", file=sys.stderr)
        return 2
    if not 1 <= args.quality <= 100:
        print("error: --quality must be 1..100", file=sys.stderr)
        return 2
    if args.max_payload_bytes < 0:
        print("error: --max-payload-bytes must be >= 0", file=sys.stderr)
        return 2

    try:
        payload, source_frame_count, frame_count, speed_ms = encode_payload(args.input, args.speed_ms, args.speed_scale, args.quality, args.fit, args.resample, args.max_payload_bytes)
        chunks = write_rawfile(payload, args.file_id, args.output)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"input={args.input}")
    print(f"output={args.output}")
    print(f"file_id={args.file_id}")
    print(f"source_frames={source_frame_count} encoded_frames={frame_count} speed_ms={speed_ms} speed_scale={args.speed_scale:g} quality={args.quality} fit={args.fit} resample={args.resample} subsampling=0")
    print(f"payload_bytes={len(payload)} chunks={chunks}")
    print(f"payload_prefix={payload[:16].hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
