"""WSL pause probe (35.93): 100 Hz loop for N s under a load; every iteration step > 0.08 s on the monotonic clock
(a real stop of the process) or a wall-clock step (wall vs monotonic differ by > 0.05 s). Also samples Dirty /
Writeback kB from /proc/meminfo at each event.
  python3 pause_probe.py <seconds> <load: idle|mntc|tmp|cpu> [label]
  mntc: a thread appends a 200-byte line to a file on /mnt/c every 100 ms and flushes (like a CSV log there)
  tmp : the same on /tmp (ext4)
  cpu : a thread spins (one core busy)"""
import os
import sys
import threading
import time

N = float(sys.argv[1])
LOAD = sys.argv[2]
LABEL = sys.argv[3] if len(sys.argv) > 3 else LOAD
stop = False


def meminfo():
    d = {}
    for ln in open('/proc/meminfo'):
        k, v = ln.split(':')
        if k in ('Dirty', 'Writeback'):
            d[k] = int(v.split()[0])
    return d


def writer(path):
    f = open(path, 'w')
    while not stop:
        f.write('x' * 199 + '\n')
        f.flush()
        time.sleep(0.1)
    f.close()
    os.remove(path)


def spin():
    while not stop:
        pass


th = None
if LOAD == 'mntc':
    th = threading.Thread(target=writer, args=('/mnt/c/Users/kirit/AppData/Local/Temp/pause_probe_load.txt',))
elif LOAD == 'tmp':
    th = threading.Thread(target=writer, args=('/tmp/pause_probe_load.txt',))
elif LOAD == 'cpu':
    th = threading.Thread(target=spin)
if th:
    th.start()
t0w, t0m = time.time(), time.monotonic()
pw, pm = t0w, t0m
ev = []
while pm - t0m < N:
    time.sleep(0.01)
    w, m = time.time(), time.monotonic()
    dm, dw = m - pm, w - pw
    if dm > 0.08 or abs(dw - dm) > 0.05:
        ev.append((round(m - t0m, 1), round(dm, 3), round(dw - dm, 3), meminfo()))
    pw, pm = w, m
stop = True
if th:
    th.join()
print(f'[{LABEL}] {N:.0f} s: real stops (monotonic step > 0.08 s): {sum(1 for e in ev if e[1] > 0.08)}; '
      f'wall-clock steps: {sum(1 for e in ev if abs(e[2]) > 0.05)}')
for e in ev[:12]:
    print('   t %6.1f  stop %.3f s  wall-mono %+.3f s  %s' % e)
