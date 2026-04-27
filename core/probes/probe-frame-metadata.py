#!/usr/bin/env python3
"""Probe Divoom custom-face frame/border metadata.

This tool is intentionally credential-local:

1. It prompts for the Divoom account password locally.
2. It logs in, then writes redacted JSON snapshots to disk.
3. It never prints the password or token.

Workflow:

    # 1. Before changing a border in the official app:
    ./probe-frame-metadata.py dump --label before --email you@example.com

    # 2. Change exactly one custom-face border/frame in the iPhone app.

    # 3. After the app has saved/synced:
    ./probe-frame-metadata.py dump --label after --email you@example.com

    # 4. Diff:
    ./probe-frame-metadata.py diff /tmp/divoom-frame-before.json /tmp/divoom-frame-after.json

    # Inspect the actual custom-face style/frame catalog:
    ./probe-frame-metadata.py styles --email you@example.com
"""

from __future__ import annotations

import argparse
import difflib
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
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://appin.divoom-gz.com"
DEFAULT_DEVICE_ID = int(os.environ["DIVOOM_DEVICE_ID"]) if os.environ.get("DIVOOM_DEVICE_ID") else None
CUSTOM_CLOCK_IDS = (984, 986, 988)
CANDIDATE_KEY_PARTS = ("frame", "border", "photo", "image", "clock", "custom")


class DivoomError(RuntimeError):
    pass


@dataclass
class Auth:
    user_id: int
    token: int
    user_token_present: bool


def java_md5(text: str) -> str:
    """Match the Android app's char-by-char byte cast, then MD5."""
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
            "User-Agent": "divoom-frame-metadata-probe/1",
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
    return parsed


def base_payload(args: argparse.Namespace, auth: Auth | None = None) -> dict[str, Any]:
    return {
        "DeviceId": args.device_id,
        "Token": auth.token if auth else 0,
        "UserId": auth.user_id if auth else 0,
    }


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
    code = resp.get("ReturnCode")
    if code not in (0, None):
        raise DivoomError(f"UserLogin: ReturnCode={code} ReturnMessage={resp.get('ReturnMessage')!r}")
    user_id = int(resp.get("UserId") or 0)
    token = int(resp.get("Token") or 0)
    if not user_id or not token:
        raise DivoomError("UserLogin succeeded but did not return UserId and Token")
    return Auth(user_id=user_id, token=token, user_token_present=bool(resp.get("UserToken")))


def safe_call(args: argparse.Namespace, auth: Auth, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = post_json(args.base_url, command, payload, args.timeout)
    except DivoomError as exc:
        return {"_probe_error": str(exc), "Command": command}
    return resp


def clock_list_payload(args: argparse.Namespace, auth: Auth) -> dict[str, Any]:
    return {
        **base_payload(args, auth),
        "Command": "Channel/MyClockGetList",
        "StartNum": args.start,
        "EndNum": args.end,
        "Flag": 0,
        "CountryISOCode": args.country,
        "Language": args.language,
    }


def photo_frame_payload(args: argparse.Namespace, auth: Auth, start: int, end: int) -> dict[str, Any]:
    return {
        **base_payload(args, auth),
        "Command": "PhotoFrame/GetList",
        "StartNum": start,
        "EndNum": end,
        "CountryISOCode": args.country,
        "Language": args.language,
    }


def channel_read_payload(args: argparse.Namespace, auth: Auth, command: str) -> dict[str, Any]:
    return {
        **base_payload(args, auth),
        "Command": command,
        "CountryISOCode": args.country,
        "Language": args.language,
    }


def clock_style_payload(args: argparse.Namespace, auth: Auth, clock_id: int) -> dict[str, Any]:
    return {
        **base_payload(args, auth),
        "Command": "Channel/GetClockStyle",
        "ClockId": clock_id,
        "StartNum": args.start,
        "EndNum": args.end,
        "CountryISOCode": args.country,
        "Language": args.language,
    }


def set_clock_style_payload(args: argparse.Namespace, auth: Auth, clock_id: int, style_id: int) -> dict[str, Any]:
    return {
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
    }


def make_snapshot(args: argparse.Namespace, auth: Auth) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "_meta": {
            "base_url": args.base_url,
            "device_id": args.device_id,
            "label": args.label,
            "time": int(time.time()),
            "user_id": auth.user_id,
            "user_token_present": auth.user_token_present,
            "custom_clock_ids": list(CUSTOM_CLOCK_IDS),
        },
        "responses": {},
    }

    calls: list[tuple[str, str, dict[str, Any]]] = [
        ("my_clock", "Channel/MyClockGetList", clock_list_payload(args, auth)),
        ("photo_frame_1_100", "PhotoFrame/GetList", photo_frame_payload(args, auth, 1, 100)),
        ("photo_frame_0_100", "PhotoFrame/GetList", photo_frame_payload(args, auth, 0, 100)),
        ("channel_get_all", "Channel/GetAll", channel_read_payload(args, auth, "Channel/GetAll")),
        ("channel_get_config", "Channel/GetConfig", channel_read_payload(args, auth, "Channel/GetConfig")),
        ("channel_get_current", "Channel/GetCurrent", channel_read_payload(args, auth, "Channel/GetCurrent")),
    ]
    calls.extend(
        (
            (f"clock_style_{clock_id}", "Channel/GetClockStyle", clock_style_payload(args, auth, clock_id))
            for clock_id in CUSTOM_CLOCK_IDS
        )
    )

    for key, command, payload in calls:
        snapshot["responses"][key] = {
            "request": redact(payload),
            "response": safe_call(args, auth, command, payload),
        }
    return snapshot


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"password", "token", "usertoken"}:
                redacted[key] = "<hidden>"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def find_custom_clocks(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    response = snapshot.get("responses", {}).get("my_clock", {}).get("response", {})
    items = response.get("ClockList") or []
    found: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        clock_id = item.get("ClockId")
        try:
            clock_id_int = int(clock_id)
        except (TypeError, ValueError):
            continue
        if clock_id_int in CUSTOM_CLOCK_IDS:
            found[str(clock_id_int)] = item
    return found


def interesting_paths(value: Any, path: str = "") -> list[tuple[str, Any]]:
    hits: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            if any(part in str(key).lower() for part in CANDIDATE_KEY_PARTS):
                hits.append((next_path, item))
            hits.extend(interesting_paths(item, next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(interesting_paths(item, f"{path}[{index}]"))
    return hits


def json_lines(value: Any) -> list[str]:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).splitlines()


def summarize_style_response(clock_id: int, response: dict[str, Any]) -> None:
    if response.get("_probe_error"):
        print(f"ClockId={clock_id} style probe error: {response['_probe_error']}")
        return
    code = response.get("ReturnCode")
    msg = response.get("ReturnMessage")
    print(
        f"ClockId={clock_id} style: ReturnCode={code} "
        f"CurStyleId={response.get('CurStyleId')} "
        f"CurStylePixelImageId={response.get('CurStylePixelImageId')!r}"
        + (f" ReturnMessage={msg!r}" if msg else "")
    )
    for item in response.get("StyleList") or []:
        if not isinstance(item, dict):
            continue
        print(
            f"  StyleId={item.get('StyleId')} "
            f"Name={item.get('StyleName')!r} "
            f"StylePixelImageId={item.get('StylePixelImageId')!r}"
        )


def diff_values(before: Any, after: Any, name: str) -> None:
    before_lines = json_lines(before)
    after_lines = json_lines(after)
    if before_lines == after_lines:
        print(f"{name}: no change")
        return
    print(f"\n{name}: changed")
    for line in difflib.unified_diff(before_lines, after_lines, fromfile=f"{name}:before", tofile=f"{name}:after", lineterm=""):
        print(line)


def cmd_dump(args: argparse.Namespace) -> int:
    email = args.email or input("Divoom email/username: ").strip()
    if not email:
        print("missing email/username", file=sys.stderr)
        return 2
    password = os.environ.get(args.password_env) if args.password_env else None
    if password is None:
        password = getpass.getpass("Divoom password: ")
    if not password:
        print("missing password", file=sys.stderr)
        return 2

    try:
        auth = login(args, email, password)
        snapshot = make_snapshot(args, auth)
    except DivoomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.out or Path(f"/tmp/divoom-frame-{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    custom = find_custom_clocks(snapshot)
    print(f"wrote {out}")
    print(f"logged in UserId={auth.user_id} Token=<hidden>")
    for clock_id in map(str, CUSTOM_CLOCK_IDS):
        item = custom.get(clock_id)
        if not item:
            print(f"ClockId={clock_id}: not found in MyClockGetList")
            continue
        name = item.get("ClockName") or item.get("Name") or ""
        clock_type = item.get("ClockType", "")
        print(f"ClockId={clock_id} ClockType={clock_type} Name={name!r}")
        for path, val in interesting_paths(item):
            print(f"  {path}={val!r}")
        style = snapshot.get("responses", {}).get(f"clock_style_{clock_id}", {}).get("response", {})
        summarize_style_response(int(clock_id), style)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())

    before_custom = find_custom_clocks(before)
    after_custom = find_custom_clocks(after)
    for clock_id in map(str, CUSTOM_CLOCK_IDS):
        diff_values(before_custom.get(clock_id), after_custom.get(clock_id), f"ClockId={clock_id}")

    before_frames = before.get("responses", {}).get("photo_frame_1_100", {}).get("response")
    after_frames = after.get("responses", {}).get("photo_frame_1_100", {}).get("response")
    diff_values(before_frames, after_frames, "PhotoFrame/GetList 1..100")

    for clock_id in map(str, CUSTOM_CLOCK_IDS):
        key = f"clock_style_{clock_id}"
        before_bucket = before.get("responses", {}).get(key)
        after_bucket = after.get("responses", {}).get(key)
        if before_bucket is None and after_bucket is None:
            print(f"Channel/GetClockStyle ClockId={clock_id}: not present in these snapshots")
            continue
        before_style = (before_bucket or {}).get("response")
        after_style = (after_bucket or {}).get("response")
        diff_values(before_style, after_style, f"Channel/GetClockStyle ClockId={clock_id}")
    return 0


def cmd_styles(args: argparse.Namespace) -> int:
    email = args.email or input("Divoom email/username: ").strip()
    if not email:
        print("missing email/username", file=sys.stderr)
        return 2
    password = os.environ.get(args.password_env) if args.password_env else None
    if password is None:
        password = getpass.getpass("Divoom password: ")
    if not password:
        print("missing password", file=sys.stderr)
        return 2

    try:
        auth = login(args, email, password)
    except DivoomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    clock_ids = args.clock_id or list(CUSTOM_CLOCK_IDS)
    print(f"logged in UserId={auth.user_id} Token=<hidden>")
    for clock_id in clock_ids:
        payload = clock_style_payload(args, auth, clock_id)
        response = safe_call(args, auth, "Channel/GetClockStyle", payload)
        summarize_style_response(clock_id, response)
    return 0


def cmd_set_style(args: argparse.Namespace) -> int:
    email = args.email or input("Divoom email/username: ").strip()
    if not email:
        print("missing email/username", file=sys.stderr)
        return 2
    password = os.environ.get(args.password_env) if args.password_env else None
    if password is None:
        password = getpass.getpass("Divoom password: ")
    if not password:
        print("missing password", file=sys.stderr)
        return 2

    try:
        auth = login(args, email, password)
    except DivoomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = set_clock_style_payload(args, auth, args.clock_id, args.style_id)
    response = safe_call(args, auth, "Channel/SetClockStyle", payload)
    print(f"logged in UserId={auth.user_id} Token=<hidden>")
    print(json.dumps(redact(response), indent=2, sort_keys=True, ensure_ascii=False))

    bt_payload = dict(payload)
    bt_payload.pop("Token", None)
    bt_payload.pop("UserId", None)
    print("\nBT relay JSON for immediate MiniToo update:")
    print(json.dumps(bt_payload, separators=(",", ":"), ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump/diff Divoom custom-face frame metadata.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=DEFAULT_BASE_URL)
    common.add_argument("--device-id", type=int, default=DEFAULT_DEVICE_ID, required=DEFAULT_DEVICE_ID is None,
                        help="Divoom cloud DeviceId. Defaults to $DIVOOM_DEVICE_ID.")
    common.add_argument("--country", default=default_country())
    common.add_argument("--language", default=default_language())
    common.add_argument("--timezone", default=default_timezone())
    common.add_argument("--timeout", type=float, default=15.0)

    dump = sub.add_parser("dump", parents=[common], help="Log in and write a redacted metadata snapshot.")
    dump.add_argument("--email", help="Divoom account email/username. If omitted, prompts locally.")
    dump.add_argument("--password-env", help="Read password from this env var instead of prompting.")
    dump.add_argument("--label", default="snapshot", help="Snapshot label used in output filename.")
    dump.add_argument("--out", type=Path, help="Output JSON path.")
    dump.add_argument("--start", type=int, default=1)
    dump.add_argument("--end", type=int, default=100)
    dump.set_defaults(func=cmd_dump)

    styles = sub.add_parser("styles", parents=[common], help="List Channel/GetClockStyle data for custom faces.")
    styles.add_argument("--email", help="Divoom account email/username. If omitted, prompts locally.")
    styles.add_argument("--password-env", help="Read password from this env var instead of prompting.")
    styles.add_argument("--clock-id", type=int, action="append", help="ClockId to inspect. Can be repeated.")
    styles.add_argument("--start", type=int, default=1)
    styles.add_argument("--end", type=int, default=100)
    styles.set_defaults(func=cmd_styles)

    set_style = sub.add_parser("set-style", parents=[common], help="POST Channel/SetClockStyle and print BT relay JSON.")
    set_style.add_argument("--email", help="Divoom account email/username. If omitted, prompts locally.")
    set_style.add_argument("--password-env", help="Read password from this env var instead of prompting.")
    set_style.add_argument("--clock-id", type=int, required=True)
    set_style.add_argument("--style-id", type=int, required=True)
    set_style.add_argument("--start", type=int, default=1)
    set_style.add_argument("--end", type=int, default=100)
    set_style.set_defaults(func=cmd_set_style)

    diff = sub.add_parser("diff", help="Diff two redacted metadata snapshots.")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.set_defaults(func=cmd_diff)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
