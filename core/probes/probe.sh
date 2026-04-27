#!/bin/bash
# Opcode probe. Sends every opcode 0x00..0xFF with a minimal arg and logs
# responses. Runs through the daemon so there's only ONE BT connection.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOG=/tmp/divoom-send.log
FIFO=/tmp/divoom.fifo

if [ ! -p "$FIFO" ]; then
  echo "daemon not running. Start it first: ./dv start <MAC>"
  exit 1
fi

START_OP="${1:-0}"
END_OP="${2:-255}"
ARG="${3:-01}"
DELAY="${4:-0.8}"

echo "probing opcodes 0x$(printf %02x $START_OP)..0x$(printf %02x $END_OP) with arg 0x$ARG, $DELAY s each"
echo "log so far: $(wc -l < "$LOG") lines"

for op in $(seq "$START_OP" "$END_OP"); do
  op_hex=$(printf '%02x' $op)
  echo "raw $op_hex $ARG" > "$FIFO"
  sleep "$DELAY"
done

echo "done. log now: $(wc -l < "$LOG") lines"
