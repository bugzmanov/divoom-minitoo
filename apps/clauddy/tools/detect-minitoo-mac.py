#!/usr/bin/env python3
"""Best-effort Divoom display-device Bluetooth MAC detector for macOS.

Recognizes the Jieli-SoC Divoom speakers that share the MiniToo firmware/
protocol stack. Extend SUPPORTED_DEVICE_TOKENS to add more variants once
they have been verified end-to-end.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterator


MAC_RE = re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}")

SUPPORTED_DEVICE_TOKENS = ("minitoo", "tiivoo")


def normalize_mac(value: str) -> str:
    return value.replace("-", ":").upper()


def is_minitoo_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.lower().replace("-", " ")
    return any(token in normalized for token in SUPPORTED_DEVICE_TOKENS)


def strings_in(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def add_candidate(
    candidates: dict[str, tuple[str, str]],
    mac: str,
    name: str | None,
    source: str,
) -> None:
    normalized = normalize_mac(mac)
    display_name = name.strip() if name else "Divoom display device"
    if normalized not in candidates:
        candidates[normalized] = (display_name, source)


def walk_json(value: object, source: str, candidates: dict[str, tuple[str, str]]) -> None:
    if isinstance(value, dict):
        keys = list(value.keys())
        values = list(value.values())
        names = [item for item in keys if is_minitoo_name(item)]
        names.extend(item for item in values if is_minitoo_name(item))
        macs: list[str] = []
        for item in keys:
            macs.extend(MAC_RE.findall(str(item)))
        for item in values:
            if isinstance(item, str):
                macs.extend(MAC_RE.findall(item))
        if names:
            for item in strings_in(value):
                macs.extend(MAC_RE.findall(item))
        if names and macs:
            for mac in macs:
                add_candidate(candidates, mac, str(names[0]), source)
        for item in values:
            walk_json(item, source, candidates)
    elif isinstance(value, list):
        for item in value:
            walk_json(item, source, candidates)


def run(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_text_blocks(text: str, source: str, candidates: dict[str, tuple[str, str]]) -> None:
    lines = text.splitlines()
    current_name: str | None = None
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        label = line[:-1].strip() if line.endswith(":") else line
        if is_minitoo_name(label):
            current_name = label
            for nearby in lines[index : index + 8]:
                for mac in MAC_RE.findall(nearby):
                    add_candidate(candidates, mac, current_name, source)
            continue

        if current_name:
            for mac in MAC_RE.findall(line):
                add_candidate(candidates, mac, current_name, source)
            if line.endswith(":") and not line.lower().startswith(("address:", "services:")):
                current_name = None


def parse_system_profiler(candidates: dict[str, tuple[str, str]]) -> None:
    json_text = run(["system_profiler", "SPBluetoothDataType", "-json"])
    if json_text:
        try:
            walk_json(json.loads(json_text), "system_profiler", candidates)
        except json.JSONDecodeError:
            pass

    text = run(["system_profiler", "SPBluetoothDataType"])
    if text:
        parse_text_blocks(text, "system_profiler", candidates)


def parse_blueutil(candidates: dict[str, tuple[str, str]]) -> None:
    if shutil.which("blueutil") is None:
        return

    json_text = run(["blueutil", "--paired", "--format", "json"])
    if json_text:
        try:
            walk_json(json.loads(json_text), "blueutil", candidates)
        except json.JSONDecodeError:
            parse_text_blocks(json_text, "blueutil", candidates)

    text = run(["blueutil", "--paired"])
    if text:
        parse_text_blocks(text, "blueutil", candidates)


def parse_ioreg(candidates: dict[str, tuple[str, str]]) -> None:
    text = run(["ioreg", "-r", "-c", "IOBluetoothDevice"])
    if not text:
        return

    current_name: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if '"Name"' in line or '"DeviceName"' in line:
            _, _, value = line.partition("=")
            value = value.strip().strip('"')
            current_name = value if is_minitoo_name(value) else None
        elif current_name and ('"DeviceAddress"' in line or '"Address"' in line):
            for mac in MAC_RE.findall(line):
                add_candidate(candidates, mac, current_name, "ioreg")


def main() -> int:
    candidates: dict[str, tuple[str, str]] = {}
    parse_system_profiler(candidates)
    parse_blueutil(candidates)
    parse_ioreg(candidates)

    for mac, (name, source) in sorted(candidates.items()):
        print(f"{mac}\t{name}\t{source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
