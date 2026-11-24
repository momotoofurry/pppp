"""Fake TCU for the S7 end-to-end test of TrignoBridge (report 35.80): streams a recorded self-test day in real time
(channels 1-8 of the recording on TCU slots 1-8), from 2 s before its first cued gesture to 2 s after the end of its
first labelled probe; writes script.txt (report 1, the day's cal commands and calibrate at their recorded times,
quit) and cues.csv (probe cues: start / end in seconds from the stream start, gesture).
usage: python fake_tcu_s7.py --day D:/selftest_data/T00/T00_d2_G --name T00_d2_G --out <dir> [--host 127.0.0.2]
  [--more S]   (2026-11-25 dry run) stream S more seconds of the recording after the first labelled probe (the task
               screen's session runs on it; its cues do not match the recording)"""
import argparse
import os
import socket
import threading
import time

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--day', required=True)
ap.add_argument('--name', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--host', default='127.0.0.2')
ap.add_argument('--more', type=float, default=0.0)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
emg = pd.read_csv(os.path.join(a.day, f'{a.name}_emg.csv'))
ops = pd.read_csv(os.path.join(a.day, f'{a.name}_ops.csv'))
task = pd.read_csv(os.path.join(a.day, f'{a.name}_task.csv'), dtype=str, keep_default_na=False)
task['t'] = task.unix_ms.astype(float)
ms = emg.unix_ms.to_numpy(float)
X = emg[[f'ch{c}_V' for c in range(1, 9)]].to_numpy(np.float32)
cal = ops[ops.command.str.match(r'^(cal \d+|calibrate)$')]
seg = task[task.segment == 'labelled']
first_end = seg.loc[seg.event == 'seg_end', 't'].iloc[0]
t_start = cal.unix_ms.iloc[0] - 2000
t_end = first_end + 2000 + 1000 * a.more
i0, i1 = np.searchsorted(ms, t_start), np.searchsorted(ms, t_end)
data = np.zeros((i1 - i0, 16), np.float32)
data[:, :8] = X[i0:i1]
t0ms = ms[i0]
lines = ['0.000 report 1'] + [f'{(r.unix_ms - t0ms) / 1000:.3f} {r.command}' for r in cal.itertuples()]
lines.append(f'{(t_end - t0ms) / 1000 + 1.0:.3f} quit')
open(os.path.join(a.out, 'script.txt'), 'w').write('\n'.join(lines) + '\n')
cues, on = [], {}
for r in seg.itertuples():
    if r.t > first_end:
        break
    if r.event == 'cue_on':
        on[r.step] = r.t
    elif r.event == 'cue_off' and r.step in on:
        cues.append(f'{(on.pop(r.step) - t0ms) / 1000:.3f},{(r.t - t0ms) / 1000:.3f},{r.target}')
open(os.path.join(a.out, 'cues.csv'), 'w').write('start_s,end_s,gesture\n' + '\n'.join(cues) + '\n')
print(f'{len(data)} frames ({len(data) / 2000:.1f} s), {len(cal)} cal / calibrate lines, {len(cues)} probe cues; '
      f'waiting on {a.host}:50040 / 50041', flush=True)

cs, es = socket.socket(), socket.socket()
for s, p in ((cs, 50040), (es, 50041)):
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((a.host, p))
    s.listen(1)
c, _ = cs.accept()
e, _ = es.accept()
c.sendall(b'Delsys Trigno System Digital Protocol Version (fake_tcu_s7.py)\r\n\r\n')
started = threading.Event()


def commands():
    buf = b''
    while True:
        d = c.recv(1024)
        if not d:
            return
        buf += d
        while b'\r\n\r\n' in buf:
            cmd, buf = buf.split(b'\r\n\r\n', 1)
            c.sendall(b'OK\r\n\r\n')
            if cmd.strip() == b'START':
                started.set()


threading.Thread(target=commands, daemon=True).start()
started.wait()
t0, i = time.perf_counter(), 0
while i < len(data):
    due = int((time.perf_counter() - t0) * 2000)
    if due > i:
        j = min(len(data), due)
        e.sendall(data[i:j].tobytes())
        i = j
    else:
        time.sleep(0.002)
time.sleep(0.5)
e.close()
print(f'sent {i} frames in {time.perf_counter() - t0:.1f} s', flush=True)
time.sleep(1.0)
c.close()
