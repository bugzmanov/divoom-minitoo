#!/usr/bin/env python3
"""Fetch Divoom clock IDs without exposing credentials in chat.

The script mirrors the Android app's cloud path:

1. POST UserLogin with MD5(password)
2. Use the returned UserId/Token for clock-list endpoints
3. Print only clock IDs and display metadata, not the token or password
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import locale
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "https://appin.divoom-gz.com"
DEFAULT_DEVICE_ID = int(os.environ["DIVOOM_DEVICE_ID"]) if os.environ.get("DIVOOM_DEVICE_ID") else None


class DivoomError(RuntimeError):
    pass


@dataclass
class Auth:
    user_id: int
    token: int
    user_token_present: bool


def java_md5(text: str) -> str:
    """Match the app's N2.q.b(String): char-by-char cast to byte, then MD5."""
    data = bytes(ord(ch) & 0xFF for ch in text)
    return hashlib.md5(data).hexdigest()


def default_timezone() -> str:
    # Java uses TimeZone.getRawOffset(), not DST-aware current offset.
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
        country = default_country()
        return "zh-hans" if country in {"CN", "SG"} else "zh-hant"
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
            "User-Agent": "divoom-clock-id-probe/1",
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
        msg = parsed.get("ReturnMessage", "")
        raise DivoomError(f"{command}: ReturnCode={code} ReturnMessage={msg!r}")
    return parsed


def base_payload(args: argparse.Namespace, auth: Auth | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "DeviceId": args.device_id,
        "Token": auth.token if auth else 0,
        "UserId": auth.user_id if auth else 0,
    }
    return payload


def login(args: argparse.Namespace, email: str, password: str) -> Auth:
    payload = {
        **base_payload(args),
        "Command": "UserLogin",
        "Email": email,
        "Password": java_md5(password),
        "TimeZone": args.timezone,
        "CountryISOCode": args.country,
        "Language": args.language,
    }
    resp = post_json(args.base_url, "UserLogin", payload, args.timeout)
    user_id = int(resp.get("UserId") or 0)
    token = int(resp.get("Token") or 0)
    if not user_id or not token:
        raise DivoomError("UserLogin succeeded but did not return UserId and Token")
    return Auth(user_id=user_id, token=token, user_token_present=bool(resp.get("UserToken")))


def get_my_clock_list(args: argparse.Namespace, auth: Auth) -> list[dict[str, Any]]:
    payload = {
        **base_payload(args, auth),
        "Command": "Channel/MyClockGetList",
        "StartNum": args.start,
        "EndNum": args.end,
        "Flag": 0,
        "CountryISOCode": args.country,
        "Language": args.language,
    }
    resp = post_json(args.base_url, "Channel/MyClockGetList", payload, args.timeout)
    return list(resp.get("ClockList") or [])


def get_store_custom_clock_ids(args: argparse.Namespace, auth: Auth) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classify_payload = {
        **base_payload(args, auth),
        "Command": "Channel/StoreClockGetClassify",
        "StartNum": 0,
        "EndNum": 0,
        "CountryISOCode": args.country,
        "Language": args.language,
    }
    classify_resp = post_json(args.base_url, "Channel/StoreClockGetClassify", classify_payload, args.timeout)
    classify_list = list(classify_resp.get("ClassifyList") or [])
    if not classify_list:
        return [], []

    first_classify_id = int(classify_list[0].get("ClassifyId") or 0)
    list_payload = {
        **base_payload(args, auth),
        "Command": "Channel/StoreClockGetList",
        "StartNum": 1,
        "EndNum": 30,
        "Flag": 0,
        "ClassifyId": first_classify_id,
        "CountryISOCode": args.country,
        "Language": args.language,
    }
    clock_resp = post_json(args.base_url, "Channel/StoreClockGetList", list_payload, args.timeout)
    return classify_list, list(clock_resp.get("ClockList") or [])


def short_item(item: dict[str, Any]) -> str:
    clock_id = item.get("ClockId", "")
    clock_type = item.get("ClockType", "")
    name = item.get("ClockName") or ""
    image_id = item.get("ImagePixelId") or ""
    parts = [f"ClockId={clock_id}", f"ClockType={clock_type}"]
    if name:
        parts.append(f"Name={name!r}")
    if image_id:
        parts.append(f"ImagePixelId={image_id}")
    return "  " + "  ".join(parts)


def print_report(auth: Auth, my_clocks: list[dict[str, Any]], classify: list[dict[str, Any]], store_clocks: list[dict[str, Any]]) -> None:
    print(f"Logged in: UserId={auth.user_id} Token=<hidden> UserTokenPresent={auth.user_token_present}")
    print()

    print("My Clock list:")
    if my_clocks:
        for item in my_clocks:
            print(short_item(item))
    else:
        print("  <empty>")
    print()

    print("Store classify list:")
    if classify:
        for item in classify:
            print(f"  ClassifyId={item.get('ClassifyId')}  Name={item.get('ClassifyName')!r}")
    else:
        print("  <empty>")
    print()

    print("Custom-page candidates from first store classify:")
    custom_by_page: dict[int, dict[str, Any]] = {}
    for item in store_clocks:
        clock_type = int(item.get("ClockType") or 0)
        if clock_type in (3, 4, 5):
            custom_by_page[clock_type - 2] = item

    if custom_by_page:
        for page in (1, 2, 3):
            item = custom_by_page.get(page)
            if item:
                print(f"  CustomFace{page}: {short_item(item).strip()}")
            else:
                print(f"  CustomFace{page}: <not found>")
        ids = [str(custom_by_page[p].get("ClockId")) for p in (1, 2, 3) if p in custom_by_page]
        print()
        print("CUSTOM_CLOCK_IDS=" + ",".join(ids))
    else:
        print("  <none found>")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log in locally to Divoom cloud and print clock IDs needed for MiniToo custom-face switching."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Divoom command API base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--email", help="Divoom account email/username. If omitted, prompts locally.")
    parser.add_argument("--device-id", type=int, default=DEFAULT_DEVICE_ID, required=DEFAULT_DEVICE_ID is None, help="DeviceId to include in requests. Defaults to $DIVOOM_DEVICE_ID.")
    parser.add_argument("--country", default=default_country(), help="CountryISOCode to send (default: locale-derived, usually US)")
    parser.add_argument("--language", default=default_language(), help="Language to send (default: locale-derived, usually en)")
    parser.add_argument("--timezone", default=default_timezone(), help="Raw timezone hour offset, matching the Android app (default: local standard offset)")
    parser.add_argument("--start", type=int, default=1, help="StartNum for Channel/MyClockGetList")
    parser.add_argument("--end", type=int, default=100, help="EndNum for Channel/MyClockGetList")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email or input("Divoom email/username: ").strip()
    if not email:
        print("missing email/username", file=sys.stderr)
        return 2
    password = getpass.getpass("Divoom password: ")
    if not password:
        print("missing password", file=sys.stderr)
        return 2

    try:
        auth = login(args, email, password)
        my_clocks = get_my_clock_list(args, auth)
        classify, store_clocks = get_store_custom_clock_ids(args, auth)
    except DivoomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_report(auth, my_clocks, classify, store_clocks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
