#!/bin/bash
# Probe documented opcodes from system_settings/music/sleep/timeplan/light docs
# that haven't been tested yet. Each is a no-arg or benign-arg probe.
# Skips destructive ones (formats, password resets).
set -euo pipefail
cd "$(dirname "$0")"

# (opcode_hex, doc_name, args_hex_optional)
PROBES=(
  # ---- system_settings ----
  "05|Set work mode (BT=0)|00"
  "15|Send sd card status|"
  "52|Set boot gif (default 0)|00"
  "8a|Set poweron channel (0)|00"
  "ab|Set auto power off (off)|00"
  "a7|Set sound ctrl (off)|00"
  "b2|Set low power switch (off)|00"
  "bb|Set poweron voice vol (50)|32"
  # ---- music_play ----
  "07|Get sd music list|"
  "47|App need get music list|"
  # ---- alarm ----
  "82|Set alarm vol ctrl (off)|00"
  "a5|Set alarm listen (off)|00"
  "a6|Set alarm vol (50)|32"
  # ---- sleep ---- DISABLED: bricks the device into a black-screen sleep state
  # that no software command can exit. Only a hardware power-cycle recovers.
  # See FINDINGS.md §9 "DO NOT PROBE". Do NOT re-enable without an exit primitive.
  # "a3|Set sleep scene listen (off)|00"
  # "a4|Set scene vol (50)|32"
  # "ad|Set sleep color (off)|00"
  # "ae|Set sleep light (off)|00"
  # "40|Set sleep auto off (no)|00"
  # ---- light ----
  "45|Set light mode (mode 0)|00"
  "87|Set light phone word attr|00 00 00 00"
)

: > /tmp/divoom-send.log
echo "=== probing ${#PROBES[@]} unprobed opcodes (~1.5s each) ==="
for entry in "${PROBES[@]}"; do
  IFS='|' read -r op name args <<< "$entry"
  echo "--- 0x$op $name (${args:-no-arg}) ---"
  if [ -z "$args" ]; then
    ./dv raw "$op"
  else
    ./dv raw "$op" $args
  fi
  sleep 1.5
done
echo "=== probe done ==="
