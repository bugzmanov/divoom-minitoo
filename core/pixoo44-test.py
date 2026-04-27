#!/usr/bin/env python3
"""Generate a Pixoo-style 0x44 static image rawfile.

This ports the packet payload shape from PixooMaxApp/PixooManager.kt:
  opcode 0x44, args:
    00 0a 0a 04 aa
    inner_len_le16
    00 00
    03
    palette_count_le16
    palette RGB888 bytes
    packed palette indices, row-major, LSB-first

The output is a dv rawfile line: "44 <args...>".
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


WIDTH = 32
HEIGHT = 32


def build_test_screen() -> tuple[list[tuple[int, int, int]], list[int]]:
    palette = [
        (0x00, 0x00, 0x00),  # black
        (0xff, 0x00, 0x00),  # red
        (0x00, 0xff, 0x00),  # green
        (0x00, 0x40, 0xff),  # blue
        (0xff, 0xff, 0x00),  # yellow
    ]
    screen: list[int] = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if x in (0, WIDTH - 1) or y in (0, HEIGHT - 1) or x == y or x == WIDTH - 1 - y:
                screen.append(0)
            elif x < WIDTH // 2 and y < HEIGHT // 2:
                screen.append(1)
            elif x >= WIDTH // 2 and y < HEIGHT // 2:
                screen.append(2)
            elif x < WIDTH // 2 and y >= HEIGHT // 2:
                screen.append(3)
            else:
                screen.append(4)
    return palette, screen


def pack_indices(indices: list[int], color_count: int) -> bytes:
    bit_length = max(1, math.ceil(math.log2(color_count)))
    out = bytearray(math.ceil((bit_length * len(indices)) / 8))
    buffer = 0
    buffer_bits = 0
    out_index = 0
    mask = (1 << bit_length) - 1
    for index in indices:
        buffer |= (index & mask) << buffer_bits
        buffer_bits += bit_length
        while buffer_bits >= 8:
            out[out_index] = buffer & 0xff
            out_index += 1
            buffer >>= 8
            buffer_bits -= 8
    if buffer_bits:
        out[out_index] = buffer & 0xff
    return bytes(out)


def build_args() -> bytes:
    palette, screen = build_test_screen()
    palette_bytes = bytes(channel for rgb in palette for channel in rgb)
    image_bytes = pack_indices(screen, len(palette))
    pixels_and_palette = palette_bytes + image_bytes

    inner_length = 8 + len(pixels_and_palette)
    header = bytes(
        [
            0x00,
            0x0A,
            0x0A,
            0x04,
            0xAA,
            inner_length & 0xFF,
            (inner_length >> 8) & 0xFF,
            0x00,
            0x00,
            0x03,
            len(palette) & 0xFF,
            (len(palette) >> 8) & 0xFF,
        ]
    )
    return header + pixels_and_palette


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-o",
        "--output",
        default="/tmp/minitoo-pixoo44-test.raw",
        help="dv rawfile path to write",
    )
    args = parser.parse_args()

    payload = bytes([0x44]) + build_args()
    line = " ".join(f"{byte:02x}" for byte in payload)
    output = Path(args.output)
    output.write_text(line + "\n", encoding="utf-8")
    print(f"wrote {output} ({len(payload)} raw opcode+arg bytes)")
    print(f"payload preview: {line[:120]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
