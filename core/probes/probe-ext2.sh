#!/bin/bash
# Continuation of probe-ext.sh past 0x3a. Tests undocumented EXT opcodes
# 0x3b..0x4f under the 0xbd wrapper with arg 00. Pure RESPONDED-or-silent
# discovery; no destructive args.
set -euo pipefail
cd "$(dirname "$0")"

EXTS=( 3b 3c 3d 3e 3f 40 41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e 4f )

: > /tmp/divoom-send.log
echo "=== probing ${#EXTS[@]} EXT opcodes 0xbd 0x3b..0x4f (~1.0s each) ==="
for op in "${EXTS[@]}"; do
  echo "--- ext 0x$op ---"
  ./dv raw bd "$op" 00
  sleep 1.0
done
echo "=== probe done ==="
