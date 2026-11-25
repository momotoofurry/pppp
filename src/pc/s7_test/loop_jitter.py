"""Control-computer timing check (reports 35.92-35.93): a 100 Hz sleep loop for N s, on two clocks:
  real stop  : a monotonic-clock step > 0.1 s (the process / the VM really stopped)
  clock step : the wall clock (time.time) moved > 0.05 s more or less than the monotonic one (time sync stepping)
90 s with neither (and a monotonic clock within 0.1 % of the raw hardware clock, 35.109) is required before the Kinova runs from this computer (SOP_Kinova實機.md 1.1).
35.92: WSL2 showed 0.7-3.4 s gaps every ~30.7 s, measured on the wall clock only; 35.93: after a standby / resume
none in 14 min on either clock. assist_ros.py times everything on the monotonic clock since 35.93.
  python3 src/pc/s7_test/loop_jitter.py [seconds]"""
import sys
import time

RAW = getattr(time, 'CLOCK_MONOTONIC_RAW', None)


def raw():
    return time.clock_gettime(RAW) if RAW is not None else time.monotonic()


def kernel_tick():
    """35.109: the kernel's tick in us (adjtimex, modes 0 = read only); nominal 10000 at USER_HZ 100"""
    try:
        import ctypes
        import ctypes.util

        class Timex(ctypes.Structure):
            _fields_ = [('modes', ctypes.c_uint)] + [(n, ctypes.c_long) for n in ('offset', 'freq', 'maxerror',
                        'esterror')] + [('status', ctypes.c_int)] + [(n, ctypes.c_long) for n in ('constant',
                        'precision', 'tolerance', 'time_sec', 'time_usec', 'tick', 'ppsfreq', 'jitter')] + \
                [('shift', ctypes.c_int)] + [(n, ctypes.c_long) for n in ('stabil', 'jitcnt', 'calcnt', 'errcnt',
                 'stbcnt')] + [('tai', ctypes.c_int), ('pad', ctypes.c_int * 11)]
        t = Timex()
        ctypes.CDLL(ctypes.util.find_library('c')).adjtimex(ctypes.byref(t))
        return t.tick
    except Exception:  # noqa: BLE001
        return None


N = float(sys.argv[1]) if len(sys.argv) > 1 else 90
t0m = pm = time.monotonic()
t0r = pr = raw()
pw = time.time()
stops, steps = [], []
while pr - t0r < N:
    time.sleep(0.01)
    m, r, w = time.monotonic(), raw(), time.time()
    dm, dr, dw = m - pm, r - pr, w - pw
    if dr > 0.1:                                   # 35.109: a real stop shows on the raw hardware clock too
        stops.append((round(r - t0r, 1), round(dr, 2)))
    if abs(dw - dm) > 0.05:
        steps.append((round(r - t0r, 1), round(dw - dm, 2)))
    pm, pr, pw = m, r, w
rate = 100 * ((pm - t0m) / (pr - t0r) - 1)         # 35.109: monotonic vs raw hardware clock
tick = kernel_tick()
print(f'{N:.0f} s: real stops > 0.1 s: {len(stops)} {stops[:10]};  wall-clock steps > 0.05 s: {len(steps)} {steps[:10]}')
print(f'monotonic clock rate vs hardware: {rate:+.3f} %; kernel tick {tick} us (nominal 10000)')
bad_rate = abs(rate) > 0.1
ok = not stops and not steps and not bad_rate
if ok:
    print('PASS')
elif stops:
    print('FAIL: this computer stops; do not drive the arm from it')
elif bad_rate:
    print(f'FAIL: the kernel clock runs {rate:+.2f} % off (tick {tick}): every timer in this Linux (control loop, '
          f'deadman, ROS) is off by as much, and the time sync steps the wall clock back every ~30 s. '
          f'Restart WSL (wsl --shutdown) and run this check again (report 35.109)')
else:
    print('FAIL: the system clock steps (time sync); fix the time sync before driving the arm')
sys.exit(0 if ok else 1)
