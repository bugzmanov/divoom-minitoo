#!/usr/bin/env bash
# Multi-Claude-aware wrapper around set-clauddy-state.sh, intended for use as
# a Claude Code hook command. The wrapper coordinates several concurrent
# Claude sessions so a low-severity event (chilling) from one session does not
# clobber a high-severity event (alerting) from another. State is shared
# through a single file under /tmp; severity ranks chilling < working < alerting.
#
# Tunables (env):
#   CLAUDDY_HOOK_STATE_FILE  shared state file (default /tmp/clauddy-hook-state)
#   CLAUDDY_ALERT_HOLD       seconds an "alerting" face is held against downgrade (default 5)
#   CLAUDDY_WORK_HOLD        seconds a "working" face is held against downgrade (default 2)
set -u

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

state="${1:-}"
case "$state" in
  chilling|working|alerting) ;;
  *)
    printf 'usage: clauddy-hook.sh <chilling|working|alerting>\n' >&2
    exit 64
    ;;
esac

SCRIPT_DIR="$(resolve_script_dir "$0")"
STATE_FILE="${CLAUDDY_HOOK_STATE_FILE:-/tmp/clauddy-hook-state}"
ALERT_HOLD="${CLAUDDY_ALERT_HOLD:-5}"
WORK_HOLD="${CLAUDDY_WORK_HOLD:-2}"

severity() {
  case "$1" in
    chilling) printf 0 ;;
    working)  printf 1 ;;
    alerting) printf 2 ;;
  esac
}

now="$(date +%s)"
new_sev="$(severity "$state")"

cur_state=""
cur_ts=0
if [ -r "$STATE_FILE" ]; then
  read -r cur_state cur_ts < "$STATE_FILE" 2>/dev/null || { cur_state=""; cur_ts=0; }
fi
case "$cur_state" in
  chilling|working|alerting) ;;
  *) cur_state="" ;;
esac
[[ "$cur_ts" =~ ^[0-9]+$ ]] || cur_ts=0

write_state() {
  local tmp="$STATE_FILE.tmp.$$"
  if printf '%s %s\n' "$state" "$now" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$STATE_FILE" 2>/dev/null || rm -f "$tmp"
  fi
}

# Same face already showing — refresh ts and skip the Bluetooth round-trip.
if [ "$cur_state" = "$state" ]; then
  write_state
  exit 0
fi

# Hold a higher-severity face against a quick downgrade from a different session.
if [ -n "$cur_state" ]; then
  cur_sev="$(severity "$cur_state")"
  if [ "$new_sev" -lt "$cur_sev" ]; then
    age=$(( now - cur_ts ))
    hold="$WORK_HOLD"
    [ "$cur_state" = "alerting" ] && hold="$ALERT_HOLD"
    if [ "$age" -lt "$hold" ]; then
      # Defer the downgrade so the face still clears once the hold expires,
      # even if no further hook fires from any session.
      remaining=$(( hold - age + 1 ))
      ( sleep "$remaining"; exec "$0" "$state" ) >/dev/null 2>&1 &
      exit 0
    fi
  fi
fi

write_state
"$SCRIPT_DIR/set-clauddy-state.sh" "$state" >/dev/null 2>&1 &
exit 0
