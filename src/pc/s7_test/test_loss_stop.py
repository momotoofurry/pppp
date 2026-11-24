# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""Fault injection (report 35.85): packets lost while a direction is held. The PC build of rt_lda.c on the stop-event
stream (run_stop: report 3); then the same stream with 5 sample packets dropped 1 s after a direction was established
and held >= 2 s. Before the fix the latch was reset silently (the arm kept the direction until the next event); now a
stop must follow the gap at once."""
import ctypes
import struct
import sys

sys.path.insert(0, '/work/src')
sys.path.insert(0, '/work/src/pc')
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402

lib = ctypes.CDLL('/work/build/c/librtl9.so')
lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
lib.rtl_idle.restype = None
raw = open('/s7/run_stop/bridge_out.bin', 'rb').read()
pk = PR.Decoder().feed(raw)


def run(drop=()):
    out, cur = [], [0]
    dec = PR.Decoder()

    def tx(p, n):
        for t, _, q in dec.feed(ctypes.string_at(p, n)):
            if t == PR.COMMAND:
                w, _, cmd, cls, _ = struct.unpack('<IIBBH', q[:12])
                out.append((cur[0], w, cmd, cls))
            elif t == PR.STATUS and q[0] == 3:
                out.append((cur[0], None, 'lost', struct.unpack('<i', q[4:8])[0]))
    cb = R.TX(tx)
    lib.rtl_init(ctypes.byref(R.Config(cb, R.NOW(0), 9, 0, 0, 3)))
    for i, (t, seq, p) in enumerate(pk):
        if i in drop:
            continue
        cur[0] = i
        b = PR.build(t, seq, p)
        lib.rtl_rx(ctypes.c_char_p(b), len(b))
        if t == PR.CONTROL:
            lib.rtl_idle()
    return out


base = run()
ev = [e for e in base if e[2] != 'lost']
pick = None
for a, b in zip(ev, ev[1:]):
    if a[2] != 0 and b[0] - a[0] >= 200:            # a direction held >= 2 s (10 ms per packet)
        pick = a
        break
assert pick, 'no long hold found'
drop = set(range(pick[0] + 100, pick[0] + 105))
after = run(drop)
nxt = [e for e in after if e[0] > pick[0] + 99]
print(f'held command {pick[2]} (class {pick[3]}) from packet {pick[0]}; dropped packets {min(drop)}-{max(drop)}')
print('events right after the gap:', nxt[:3])
first = nxt[0] if nxt else None
ok = first is not None and first[2] == 'lost' and len(nxt) > 1 and nxt[1][2] == 0 and nxt[1][0] == first[0]
print('stop sent with the loss report, in the same packet:', ok)
base_next = [e for e in ev if e[0] > pick[0]][0]
print(f'without the fix the arm would have kept the direction until packet {base_next[0]} '
      f'({(base_next[0] - pick[0] - 105) * 10} ms after the gap)')
