#!/usr/bin/env python3
"""
Re-encode the three Clauddy GIFs with a single global palette so the
background stays bit-stable across every frame.

Aseprite GIF export from an RGB sprite produces per-frame palettes; the dark
background ends up with two slightly different "near-black" entries that swap
between frames and cause visible flicker. This script:

  1. Reads each GIF frame as RGB.
  2. Snaps near-duplicate background pixels to one canonical RGB.
  3. Builds one master palette from the union of all frames.
  4. Re-quantizes every frame against that palette.
  5. Saves a multi-frame GIF with one shared global color table.

Run after re-exporting GIFs from Aseprite. Requires Pillow:

  python3 -m pip install Pillow
"""

from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageSequence

ASSETS = Path(__file__).resolve().parent
BG_CANON = (41, 40, 49)
SNAP = {(41, 44, 49), (0, 255, 0)}  # second near-black + decoder green-screen artifact


def rebuild(gif: Path) -> None:
    im = Image.open(gif)
    duration = im.info.get("duration", 100)

    rgb_frames: list[Image.Image] = []
    for f in ImageSequence.Iterator(im):
        r = f.convert("RGB")
        px = r.load()
        for y in range(r.height):
            for x in range(r.width):
                if px[x, y] in SNAP:
                    px[x, y] = BG_CANON
        rgb_frames.append(r.copy())

    # one master palette from the union of all frames
    big = Image.new("RGB", (rgb_frames[0].width, sum(f.height for f in rgb_frames)))
    y = 0
    for f in rgb_frames:
        big.paste(f, (0, y))
        y += f.height
    master = big.quantize(colors=256, dither=Image.Dither.NONE, method=Image.Quantize.MEDIANCUT)

    indexed = []
    for f in rgb_frames:
        q = f.quantize(palette=master, dither=Image.Dither.NONE)
        q.info.pop("transparency", None)
        q.info.pop("background", None)
        indexed.append(q)

    indexed[0].save(
        gif,
        save_all=True,
        append_images=indexed[1:],
        duration=duration,
        loop=0,
        optimize=False,
        disposal=2,
    )

    # report
    re = Image.open(gif)
    n = 0
    samples = []
    while True:
        try:
            re.seek(n)
            samples.append(re.convert("RGB").getpixel((5, 5)))
            n += 1
        except EOFError:
            break
    unique_bg = len(set(samples))
    print(f"  {gif.name}: frames={n} unique_bg={unique_bg}")


def main() -> None:
    for name in ("chilling.gif", "alerting.gif", "working.gif"):
        rebuild(ASSETS / name)


if __name__ == "__main__":
    main()
