#!/usr/bin/env python3
"""Parse /tmp/divoom-send.log, pair each tx opcode with the rx frames that
followed before the next tx, and extract any JSON "Command" values.
Prints a table of opcode -> device response command(s), highlighting novel ones."""
import re, sys, pathlib

LOG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/divoom-send.log")
KNOWN = {"Channel/SetBrightness", "Tomato/FocusAction"}

tx_rx = []  # list of (opcode_hex, [rx_hex_strings])
current = None

tx_re = re.compile(r"tx\[\d+\]:\s*([0-9a-f ]+)")
rx_re = re.compile(r"delegate: rx\[\d+\]:\s*([0-9a-f ]+)")

for line in LOG.read_text(errors="replace").splitlines():
    line = line.strip()
    if m := tx_re.search(line):
        parts = m.group(1).split()
        if len(parts) >= 4:
            opcode = parts[3]  # 01 [len_lo] [len_hi] [opcode] ...
            current = (opcode, [])
            tx_rx.append(current)
    elif m := rx_re.search(line):
        if current is not None:
            current[1].append(m.group(1).strip())

cmd_re = re.compile(rb'"Command"\s*:\s*"([^"]+)"')
opcode_cmds: dict[str, set[str]] = {}

for opcode, rx_list in tx_rx:
    for hex_str in rx_list:
        try:
            data = bytes.fromhex(hex_str.replace(" ", ""))
        except ValueError:
            continue
        for m in cmd_re.finditer(data):
            opcode_cmds.setdefault(opcode, set()).add(m.group(1).decode())

print(f"{'opcode':<8} {'device response Command(s)':<40} status")
print(f"{'-'*8} {'-'*40} {'-'*6}")
for op in sorted(opcode_cmds):
    cmds = opcode_cmds[op]
    new = cmds - KNOWN
    marker = "*** NEW ***" if new else "(known)"
    print(f"  0x{op:<5} {', '.join(sorted(cmds)):<40} {marker}")

print()
print(f"total tx frames analyzed: {len(tx_rx)}")
print(f"opcodes with JSON Command responses: {len(opcode_cmds)}")
novel = {op for op, cmds in opcode_cmds.items() if cmds - KNOWN}
if novel:
    print(f"opcodes with NOVEL responses: {sorted(novel)}")
else:
    print("no novel Command responses discovered")
