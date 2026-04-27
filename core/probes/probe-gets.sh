#!/bin/bash
# Methodically probe all documented GET opcodes on Minitoo.
# For each opcode we send the no-arg / minimal-arg form, wait for response,
# and let the caller check the log for non-keepalive RX frames.
set -euo pipefail

cd "$(dirname "$0")"

# (opcode_hex, doc_name, args_hex_optional)
PROBES=(
  "06|get sd play name|"
  "09|Get vol|"
  "0b|Get play status|"
  "13|Get working mode|"
  "42|Get alarm time|"
  "46|Get light mode|"
  "53|Get memorial time|"
  "59|Get device temp|"
  "71|Get tool info|"
  "73|Get net temp disp|"
  "76|Get device name|"
  "7d|Get sd music list total num|"
  "a2|Get sleep scene|"
  "a8|Get sound ctrl|"
  "ac|Get auto power off|"
  "b3|Get low power switch|"
  "b4|Get sd music info|"
  "8e|App get user define info|00"
)

: > /tmp/divoom-send.log
echo "=== probing ${#PROBES[@]} GET opcodes (no-arg form, ~1.2s each) ==="
for entry in "${PROBES[@]}"; do
  IFS='|' read -r op name args <<< "$entry"
  marker="--- 0x$op $name ---"
  echo "$marker" | tee -a /tmp/probe-marker.txt
  # write a marker into the log via the daemon for time-correlation
  if [ -z "$args" ]; then
    ./dv raw "$op"
  else
    ./dv raw "$op" $args
  fi
  sleep 1.2
done
echo "=== probe done ==="