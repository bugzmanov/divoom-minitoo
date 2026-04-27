#!/usr/bin/env python3
"""Parse /tmp/divoom-send.log after a probe-gets.sh run.
For each TX, find the RX frames that followed (before the next TX),
filter out keepalives, and print which opcodes got real responses."""
import re

with open('/tmp/divoom-send.log', 'rb') as f:
    log = f.read().decode('utf-8', errors='replace').replace('\x00', '')

events = []   # list of ('tx', opcode, hex) or ('rx', payload_hex)
for line in log.splitlines():
    m = re.match(r'tx\[\d+\]:\s*([0-9a-f ]+)', line)
    if m:
        bytes_hex = m.group(1).split()
        if len(bytes_hex) >= 4:
            opcode = bytes_hex[3]
            events.append(('tx', opcode, ' '.join(bytes_hex)))
        continue
    m = re.match(r'delegate: rx\[\d+\]:\s*([0-9a-f ]+)', line)
    if m:
        bytes_hex = m.group(1).split()
        events.append(('rx', None, ' '.join(bytes_hex)))

KEEPALIVE_SIG = '04 f7 55 4e 6f 62'   # the standard 17-byte keepalive
TOMATO_SIG    = '54 6f 6d 61 74 6f 2f 46 6f 63 75 73'   # "Tomato/Focus"

print(f"{'opcode':<8} {'response':<10} {'rx body':<60}")
print("-" * 80)

current_tx = None
rx_for_tx = []

def flush(opcode, rx_list):
    if opcode is None: return
    real = []
    for r in rx_list:
        if KEEPALIVE_SIG in r: continue
        if TOMATO_SIG in r: continue
        real.append(r)
    if real:
        for r in real:
            preview = r[:60] + ('…' if len(r) > 60 else '')
            print(f"  0x{opcode:<5} RESPONDED  {preview}")
    else:
        print(f"  0x{opcode:<5} silent     ({len(rx_list)} keepalive/noise)")

for kind, op, payload in events:
    if kind == 'tx':
        flush(current_tx, rx_for_tx)
        current_tx = op
        rx_for_tx = []
    else:
        rx_for_tx.append(payload)
flush(current_tx, rx_for_tx)
