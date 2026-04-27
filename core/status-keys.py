#!/usr/bin/env python3
"""Tiny keyboard app for MiniToo custom-face switching.

Left arrow / 1  -> left custom face
Right arrow / 2 -> right custom face
3               -> optional third custom face
q / Ctrl-C      -> quit
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path


HERE = Path(__file__).resolve().parent
DV = HERE / "dv"
FIFO = Path(os.environ.get("DIVOOM_FIFO", "/tmp/divoom.fifo"))

DEFAULT_MAC = os.environ.get("DIVOOM_MAC")
DEFAULT_DEVICE_ID = int(os.environ["DIVOOM_DEVICE_ID"]) if os.environ.get("DIVOOM_DEVICE_ID") else None

# Confirmed from authenticated Channel/MyClockGetList + live hardware test.
CUSTOM_FACE_1 = 984  # ClockType=3, Custom1, user's creature GIF
CUSTOM_FACE_2 = 986  # ClockType=4, Custom 2
CUSTOM_FACE_3 = 988  # ClockType=5, Custom 3


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=HERE, check=check)


def stop_daemon() -> None:
    if FIFO.exists():
        run([str(DV), "stop"], check=False)


def start_daemon(args: argparse.Namespace) -> None:
    if args.use_existing:
        if not FIFO.exists():
            raise RuntimeError("no existing daemon FIFO; start without --use-existing or run ./dv start first")
        return

    stop_daemon()
    run([str(DV), "start", args.mac])


def selector_payload(clock_id: int, device_id: int) -> dict[str, object]:
    # Mirrors the Android WifiChannelSetClockSelectIdRequest/BaseChannelRequest
    # fields that worked in the live ClockId=986 test.
    return {
        "Command": "Channel/SetClockSelectId",
        "ClockId": clock_id,
        "DeviceId": device_id,
        "ParentClockId": 0,
        "ParentItemId": "",
        "PageIndex": 0,
        "LcdIndependence": 0,
        "LcdIndex": 0,
        "Language": "en",
    }


def send_clock(clock_id: int, args: argparse.Namespace) -> None:
    payload = json.dumps(selector_payload(clock_id, args.device_id), separators=(",", ":"))
    with FIFO.open("w", encoding="utf-8") as fifo:
        fifo.write(f"json {payload}\n")
        fifo.flush()


def read_key() -> str | None:
    ch = sys.stdin.read(1)
    if ch == "\x03":
        return "quit"
    if ch in ("q", "Q"):
        return "quit"
    if ch == "1":
        return "left"
    if ch == "2":
        return "right"
    if ch == "3":
        return "third"
    if ch == "\x1b":
        seq = sys.stdin.read(2)
        if seq == "[D":
            return "left"
        if seq == "[C":
            return "right"
    return None


def key_loop(args: argparse.Namespace) -> None:
    bindings = {
        "left": (args.left_clock_id, args.left_label),
        "right": (args.right_clock_id, args.right_label),
        "third": (args.third_clock_id, args.third_label),
    }

    print("")
    print("MiniToo status keys")
    print(f"  left arrow / 1  -> {args.left_label} ({args.left_clock_id})")
    print(f"  right arrow / 2 -> {args.right_label} ({args.right_clock_id})")
    print(f"  3               -> {args.third_label} ({args.third_clock_id})")
    print("  q               -> quit")
    print("")

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            key = read_key()
            if key == "quit":
                print("\nquitting")
                return
            if key not in bindings:
                continue

            clock_id, label = bindings[key]
            started = time.monotonic()
            send_clock(clock_id, args)
            elapsed = (time.monotonic() - started) * 1000
            print(f"\r{label} queued ({clock_id}, {elapsed:.0f}ms)      ", end="", flush=True)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arrow-key MiniToo custom face switcher.")
    parser.add_argument("--mac", default=DEFAULT_MAC, required=DEFAULT_MAC is None,
                        help="Bluetooth MAC of the Divoom device. Defaults to $DIVOOM_MAC.")
    parser.add_argument("--device-id", type=int, default=DEFAULT_DEVICE_ID, required=DEFAULT_DEVICE_ID is None,
                        help="Divoom cloud DeviceId. Defaults to $DIVOOM_DEVICE_ID.")
    parser.add_argument("--use-existing", action="store_true", help="Use an already-running ./dv daemon instead of starting/stopping one.")
    parser.add_argument("--left-clock-id", type=int, default=CUSTOM_FACE_2)
    parser.add_argument("--right-clock-id", type=int, default=CUSTOM_FACE_1)
    parser.add_argument("--third-clock-id", type=int, default=CUSTOM_FACE_3)
    parser.add_argument("--left-label", default="Custom 2")
    parser.add_argument("--right-label", default="creature")
    parser.add_argument("--third-label", default="Custom 3")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start_daemon(args)
        key_loop(args)
    except KeyboardInterrupt:
        print("\nquitting")
    finally:
        if not getattr(args, "use_existing", False):
            stop_daemon()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
