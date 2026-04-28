#!/usr/bin/env bash
set -euo pipefail

resolve_script_dir() {
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

SCRIPT_DIR="$(resolve_script_dir "$0")"
# shellcheck source=lib/clauddy-lib.sh
. "$SCRIPT_DIR/lib/clauddy-lib.sh"

usage() {
  cat <<EOF
Usage: set-clauddy-state.sh <working|chilling|alerting> [--config <path>] [--stop-after]

Switches the Divoom display device to a preloaded Clauddy custom face.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

state="${1:-}"
if [ -z "$state" ]; then
  usage >&2
  exit 64
fi
shift

config="$CLAUDDY_CONFIG_DEFAULT"
stop_after=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --config)
      config="${2:-}"
      shift 2
      ;;
    --stop-after)
      stop_after=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
done

case "$state" in
  working|chilling|alerting) ;;
  *)
    clauddy_die "unknown state '$state'. Expected: working, chilling, alerting."
    ;;
esac

clauddy_require_macos
clauddy_ensure_dv_app
clauddy_load_config "$config"

started=0
if ! clauddy_daemon_running; then
  started=1
  clauddy_note "Bluetooth helper is not running; starting it for device at $CLAUDDY_MINITOO_MAC..."
  clauddy_start_daemon "$CLAUDDY_MINITOO_MAC" || exit 1
fi

clock_id="$(clauddy_state_clock_id "$state")"
clauddy_send_json "$(clauddy_selector_json "$clock_id" "$CLAUDDY_DEVICE_ID")"
printf 'clauddy state: %s (ClockId=%s)\n' "$state" "$clock_id"

if [ "$stop_after" -eq 1 ]; then
  clauddy_stop_daemon
elif [ "$started" -eq 1 ]; then
  clauddy_note "Bluetooth helper left running for faster future switches. Stop it with: $(clauddy_dv) stop"
fi
