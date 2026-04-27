#!/bin/bash
# Probe documented SET commands that should be safe (no audio, no destructive).
# Each probe sends a no-side-effect or easily-revertable value; correlate
# responses via parse-probe.py afterward.
set -euo pipefail

cd "$(dirname "$0")"

# (opcode_hex, doc_name, args_hex)
PROBES=(
  "16|Set gif speed (100ms)|00 64"
  "2b|Set temp type (Celsius)|00"
  "2c|Set hour type (24h)|01"
  "32|Set lightness (75)|4b"
  "74|Set brightness (75)|4b"
  "5d|Send net temp (room=22)|00 16"
  "5e|Send net temp disp|00"
  "5f|Send current temp|16 01"
  "83|Set song display (off)|00"
)

: > /tmp/divoom-send.log
echo "=== probing ${#PROBES[@]} safe SET opcodes (~1.2s each) ==="
for entry in "${PROBES[@]}"; do
  IFS='|' read -r op name args <<< "$entry"
  echo "--- 0x$op $name ($args) ---"
  ./dv raw "$op" $args
  sleep 1.2
done
echo "=== probe done ==="