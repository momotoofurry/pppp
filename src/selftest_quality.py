"""Data quality of one self-test recording (6- or 9-gesture), run right after copying it (report 35.53, 2026-11-17):
stream gaps, repeated slots, per channel rest noise / active level / 60 Hz share / clipping, and the RMS of every
channel in every cued gesture (all cued passes averaged), so a sensor on the wrong muscle or a dead channel shows up.

usage: python src/selftest_quality.py --dir D:/selftest_data/T00 --name T00_d1_G [--out <folder>]
"""
import argparse
import os
import re

import numpy as np
import pandas as pd

FS = 2000.0
SIX = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    emg = pd.read_csv(os.path.join(a.dir, f'{a.name}_emg.csv'))
    ops = pd.read_csv(os.path.join(a.dir, f'{a.name}_ops.csv'))
    notes = ' | '.join(str(c) for c in ops.command if str(c).startswith('note'))
    m = re.search(r'note classes (\d+) ([A-Za-z ]+)', notes)
    gest = m.group(2).split()[:int(m.group(1))] if m else SIX
    ms = re.search(r'note slots (\S+)', notes)
    slots = ms.group(1).split(':') if ms else [str(i) for i in range(1, 9)]
    t = emg.unix_ms.to_numpy()
    fr = emg.frame.to_numpy()
    p(f'{a.name}: {len(emg)} rows, {(t[-1] - t[0]) / 60000:.2f} min, gestures {len(gest)}, slots {":".join(slots)}')
    df = np.diff(fr)
    p(f'frame steps != 1: {(df != 1).sum()} (largest {df.max()}); pc time gaps > 200 ms: {(np.diff(t) > 200).sum()} '
      f'(largest {np.diff(t).max():.0f} ms)')
    X = emg[[f'ch{i}_V' for i in range(1, 9)]].to_numpy()
    uniq = []
    for c in range(8):
        same = next((u for u in uniq if np.array_equal(X[:, u], X[:, c])), None)
        if same is None:
            uniq.append(c)
        else:
            p(f'  ch{c + 1} = copy of ch{same + 1}')
    X = X[:, uniq] - X[:, uniq].mean(0)
    names = [f'ch{u + 1} (slot {slots[u] if u < len(slots) else "?"})' for u in uniq]
    n = 1000
    r = np.sqrt((X[: len(X) // n * n].reshape(-1, n, len(uniq)) ** 2).mean(1)) * 1e6
    f = np.fft.rfftfreq(len(X), 1 / FS)
    p('\nchannel             rest(10%)  active(99%)  active/rest  max|x| mV  >8 mV  60 Hz %')
    warn = []
    for k, nm in enumerate(names):
        P = np.abs(np.fft.rfft(X[:, k])) ** 2
        tot = P[f > 0.5].sum()
        mains = sum(P[(f > h - 1) & (f < h + 1)].sum() for h in (60, 120, 180)) / tot * 100
        lo, hi = np.percentile(r[:, k], 10), np.percentile(r[:, k], 99)
        mx = np.abs(X[:, k]).max() * 1e3
        clip = int((np.abs(X[:, k]) > 8e-3).sum())
        p(f'{nm:18s} {lo:8.1f} uV {hi:9.1f} uV {hi / max(lo, 1e-9):10.1f}x {mx:9.3f} {clip:6d} {mains:7.1f}')
        if hi / max(lo, 1e-9) < 3:
            warn.append(f'{nm}: active only {hi / max(lo, 1e-9):.1f}x rest (contact / placement?)')
        if mains > 15:
            warn.append(f'{nm}: 60 Hz {mains:.0f} % (charger, cables?)')
        if clip:
            warn.append(f'{nm}: {clip} samples near the 8.19 mV limit')
    p('\ncued gestures: RMS (uV) over 0.5-4.0 s of each cue, all passes averaged; * = largest channel of the gesture')
    p('gesture        n  ' + ''.join(f'{nm[:12]:>14s}' for nm in names))
    for g, gname in enumerate(gest):
        rows = ops[ops.command.astype(str) == f'cal {g}']
        vals = []
        for u in rows.unix_ms:
            mm = (t >= u + 500) & (t < u + 4000)
            if mm.any():
                vals.append(np.sqrt((X[mm] ** 2).mean(0)) * 1e6)
        if not vals:
            p(f'{g} {gname:11s} 0  (no cued pass)')
            warn.append(f'gesture {g} {gname}: no cued pass')
            continue
        v = np.mean(vals, 0)
        top = int(np.argmax(v))
        p(f'{g} {gname:11s} {len(vals)}  ' + ''.join(f"{x:13.1f}{'*' if k == top else ' '}" for k, x in enumerate(v)))
    p('\nwarnings: ' + ('none' if not warn else ''))
    for w in warn:
        p('  - ' + w)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        open(os.path.join(a.out, f'{a.name}_quality.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
