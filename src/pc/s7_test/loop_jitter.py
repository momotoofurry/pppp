"""Control-computer timing check (report 35.92): a 100 Hz sleep loop for N s; reports every gap > 0.1 s (wall time).
90 s without a gap is required before the Kinova runs from this computer (SOP_Kinova實機.md 1.1).
WSL2 on the lab laptop, 2026-11-25: 0.7 s pauses every 30.7 s (Windows native Python: none in 70 s).
  python3 src/pc/s7_test/loop_jitter.py [seconds]"""
import sys
import time

N = float(sys.argv[1]) if len(sys.argv) > 1 else 90
t0 = last = time.time()
gaps = []
while time.time() - t0 < N:
    time.sleep(0.01)
    now = time.time()
    if now - last > 0.1:
        gaps.append((round(now - t0, 1), round(now - last, 2)))
    last = now
print(f'{N:.0f} s: gaps > 0.1 s: {len(gaps)} {gaps[:15]}')
print('PASS' if not gaps else 'FAIL: this computer pauses; do not drive the arm from it')
sys.exit(1 if gaps else 0)
