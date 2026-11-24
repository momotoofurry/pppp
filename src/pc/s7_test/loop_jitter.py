"""Control-computer timing check (reports 35.92-35.93): a 100 Hz sleep loop for N s, on two clocks:
  real stop  : a monotonic-clock step > 0.1 s (the process / the VM really stopped)
  clock step : the wall clock (time.time) moved > 0.05 s more or less than the monotonic one (time sync stepping)
90 s with neither is required before the Kinova runs from this computer (SOP_Kinova實機.md 1.1).
35.92: WSL2 showed 0.7-3.4 s gaps every ~30.7 s, measured on the wall clock only; 35.93: after a standby / resume
none in 14 min on either clock. assist_ros.py times everything on the monotonic clock since 35.93.
  python3 src/pc/s7_test/loop_jitter.py [seconds]"""
import sys
import time

N = float(sys.argv[1]) if len(sys.argv) > 1 else 90
t0m = pm = time.monotonic()
pw = time.time()
stops, steps = [], []
while pm - t0m < N:
    time.sleep(0.01)
    m, w = time.monotonic(), time.time()
    dm, dw = m - pm, w - pw
    if dm > 0.1:
        stops.append((round(m - t0m, 1), round(dm, 2)))
    if abs(dw - dm) > 0.05:
        steps.append((round(m - t0m, 1), round(dw - dm, 2)))
    pm, pw = m, w
print(f'{N:.0f} s: real stops > 0.1 s: {len(stops)} {stops[:10]};  wall-clock steps > 0.05 s: {len(steps)} {steps[:10]}')
ok = not stops and not steps
print('PASS' if ok else ('FAIL: this computer stops; do not drive the arm from it' if stops else
                         'FAIL: the system clock steps (time sync); fix the time sync before driving the arm'))
sys.exit(0 if ok else 1)
