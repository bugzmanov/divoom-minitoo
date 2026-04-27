#!/bin/bash
# Probe more documented opcodes from light.md / game.md / etc.
# Focus on "user-defined picture" family that *might* give us a writeable storage slot.
set -euo pipefail
cd "$(dirname "$0")"

# (opcode_hex, doc_name, args_hex)
PROBES=(
  "b1|Set user gif (CW=0, type=0 normal)|00 00"
  "b6|Modify user gif items (query count)|00"
  "b7|Set rhythm gif (Pos=0,Tol=0,Id=0)|00 00 00"
  "1b|App send eq gif (no-arg)|"
  "34|Sand paint ctrl (off)|00"
  "35|Pic scan ctrl (off)|00"
  "3a|Drawing mul pad ctrl (off)|00"
  "3b|Drawing big pad ctrl (off)|00"
  "58|Drawing pad ctrl (off)|00"
  "5a|Drawing pad exit|"
  "5b|Drawing mul encode single pic (no-arg)|"
  "5c|Drawing mul encode pic (no-arg)|"
)

: > /tmp/divoom-send.log
echo "=== probing ${#PROBES[@]} unprobed light/draw opcodes (~1.5s each) ==="
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
