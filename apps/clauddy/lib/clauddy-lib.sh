#!/usr/bin/env bash

clauddy_resolve_path() {
  local source="$1"
  local dir
  while [ -h "$source" ]; do
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    case "$source" in
      /*) ;;
      *) source="$dir/$source" ;;
    esac
  done
  cd -P "$(dirname "$source")" && pwd
}

CLAUDDY_LIB_DIR="$(clauddy_resolve_path "${BASH_SOURCE[0]}")"
CLAUDDY_PACKAGE_DIR="$(cd "$CLAUDDY_LIB_DIR/.." && pwd)"
CLAUDDY_REPO_ROOT="$(cd "$CLAUDDY_PACKAGE_DIR/../.." && pwd)"
CLAUDDY_CORE_DIR_DEFAULT="$CLAUDDY_REPO_ROOT/core"
CLAUDDY_CONFIG_DEFAULT="${CLAUDDY_CONFIG:-$HOME/.clauddy/config}"
CLAUDDY_DETECTED_DEFAULT="${CLAUDDY_DETECTED:-$HOME/.clauddy/detected}"
CLAUDDY_FIFO="${DIVOOM_FIFO:-/tmp/divoom.fifo}"
CLAUDDY_LOG="${DIVOOM_LOG:-/tmp/divoom-send.log}"

clauddy_die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

clauddy_note() {
  printf '%s\n' "$*" >&2
}

clauddy_normalize_mac() {
  printf '%s\n' "${1//-/:}" | tr '[:lower:]' '[:upper:]'
}

clauddy_is_mac() {
  [[ "$1" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]
}

clauddy_is_device_id() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

clauddy_config_get() {
  local config="$1"
  local key="$2"
  [ -f "$config" ] || return 1
  (
    set +u
    # shellcheck source=/dev/null
    . "$config" >/dev/null 2>&1 || exit 1
    case "$key" in
      CLAUDDY_MINITOO_MAC) printf '%s\n' "${CLAUDDY_MINITOO_MAC:-}" ;;
      CLAUDDY_DEVICE_ID) printf '%s\n' "${CLAUDDY_DEVICE_ID:-}" ;;
      *) exit 1 ;;
    esac
  )
}

clauddy_write_detected_config() {
  local config="$1"
  local mac="$2"
  local device_id="$3"

  mkdir -p "$(dirname "$config")" || return 1
  {
    printf '# Clauddy Bluetooth detection cache.\n'
    printf '# Contains no Divoom password, auth token, or account secret.\n'
    [ -n "$mac" ] && printf 'CLAUDDY_MINITOO_MAC=%q\n' "$mac"
    [ -n "$device_id" ] && printf 'CLAUDDY_DEVICE_ID=%q\n' "$device_id"
  } > "$config"
  chmod 600 "$config"
}

clauddy_detect_minitoo_macs() {
  python3 "$CLAUDDY_PACKAGE_DIR/tools/detect-minitoo-mac.py"
}

clauddy_require_macos() {
  [ "$(uname -s)" = "Darwin" ] || clauddy_die "Clauddy currently supports macOS only."
}

clauddy_require_python_pillow() {
  command -v python3 >/dev/null 2>&1 || clauddy_die "python3 is required."
  if ! python3 - <<'PY' >/dev/null 2>&1
from PIL import Image
PY
  then
    clauddy_die "Python Pillow is required. Install it with: python3 -m pip install Pillow"
  fi
}

clauddy_core_dir() {
  printf '%s\n' "${CLAUDDY_CORE_DIR:-$CLAUDDY_CORE_DIR_DEFAULT}"
}

clauddy_dv() {
  printf '%s/dv\n' "$(clauddy_core_dir)"
}

clauddy_require_dv() {
  local dv
  dv="$(clauddy_dv)"
  [ -x "$dv" ] || clauddy_die "missing Divoom Bluetooth helper: $dv"
}

clauddy_ensure_dv_app() {
  local dir
  dir="$(clauddy_core_dir)"
  clauddy_require_dv
  if [ ! -x "$dir/divoom-send.app/Contents/MacOS/divoom-send" ]; then
    clauddy_note "Building macOS Bluetooth helper..."
    (cd "$dir" && ./build.sh) || clauddy_die "failed to build divoom-send.app. Xcode command line tools may be missing."
  fi
}

clauddy_daemon_running() {
  [ -p "$CLAUDDY_FIFO" ] && pgrep -f "divoom-send" >/dev/null 2>&1
}

clauddy_clear_stale_fifo() {
  if [ -p "$CLAUDDY_FIFO" ] && ! pgrep -f "divoom-send" >/dev/null 2>&1; then
    rm -f "$CLAUDDY_FIFO"
  fi
}

clauddy_bluetooth_help() {
  cat >&2 <<EOF
Could not connect to the Divoom display device over Bluetooth.

Check:
  1. Device is powered on and awake.
  2. It is paired in macOS System Settings > Bluetooth.
  3. The Divoom phone app is not currently connected to the device.
  4. The Bluetooth MAC address in the Clauddy config is correct.

Recent helper log:
EOF
  tail -n 40 "$CLAUDDY_LOG" >&2 2>/dev/null || true
}

clauddy_start_daemon() {
  local mac="$1"
  local dv
  dv="$(clauddy_dv)"
  clauddy_clear_stale_fifo
  if clauddy_daemon_running; then
    return 0
  fi
  if ! "$dv" start "$mac" >/tmp/clauddy-dv-start.out 2>&1; then
    cat /tmp/clauddy-dv-start.out >&2 2>/dev/null || true
    clauddy_bluetooth_help
    return 1
  fi
}

clauddy_stop_daemon() {
  local dv
  dv="$(clauddy_dv)"
  "$dv" stop >/dev/null 2>&1 || true
}

clauddy_check_connection() {
  local mac="$1"
  local dv detected
  dv="$(clauddy_dv)"

  clauddy_stop_daemon
  if ! clauddy_start_daemon "$mac"; then
    return 1
  fi
  "$dv" raw bd 2b 00 >/dev/null 2>&1 || true
  sleep 1
  detected="$(python3 "$CLAUDDY_PACKAGE_DIR/tools/parse-device-id-log.py" "$CLAUDDY_LOG" 2>/dev/null || true)"
  clauddy_stop_daemon
  printf '%s\n' "$detected"
}

clauddy_load_config() {
  local config="$1"
  [ -f "$config" ] || clauddy_die "missing config: $config. Run install.sh first."
  # shellcheck source=/dev/null
  . "$config"
  : "${CLAUDDY_MINITOO_MAC:?missing CLAUDDY_MINITOO_MAC in config}"
  : "${CLAUDDY_DEVICE_ID:?missing CLAUDDY_DEVICE_ID in config}"
  : "${CLAUDDY_CLOCK_CHILLING:?missing CLAUDDY_CLOCK_CHILLING in config}"
  : "${CLAUDDY_CLOCK_WORKING:?missing CLAUDDY_CLOCK_WORKING in config}"
  : "${CLAUDDY_CLOCK_ALERTING:?missing CLAUDDY_CLOCK_ALERTING in config}"
}

clauddy_state_clock_id() {
  case "$1" in
    chilling) printf '%s\n' "$CLAUDDY_CLOCK_CHILLING" ;;
    working) printf '%s\n' "$CLAUDDY_CLOCK_WORKING" ;;
    alerting) printf '%s\n' "$CLAUDDY_CLOCK_ALERTING" ;;
    *) return 1 ;;
  esac
}

clauddy_state_page_index() {
  case "$1" in
    chilling) printf '%s\n' "${CLAUDDY_PAGE_CHILLING:-0}" ;;
    working) printf '%s\n' "${CLAUDDY_PAGE_WORKING:-1}" ;;
    alerting) printf '%s\n' "${CLAUDDY_PAGE_ALERTING:-2}" ;;
    *) return 1 ;;
  esac
}

clauddy_state_style_id() {
  case "$1" in
    chilling) printf '%s\n' "${CLAUDDY_STYLE_CHILLING:-798}" ;;
    working) printf '%s\n' "${CLAUDDY_STYLE_WORKING:-828}" ;;
    alerting) printf '%s\n' "${CLAUDDY_STYLE_ALERTING:-798}" ;;
    *) return 1 ;;
  esac
}

clauddy_selector_json() {
  local clock_id="$1"
  local device_id="$2"
  printf '{"Command":"Channel/SetClockSelectId","ClockId":%s,"DeviceId":%s,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}' "$clock_id" "$device_id"
}

clauddy_clean_json() {
  local page_index="$1"
  local clock_id="$2"
  local device_id="$3"
  printf '{"Command":"Channel/CleanCustom","CustomPageIndex":%s,"ClockId":%s,"ParentClockId":0,"ParentItemId":"","DeviceId":%s}' "$page_index" "$clock_id" "$device_id"
}

clauddy_set_custom_json() {
  local page_index="$1"
  local file_id="$2"
  local clock_id="$3"
  local device_id="$4"
  printf '{"Command":"Channel/SetCustom","CustomPageIndex":%s,"CustomId":0,"FileId":"%s","ClockId":%s,"ParentClockId":0,"ParentItemId":"","LcdIndependence":0,"LcdIndex":0,"Language":"en","DeviceId":%s}' "$page_index" "$file_id" "$clock_id" "$device_id"
}

clauddy_style_json() {
  local clock_id="$1"
  local style_id="$2"
  local device_id="$3"
  printf '{"Command":"Channel/SetClockStyle","ClockId":%s,"StyleId":%s,"DeviceId":%s,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}' "$clock_id" "$style_id" "$device_id"
}

clauddy_send_json() {
  local json="$1"
  local dv
  dv="$(clauddy_dv)"
  if ! clauddy_daemon_running; then
    clauddy_die "Bluetooth helper is not running."
  fi
  "$dv" json "$json" || clauddy_die "failed to send Bluetooth JSON command."
}

clauddy_wait_for_upload_ack() {
  local timeout="${1:-30}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if grep -q "bd 55 13 01 05 00" "$CLAUDDY_LOG" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

clauddy_start_custom_daemon() {
  local mac="$1"
  local file_id="$2"
  local rawfile="$3"
  local device_id="$4"
  local delay_ms="$5"
  local dv
  dv="$(clauddy_dv)"

  clauddy_stop_daemon
  clauddy_clear_stale_fifo
  if ! "$dv" start-custom "$mac" "$file_id" "$rawfile" "$device_id" "$delay_ms" >/tmp/clauddy-dv-start-custom.out 2>&1; then
    cat /tmp/clauddy-dv-start-custom.out >&2 2>/dev/null || true
    clauddy_bluetooth_help
    return 1
  fi
}

clauddy_upload_custom() {
  local state="$1"
  local mac="$2"
  local file_id="$3"
  local rawfile="$4"
  local page_index="$5"
  local clock_id="$6"
  local style_id="$7"
  local device_id="$8"
  local delay_ms="${9:-5}"

  clauddy_note "Uploading $state to CustomPageIndex=$page_index ClockId=$clock_id..."
  clauddy_start_custom_daemon "$mac" "$file_id" "$rawfile" "$device_id" "$delay_ms" || return 1
  # The MiniToo upload handshake is tied to the custom page index. In live
  # tests it requested file chunks when CleanCustom/SetCustom used ClockId=0;
  # the real custom ClockId is still used below for style and runtime selection.
  clauddy_send_json "$(clauddy_clean_json "$page_index" 0 "$device_id")"
  clauddy_send_json "$(clauddy_set_custom_json "$page_index" "$file_id" 0 "$device_id")"
  if ! clauddy_wait_for_upload_ack 45; then
    clauddy_bluetooth_help
    clauddy_stop_daemon
    clauddy_die "timed out waiting for device to ACK $state upload."
  fi
  clauddy_send_json "$(clauddy_style_json "$clock_id" "$style_id" "$device_id")"
  clauddy_stop_daemon
}
