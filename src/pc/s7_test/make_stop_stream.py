# report 35.82-35.83 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""run_stop/bridge_out.bin = run/bridge_out.bin with SET_REPORT 1 -> 3 (stop events on, report 35.82); same seq / CRC
rule (protocol.py build)."""
import os
import sys

sys.path.insert(0, r'\\wsl.localhost\Ubuntu-22.04\home\momo1234\model-leaf\src\pc')
import protocol as PR  # noqa: E402

d = os.path.dirname(os.path.abspath(__file__))
raw = open(os.path.join(d, 'run', 'bridge_out.bin'), 'rb').read()
out, n = bytearray(), 0
for t, seq, p in PR.Decoder().feed(raw):
    if t == PR.CONTROL and p[0] == 6:
        p = bytes([6, 3])
        n += 1
    out += PR.build(t, seq, p)
os.makedirs(os.path.join(d, 'run_stop'), exist_ok=True)
open(os.path.join(d, 'run_stop', 'bridge_out.bin'), 'wb').write(bytes(out))
open(os.path.join(d, 'run_stop', 'cues.csv'), 'w').write(open(os.path.join(d, 'run', 'cues.csv')).read())
print(f'{len(out)} bytes, SET_REPORT packets changed: {n}, same length as the original: {len(out) == len(raw)}')
