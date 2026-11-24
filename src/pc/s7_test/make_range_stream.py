# report 35.82-35.83 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""run_range/bridge_out.bin (report 35.83): the stop-event stream (run_stop) with two RTL_LABEL_RANGE packets inserted
after 60 % of its sample packets: windows [W-200, W-101] as class 0 and [W-100, W-1] as Rest, W = the windows the
firmware has made by then (from the PC build, counted from init like the board after a reset). Run in the container."""
import ctypes
import os
import struct
import sys

sys.path.insert(0, '/work/src')
sys.path.insert(0, '/work/src/pc')
import check_rt_lda as R  # noqa: E402
import protocol as PR  # noqa: E402

LIB9 = '/work/build/c/librtl9.so'
d = '/s7'
raw = open(os.path.join(d, 'run_stop', 'bridge_out.bin'), 'rb').read()
pk = PR.Decoder().feed(raw)
samp = [i for i, (t, _, _) in enumerate(pk) if t == PR.SAMPLES]
cut = samp[int(0.6 * len(samp))]
lib = ctypes.CDLL(LIB9)
lib.rtl_init.argtypes = [ctypes.POINTER(R.Config)]
lib.rtl_rx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
lib.rtl_idle.restype = None
lib.rtl_counters.restype = ctypes.POINTER(R.Counters)
txcb = R.TX(lambda p, n: None)
lib.rtl_init(ctypes.byref(R.Config(txcb, R.NOW(0), 9, 0, 0, 3)))
for t, seq, p in pk[:cut + 1]:
    b = PR.build(t, seq, p)
    lib.rtl_rx(ctypes.c_char_p(b), len(b))
    if t == PR.CONTROL:
        lib.rtl_idle()
W = lib.rtl_counters().contents.windows
ins = [PR.build(PR.CONTROL, 60000 + i, bytes([15]) + struct.pack('<IIB', a, b_, c))
       for i, (a, b_, c) in enumerate(((W - 200, W - 101, 0), (W - 100, W - 1, 8)))]
out = b''.join(PR.build(t, s, p) for t, s, p in pk[:cut + 1]) + b''.join(ins) + \
    b''.join(PR.build(t, s, p) for t, s, p in pk[cut + 1:])
os.makedirs(os.path.join(d, 'run_range'), exist_ok=True)
open(os.path.join(d, 'run_range', 'bridge_out.bin'), 'wb').write(out)
print(f'inserted 2 range labels after packet {cut} (window {W}): [{W - 200},{W - 101}] class 0, [{W - 100},{W - 1}] Rest; '
      f'{len(out)} bytes')
