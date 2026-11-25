"""35.109: watch the kernel tick / freq (adjtimex, read-only) and the monotonic rate vs the raw clock, every 2 s"""
import ctypes
import ctypes.util
import sys
import time


class Timex(ctypes.Structure):
    _fields_ = [('modes', ctypes.c_uint)] + [(n, ctypes.c_long) for n in ('offset', 'freq', 'maxerror', 'esterror')] + \
        [('status', ctypes.c_int)] + [(n, ctypes.c_long) for n in ('constant', 'precision', 'tolerance', 'time_sec',
                                                                   'time_usec', 'tick', 'ppsfreq', 'jitter')] + \
        [('shift', ctypes.c_int)] + [(n, ctypes.c_long) for n in ('stabil', 'jitcnt', 'calcnt', 'errcnt', 'stbcnt')] + \
        [('tai', ctypes.c_int), ('pad', ctypes.c_int * 11)]


libc = ctypes.CDLL(ctypes.util.find_library('c'))
N = float(sys.argv[1]) if len(sys.argv) > 1 else 180
t0r = time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
pr, pm, pw = t0r, time.monotonic(), time.time()
last = None
while time.clock_gettime(time.CLOCK_MONOTONIC_RAW) - t0r < N:
    time.sleep(2)
    t = Timex()
    st = libc.adjtimex(ctypes.byref(t))
    r, m, w = time.clock_gettime(time.CLOCK_MONOTONIC_RAW), time.monotonic(), time.time()
    rate = 100 * ((m - pm) / (r - pr) - 1)
    step = (w - pw) - (m - pm)
    cur = (t.tick, round(t.freq / 65536, 1))
    if cur != last or abs(step) > 0.05 or abs(rate) > 0.1:
        print(f'{r - t0r:6.1f} s  tick {t.tick}  freq {t.freq / 65536:7.1f} ppm  state {st}  rate(2 s) {rate:+6.2f} %  '
              f'wall step {step:+.2f} s', flush=True)
    last = cur
    pr, pm, pw = r, m, w
print('done')
