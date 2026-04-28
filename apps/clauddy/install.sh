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
Usage: ./install.sh [--mac <bluetooth-mac>] [--device-id <id>] [--email <divoom-login>] [--config <path>]

Uploads the three bundled Clauddy GIFs into the device's custom faces and
writes a local config for set-clauddy-state.sh. Supports any compatible
Divoom display speaker (MiniToo, Tiivoo 2, ...).
EOF
}

choose_detected_mac() {
  local candidates_file="$1"
  local count choice line detected_mac detected_name detected_source

  count="$(grep -c . "$candidates_file" 2>/dev/null || true)"
  case "$count" in
    0)
      clauddy_note "No paired Divoom display device was found automatically."
      return 1
      ;;
    1)
      IFS=$'\t' read -r detected_mac detected_name detected_source < "$candidates_file"
      mac="$detected_mac"
      clauddy_note "Found paired Divoom device: $detected_name ($mac via $detected_source)"
      return 0
      ;;
    *)
      clauddy_note "Found multiple paired Divoom devices:"
      local n=1
      while IFS=$'\t' read -r detected_mac detected_name detected_source; do
        printf '  %s. %s (%s via %s)\n' "$n" "$detected_name" "$detected_mac" "$detected_source" >&2
        n=$((n + 1))
      done < "$candidates_file"
      printf 'Choose device number, or press Enter to type the MAC manually: '
      IFS= read -r choice
      case "$choice" in
        ''|*[!0-9]*)
          return 1
          ;;
        *)
          if [ "$choice" -lt 1 ] || [ "$choice" -gt "$count" ]; then
            clauddy_note "Invalid selection."
            return 1
          fi
          line="$(sed -n "${choice}p" "$candidates_file")"
          IFS=$'\t' read -r detected_mac detected_name detected_source <<EOF_CHOICE
$line
EOF_CHOICE
          mac="$detected_mac"
          clauddy_note "Using paired Divoom device: $detected_name ($mac via $detected_source)"
          return 0
          ;;
      esac
      ;;
  esac
}

mac="${CLAUDDY_MINITOO_MAC:-}"
device_id="${CLAUDDY_DEVICE_ID:-}"
email=""
config="$CLAUDDY_CONFIG_DEFAULT"
detected_config="$CLAUDDY_DETECTED_DEFAULT"
speed_scale="${CLAUDDY_SPEED_SCALE:-1}"
jpeg_quality="${CLAUDDY_JPEG_QUALITY:-95}"
max_payload_bytes="${CLAUDDY_MAX_PAYLOAD_BYTES:-0}"
resample="${CLAUDDY_RESAMPLE:-nearest}"
skip_upload=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mac)
      mac="${2:-}"
      shift 2
      ;;
    --device-id)
      device_id="${2:-}"
      shift 2
      ;;
    --email)
      email="${2:-}"
      shift 2
      ;;
    --config)
      config="${2:-}"
      shift 2
      ;;
    --skip-upload)
      skip_upload=1
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

clauddy_require_macos
clauddy_require_python_pillow
clauddy_ensure_dv_app

cat <<'EOF'
!! Before continuing:
  - Close the official Divoom app on your phone (force-quit, not just background).
  - Disconnect Bluetooth from your Divoom device on your phone (Settings ->
    Bluetooth -> tap the (i) next to the device -> "Disconnect").
  The device accepts only one client at a time. If the phone is still holding
  the Bluetooth channel, this installer cannot connect and will fail.

EOF

read -r -p "Phone disconnected and Divoom app closed? [y/N] " confirm
case "$confirm" in
  y|Y|yes|Yes|YES) ;;
  *) clauddy_die "Aborted. Disconnect the phone and re-run install.sh." ;;
esac

cat <<'EOF'
Divoom account disclaimer:
  - The installer asks for your Divoom login only to discover the three custom
    ClockIds and to persist frame/style settings through Divoom's official API.
  - Your password is read with a hidden prompt and is never written to disk.
  - The auth token returned by Divoom is kept in memory only and is never stored.
  - The local config/cache stores only Bluetooth MAC, DeviceId, ClockIds, and StyleIds.

EOF

if [ -z "$mac" ]; then
  existing_mac="$(clauddy_config_get "$config" CLAUDDY_MINITOO_MAC 2>/dev/null || true)"
  if [ -n "$existing_mac" ]; then
    mac="$existing_mac"
    clauddy_note "Using Divoom Bluetooth MAC from existing config: $mac"
  else
    cached_mac="$(clauddy_config_get "$detected_config" CLAUDDY_MINITOO_MAC 2>/dev/null || true)"
    if [ -n "$cached_mac" ]; then
      mac="$cached_mac"
      clauddy_note "Using Divoom Bluetooth MAC from detection cache: $mac"
    fi
  fi
fi

if [ -z "$mac" ]; then
  clauddy_note "Looking for a paired Divoom display device in macOS Bluetooth..."
  candidates_file="$(mktemp "${TMPDIR:-/tmp}/clauddy-device-macs.XXXXXX")"
  clauddy_detect_minitoo_macs > "$candidates_file" 2>/dev/null || true
  choose_detected_mac "$candidates_file" || true
  rm -f "$candidates_file"
fi

if [ -z "$mac" ]; then
  cat >&2 <<'EOF'
Pair your Divoom display speaker in macOS System Settings > Bluetooth, then
enter its Bluetooth MAC address. The device shows up as "Divoom MiniToo",
"Divoom Tiivoo", or similar.
EOF
  printf 'Bluetooth MAC address: '
  IFS= read -r mac
fi
mac="$(clauddy_normalize_mac "$mac")"
[ -n "$mac" ] || clauddy_die "Bluetooth MAC address is required."
clauddy_is_mac "$mac" || clauddy_die "invalid Bluetooth MAC address: $mac"

if [ -z "$device_id" ]; then
  existing_device_id="$(clauddy_config_get "$config" CLAUDDY_DEVICE_ID 2>/dev/null || true)"
  if [ -n "$existing_device_id" ]; then
    device_id="$existing_device_id"
    clauddy_note "Using DeviceId from existing config: $device_id"
  else
    cached_device_id="$(clauddy_config_get "$detected_config" CLAUDDY_DEVICE_ID 2>/dev/null || true)"
    if [ -n "$cached_device_id" ]; then
      device_id="$cached_device_id"
      clauddy_note "Using DeviceId from detection cache: $device_id"
    fi
  fi
fi
[ -z "$device_id" ] || clauddy_is_device_id "$device_id" || clauddy_die "invalid DeviceId: $device_id"

clauddy_note "Checking Bluetooth connection and trying to detect DeviceId..."
detected_device_id=""
if ! detected_device_id="$(clauddy_check_connection "$mac")"; then
  clauddy_die "Bluetooth connection check failed. Connect the device, then re-run install.sh."
fi

if [ -n "$detected_device_id" ] && ! clauddy_is_device_id "$detected_device_id"; then
  clauddy_note "Ignoring unexpected Bluetooth DeviceId response: $detected_device_id"
  detected_device_id=""
fi

if [ -z "$device_id" ] && [ -n "$detected_device_id" ]; then
  device_id="$detected_device_id"
  clauddy_note "Detected DeviceId=$device_id"
elif [ -n "$device_id" ] && [ -n "$detected_device_id" ] && [ "$device_id" != "$detected_device_id" ]; then
  clauddy_note "Using provided DeviceId=$device_id (Bluetooth reported $detected_device_id)."
fi

if [ -z "$device_id" ]; then
  cat >&2 <<'EOF'
Could not auto-detect DeviceId over Bluetooth.
If you have a previous Clauddy config, use that CLAUDDY_DEVICE_ID value; otherwise
make sure the device is awake, disconnected from the phone app, and re-run.
EOF
  printf 'DeviceId: '
  IFS= read -r device_id
fi
[ -n "$device_id" ] || clauddy_die "DeviceId is required. Re-run after the device is connected over Bluetooth."
clauddy_is_device_id "$device_id" || clauddy_die "invalid DeviceId: $device_id"

if clauddy_write_detected_config "$detected_config" "$mac" "$device_id"; then
  clauddy_note "Cached Bluetooth metadata in $detected_config (no credentials)."
else
  clauddy_note "Warning: could not write Bluetooth detection cache: $detected_config"
fi

cloud_args=(setup --config "$config" --mac "$mac" --device-id "$device_id")
if [ -n "$email" ]; then
  cloud_args+=(--email "$email")
fi
python3 "$SCRIPT_DIR/tools/clauddy-cloud.py" "${cloud_args[@]}"

clauddy_load_config "$config"

if [ "$skip_upload" -eq 0 ]; then
  clauddy_note "Uploading three custom faces. This usually takes about 1-2 minutes."

  tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/clauddy-install.XXXXXX")"
  cleanup() {
    clauddy_stop_daemon
    rm -rf "$tmpdir"
  }
  trap cleanup EXIT

  timestamp="$(date +%s)"
  for state in chilling working alerting; do
    gif="$SCRIPT_DIR/assets/$state.gif"
    raw="$tmpdir/$state.raw"
    file_id="clauddy-$state-$timestamp"
    clock_id="$(clauddy_state_clock_id "$state")"
    page_index="$(clauddy_state_page_index "$state")"
    style_id="$(clauddy_state_style_id "$state")"
    state_speed_ms=""
    case "$state" in
      chilling) state_speed_ms="${CLAUDDY_SPEED_CHILLING:-}" ;;
      working) state_speed_ms="${CLAUDDY_SPEED_WORKING:-}" ;;
      alerting) state_speed_ms="${CLAUDDY_SPEED_ALERTING:-}" ;;
    esac

    [ -f "$gif" ] || clauddy_die "missing bundled GIF: $gif"
    encode_args=(
      "$SCRIPT_DIR/tools/encode-custom-raw.py"
      --input "$gif"
      --output "$raw"
      --file-id "$file_id"
      --quality "$jpeg_quality"
      --fit cover
      --resample "$resample"
      --max-payload-bytes "$max_payload_bytes"
      --speed-scale "$speed_scale"
    )
    if [ -n "$state_speed_ms" ]; then
      encode_args+=(--speed-ms "$state_speed_ms")
    fi
    python3 "${encode_args[@]}"

    clauddy_upload_custom "$state" "$CLAUDDY_MINITOO_MAC" "$file_id" "$raw" "$page_index" "$clock_id" "$style_id" "$CLAUDDY_DEVICE_ID" 5
  done
fi

"$SCRIPT_DIR/set-clauddy-state.sh" chilling --config "$config" >/dev/null

cat <<EOF

Clauddy install complete.

Config:
  $config

Try:
  $SCRIPT_DIR/set-clauddy-state.sh working --config "$config"
  $SCRIPT_DIR/set-clauddy-state.sh chilling --config "$config"
  $SCRIPT_DIR/set-clauddy-state.sh alerting --config "$config"

Add to PATH:
  mkdir -p "\$HOME/.local/bin"
  ln -sf "$SCRIPT_DIR/set-clauddy-state.sh" "\$HOME/.local/bin/set-clauddy-state.sh"
  export PATH="\$HOME/.local/bin:\$PATH"

Then call from anywhere:
  set-clauddy-state.sh working
EOF
