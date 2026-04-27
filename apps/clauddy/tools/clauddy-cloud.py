#!/usr/bin/env python3
"""One-shot Divoom cloud setup for Clauddy.

The password and auth token are kept in memory only. The generated config stores
Bluetooth and clock metadata, not credentials.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import locale
import os
import shlex
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://appin.divoom-gz.com"
STYLE_RIMLESS = 798
STYLE_NOISE_BARS = 828


class DivoomError(RuntimeError):
    pass


@dataclass
class Auth:
    user_id: int
    token: int


def java_md5(text: str) -> str:
    data = bytes(ord(ch) & 0xFF for ch in text)
    return hashlib.md5(data).hexdigest()


def default_timezone() -> str:
    hours = -time.timezone // 3600
    return f"+{hours}" if hours >= 0 else str(hours)


def default_country() -> str:
    loc = locale.getlocale()[0] or ""
    if "_" in loc:
        return loc.split("_", 1)[1].upper()
    return "US"


def default_language() -> str:
    loc = locale.getlocale()[0] or ""
    lang = loc.split("_", 1)[0].lower() if loc else "en"
    if lang == "zh":
        return "zh-hans" if default_country() in {"CN", "SG"} else "zh-hant"
    return lang or "en"


def post_json(base_url: str, command: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{command}"
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Connection": "close",
            "User-Agent": "clauddy-setup/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise DivoomError(f"{command}: HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise DivoomError(f"{command}: network error: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DivoomError(f"{command}: non-JSON response: {raw[:500]}") from exc

    code = parsed.get("ReturnCode")
    if code not in (0, None):
        raise DivoomError(f"{command}: ReturnCode={code} ReturnMessage={parsed.get('ReturnMessage')!r}")
    return parsed


def base_payload(args: argparse.Namespace, auth: Auth | None = None) -> dict[str, Any]:
    return {
        "DeviceId": args.device_id,
        "Token": auth.token if auth else 0,
        "UserId": auth.user_id if auth else 0,
    }


def login(args: argparse.Namespace, email: str, password: str) -> Auth:
    response = post_json(
        args.base_url,
        "UserLogin",
        {
            **base_payload(args),
            "Command": "UserLogin",
            "Email": email,
            "Password": java_md5(password),
            "TimeZone": args.timezone,
            "CountryISOCode": args.country,
            "Language": args.language,
        },
        args.timeout,
    )
    user_id = int(response.get("UserId") or 0)
    token = int(response.get("Token") or 0)
    if not user_id or not token:
        raise DivoomError("UserLogin succeeded but did not return UserId and Token")
    return Auth(user_id=user_id, token=token)


def my_clock_list(args: argparse.Namespace, auth: Auth) -> list[dict[str, Any]]:
    response = post_json(
        args.base_url,
        "Channel/MyClockGetList",
        {
            **base_payload(args, auth),
            "Command": "Channel/MyClockGetList",
            "StartNum": 1,
            "EndNum": 100,
            "Flag": 0,
            "CountryISOCode": args.country,
            "Language": args.language,
        },
        args.timeout,
    )
    return list(response.get("ClockList") or [])


def store_custom_candidates(args: argparse.Namespace, auth: Auth) -> list[dict[str, Any]]:
    classify = post_json(
        args.base_url,
        "Channel/StoreClockGetClassify",
        {
            **base_payload(args, auth),
            "Command": "Channel/StoreClockGetClassify",
            "StartNum": 0,
            "EndNum": 0,
            "CountryISOCode": args.country,
            "Language": args.language,
        },
        args.timeout,
    )
    classify_list = list(classify.get("ClassifyList") or [])
    if not classify_list:
        return []
    classify_id = int(classify_list[0].get("ClassifyId") or 0)
    response = post_json(
        args.base_url,
        "Channel/StoreClockGetList",
        {
            **base_payload(args, auth),
            "Command": "Channel/StoreClockGetList",
            "StartNum": 1,
            "EndNum": 30,
            "Flag": 0,
            "ClassifyId": classify_id,
            "CountryISOCode": args.country,
            "Language": args.language,
        },
        args.timeout,
    )
    return list(response.get("ClockList") or [])


def map_custom_clocks(items: list[dict[str, Any]]) -> dict[str, int]:
    found: dict[str, int] = {}
    by_type = {3: "chilling", 4: "working", 5: "alerting"}
    for item in items:
        try:
            clock_type = int(item.get("ClockType") or 0)
            clock_id = int(item.get("ClockId") or 0)
        except (TypeError, ValueError):
            continue
        state = by_type.get(clock_type)
        if state and clock_id:
            found[state] = clock_id
    return found


def set_style(args: argparse.Namespace, auth: Auth, clock_id: int, style_id: int) -> None:
    post_json(
        args.base_url,
        "Channel/SetClockStyle",
        {
            **base_payload(args, auth),
            "Command": "Channel/SetClockStyle",
            "ClockId": clock_id,
            "StyleId": style_id,
            "ParentClockId": 0,
            "ParentItemId": "",
            "PageIndex": 0,
            "LcdIndependence": 0,
            "LcdIndex": 0,
            "Language": args.language,
        },
        args.timeout,
    )


def shell_config(args: argparse.Namespace, clocks: dict[str, int]) -> str:
    values = {
        "CLAUDDY_MINITOO_MAC": args.mac,
        "CLAUDDY_DEVICE_ID": str(args.device_id),
        "CLAUDDY_CLOCK_CHILLING": str(clocks["chilling"]),
        "CLAUDDY_CLOCK_WORKING": str(clocks["working"]),
        "CLAUDDY_CLOCK_ALERTING": str(clocks["alerting"]),
        "CLAUDDY_PAGE_CHILLING": "0",
        "CLAUDDY_PAGE_WORKING": "1",
        "CLAUDDY_PAGE_ALERTING": "2",
        "CLAUDDY_STYLE_CHILLING": str(STYLE_RIMLESS),
        "CLAUDDY_STYLE_WORKING": str(STYLE_NOISE_BARS),
        "CLAUDDY_STYLE_ALERTING": str(STYLE_RIMLESS),
        "CLAUDDY_GENERATED_AT": str(int(time.time())),
    }
    lines = [
        "# Clauddy local config.",
        "# Contains no Divoom password, auth token, or account secret.",
    ]
    for key, value in values.items():
        lines.append(f"{key}={shlex.quote(value)}")
    return "\n".join(lines) + "\n"


def cmd_setup(args: argparse.Namespace) -> int:
    email = args.email or input("Divoom email/username: ").strip()
    if not email:
        print("error: missing Divoom email/username", file=sys.stderr)
        return 2
    password = getpass.getpass("Divoom password (not stored): ")
    if not password:
        print("error: missing Divoom password", file=sys.stderr)
        return 2

    try:
        auth = login(args, email, password)
        clocks = map_custom_clocks(my_clock_list(args, auth))
        if set(clocks) != {"chilling", "working", "alerting"}:
            clocks.update({k: v for k, v in map_custom_clocks(store_custom_candidates(args, auth)).items() if k not in clocks})
        missing = {"chilling", "working", "alerting"} - set(clocks)
        if missing:
            raise DivoomError(f"could not find custom face IDs for: {', '.join(sorted(missing))}")

        set_style(args, auth, clocks["chilling"], STYLE_RIMLESS)
        set_style(args, auth, clocks["working"], STYLE_NOISE_BARS)
        set_style(args, auth, clocks["alerting"], STYLE_RIMLESS)
    except DivoomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.config.parent.mkdir(parents=True, exist_ok=True)
    args.config.write_text(shell_config(args, clocks), encoding="utf-8")
    os.chmod(args.config, 0o600)

    print(f"logged in UserId={auth.user_id} Token=<hidden>")
    print(f"wrote {args.config}")
    print("custom faces:")
    print(f"  chilling -> ClockId={clocks['chilling']} StyleId={STYLE_RIMLESS}")
    print(f"  working  -> ClockId={clocks['working']} StyleId={STYLE_NOISE_BARS}")
    print(f"  alerting -> ClockId={clocks['alerting']} StyleId={STYLE_RIMLESS}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clauddy Divoom cloud setup.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup", help="Discover custom face IDs, set frame styles, and write local config.")
    setup.add_argument("--config", type=Path, required=True)
    setup.add_argument("--mac", required=True)
    setup.add_argument("--device-id", type=int, required=True)
    setup.add_argument("--email")
    setup.add_argument("--base-url", default=DEFAULT_BASE_URL)
    setup.add_argument("--country", default=default_country())
    setup.add_argument("--language", default=default_language())
    setup.add_argument("--timezone", default=default_timezone())
    setup.add_argument("--timeout", type=float, default=15.0)
    setup.set_defaults(func=cmd_setup)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
