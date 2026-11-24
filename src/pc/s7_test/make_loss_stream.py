# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""run_loss/bridge_out.bin (report 35.85): the stop-event stream (run_stop) with packets 19920-19924 (5 sample packets,
1 s into a held command) left out, as a lost stretch on the serial link."""
import os
import sys

sys.path.insert(0, r'\\wsl.localhost\Ubuntu-22.04\home\momo1234\model-leaf\src\pc')
import protocol as PR  # noqa: E402

d = os.path.dirname(os.path.abspath(__file__))
raw = open(os.path.join(d, 'run_stop', 'bridge_out.bin'), 'rb').read()
pk = PR.Decoder().feed(raw)
drop = set(range(19920, 19925))
assert all(pk[i][0] == PR.SAMPLES for i in drop)
out = b''.join(PR.build(t, s, p) for i, (t, s, p) in enumerate(pk) if i not in drop)
os.makedirs(os.path.join(d, 'run_loss'), exist_ok=True)
open(os.path.join(d, 'run_loss', 'bridge_out.bin'), 'wb').write(out)
print(f'dropped {len(drop)} sample packets; {len(out)} bytes')
