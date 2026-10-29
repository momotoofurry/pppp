"""Stand-in for the Trigno Control Utility, to test TrignoBridge.exe on this PC (numpy only).

TCP 50040 (commands: a banner on connect, "OK" to START / STOP) and 50041 (EMG: little-endian float32, 16 channels
per frame, volts; channels 1-8 = subject 0's recordings, 9-16 = 0). On START it streams, in real time at --rate,
the 6 calibration recordings and then the 30 recordings of testing_block0, back to back (as a live session would),
and closes the EMG socket at the end. --rate other than 2000 resamples the recordings (linear interpolation) so that
the bridge's resampling can be tested. Also writes <out>/script.txt (the bridge's --script: report, then per
calibration recording cal g (the bridge sends reset + CAL_START and, 2 s later, CAL_END), calibrate, a reset at the start of every test recording) and
<out>/segments.csv (segment = recording, in order, with its label), for src/pc/check_bridge.py.
Usage: python fake_tcu.py --out <dir> [--rate 2000]
"""
import argparse
import os
import socket
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, 'external', 'self-calibrating-rf', 'dataset_arm_position', '0')


def recordings():
    segs = []
    for folder in ['calibration', 'testing_block0']:
        d = np.load(os.path.join(DATA, folder, 'data.npy'))            # trials x 8 x 4000, volts
        lab = np.load(os.path.join(DATA, folder, 'label.npy')).astype(int)
        segs += [(folder, int(y), x.T) for x, y in zip(d, lab)]
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--rate', type=float, default=2000.0)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    segs = recordings()
    frames, t, script, rows = [], 0.0, ['0.000 report 1'], []
    for i, (kind, y, x) in enumerate(segs):
        dur = len(x) / 2000.0
        n = int(round(dur * args.rate))
        tt = np.arange(n) / args.rate * 2000.0
        xr = np.stack([np.interp(tt, np.arange(len(x)), x[:, c]) for c in range(8)], 1) if args.rate != 2000 else x
        frames.append(xr)
        if kind == 'calibration':
            script.append(f'{t + 0.005:.3f} cal {y}')            # reset + CAL_START; CAL_END by the bridge after 2 s
        else:
            script.append(f'{t + 0.005:.3f} reset')
        rows.append(f'{i},{kind},{y},{t:.3f},{n}')
        t += dur
        if kind == 'calibration' and i == 5:
            script.append(f'{t:.3f} calibrate')
    script.append(f'{t + 1.0:.3f} quit')
    with open(os.path.join(args.out, 'script.txt'), 'w') as fh:
        fh.write('\n'.join(script) + '\n')
    with open(os.path.join(args.out, 'segments.csv'), 'w') as fh:
        fh.write('segment,kind,label,t_s,frames\n' + '\n'.join(rows) + '\n')
    data = np.concatenate(frames)
    f16 = np.zeros((len(data), 16), np.float32)
    f16[:, :8] = data
    print(f'{len(data)} frames at {args.rate} Hz ({len(data) / args.rate:.1f} s); waiting for the bridge on 50040 / 50041')

    cs, es = socket.socket(), socket.socket()
    for s, p in ((cs, 50040), (es, 50041)):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', p))
        s.listen(1)
    c, _ = cs.accept()
    e, _ = es.accept()
    c.sendall(b'Delsys Trigno System Digital Protocol Version (fake_tcu.py)\r\n\r\n')
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
    while i < len(f16):
        due = int((time.perf_counter() - t0) * args.rate)
        if due > i:
            j = min(len(f16), due)
            e.sendall(f16[i:j].tobytes())
            i = j
        else:
            time.sleep(0.002)
    time.sleep(0.5)
    e.close()
    print(f'sent {i} frames in {time.perf_counter() - t0:.1f} s')
    time.sleep(1.0)
    c.close()


if __name__ == '__main__':
    main()
