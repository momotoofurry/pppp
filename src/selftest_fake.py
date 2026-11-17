"""Synthetic self-test sessions for a dry run of src/selftest_analysis.py (report 35.35). NOT data of a person and
NOT a result: real Trigno EMG of the Kyranou et al. (2025) data spliced along the self-test schedule, written in the
exact file formats of TrignoBridge.exe (<name>_emg.csv at a TCU-like 2148 Hz, <name>_ops.csv) and TaskScreen.exe
(<name>_task.csv), so that the whole analysis path (rate fit, resampling, features, cue / trial windows, replay,
decision rule) runs once before the first real recording.

Per participant p (1-3) and day d (1-2): the EMG of each scheduled gesture is a random stretch of a random trial of
that grasp from participant{p}_day{d}_block1 (rows 0-7 = one electrode ring; grasp codes 1-6 -> Power Lateral Tripod
Pointer Open Rest), rest periods from the rest grasp. Schedule as SELFTEST.md: 3 s rest; cued pass cal 0..5 (gesture
4.5 s, rest 2 s), calibrate; TaskScreen labelled (2 x 6 cues, gap 3 s, cue 2 s, gesture from 0.4 s after cue_on to
0.2 s after cue_off), task (40 trials, the target's gesture from 0.5 s to 2.5 s, trial_off at 2.2 s, rest 2.5 s),
labelled, task, labelled. The user's reaction to the board's feedback is not modelled.
Usage (in the container, Kyranou data at /data): python src/selftest_fake.py [--out build/selftest_fake]
"""
import argparse
import os
from fractions import Fraction

import h5py
import numpy as np
import pandas as pd
from scipy.signal import resample_poly

FS, TCU = 2000, 2148.0
GEST = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']
COMMANDS = ['grip', 'release', 'pose_A', 'pose_B', 'home']
CMD_G = {'pose_A': 0, 'home': 1, 'grip': 2, 'pose_B': 3, 'release': 4}
T0_UNIX = 1.7e12
COLS = 'unix_ms,segment,event,step,trial,target,command,command_gesture,window,phase,result,latency_ms,text'.split(',')


def order(items, count, rng):
    while True:
        left = {i: count for i in items}
        o, prev = [], None
        for _ in range(len(items) * count):
            cand = [i for i in items if i != prev and left[i] > 0]
            if not cand:
                break
            w = np.array([left[i] for i in cand], float)
            pick = cand[rng.choice(len(cand), p=w / w.sum())]
            left[pick] -= 1
            o.append(pick)
            prev = pick
        if len(o) == len(items) * count:
            return o


class Stream:
    def __init__(self, pools, rng):
        self.pools, self.rng, self.chunks, self.n = pools, rng, [], 0

    def add(self, g, seconds):
        need = int(round(seconds * FS))
        while need > 0:
            tr = self.pools[g][self.rng.integers(len(self.pools[g]))]
            a = self.rng.integers(0, max(1, tr.shape[1] - 2000))
            seg = tr[:, a:a + need]
            self.chunks.append(seg)
            self.n += seg.shape[1]
            need -= seg.shape[1]

    def ms(self):
        return T0_UNIX + self.n / FS * 1000


def session(data, p, d, rng):
    base = os.path.join(data, 'data', f'participant_{p}', f'participant{p}_day{d}_block1')
    tr = pd.read_csv(os.path.join(base, 'trials.csv'), index_col=0)
    pools = {g: [] for g in range(6)}
    with h5py.File(os.path.join(base, 'emg_data.hdf5'), 'r') as f:
        for r in tr.itertuples():
            pools[int(r.grasp) - 1].append(np.asarray(f[str(r.row_number)], dtype=np.float32)[:8])
    s = Stream(pools, rng)
    ops, task = [], []

    def tl(event, seg='', step='', trial='', target='', text=''):
        row = dict.fromkeys(COLS, '')
        row.update(unix_ms=f'{s.ms():.1f}', segment=seg, event=event, step=step, trial=trial, target=target, text=text)
        task.append(row)

    s.add(5, 3.0)
    ops.append((s.ms(), 'reset', 1))
    for g in range(6):
        ops.append((s.ms(), f'cal {g}', 1))
        s.add(g, 4.5)
        s.add(5, 2.0)
    ops.append((s.ms(), 'calibrate', 1))
    s.add(5, 3.0)
    tl('session', text='subject F00 day 1 segments labelled task labelled task labelled (synthetic)')
    for idx, seg in enumerate(['labelled', 'task', 'labelled', 'task', 'labelled']):
        s.add(5, 1.0)
        tl('seg_start', seg, text=str(idx))
        step = 0
        if seg == 'labelled':
            for g in order(list(range(6)), 2, rng):
                tl('rest_on', seg, step, target='')
                s.add(5, 3.0)
                tl('rest_off', seg, step)
                step += 1
                tl('cue_on', seg, step, target=GEST[g])
                s.add(5, 0.4)
                s.add(g, 1.6)
                tl('cue_off', seg, step, target=GEST[g])
                s.add(g, 0.2)
                step += 1
            tl('rest_on', seg, step)
            s.add(5, 2.8)
            tl('rest_off', seg, step)
        else:
            tl('rest_on', seg, step)
            s.add(5, 2.5)
            tl('rest_off', seg, step)
            step += 1
            for t, c in enumerate(order(COMMANDS, 8, rng)):
                tl('trial_on', seg, step, t, c)
                s.add(5, 0.5)
                s.add(CMD_G[c], 1.7)
                tl('trial_off', seg, step, t, c)
                s.add(CMD_G[c], 0.3)
                step += 1
                tl('rest_on', seg, step)
                s.add(5, 2.2)
                tl('rest_off', seg, step)
                step += 1
        tl('seg_end', seg, text=str(idx))
    X = np.concatenate(s.chunks, axis=1).T.astype(np.float64)        # n x 8 at 2000 Hz
    fr = Fraction(TCU / FS).limit_denominator(1000)
    Y = resample_poly(X, fr.numerator, fr.denominator, axis=0)
    rate = FS * fr.numerator / fr.denominator
    frame = np.arange(len(Y))
    batch = frame // 27
    ms = T0_UNIX + ((batch + 1) * 27) / rate * 1000 + 2.0       # a read returns 27 frames, logged ~2 ms later
    emg = pd.DataFrame(Y.astype(np.float32), columns=[f'ch{c}_V' for c in range(1, 9)])
    emg.insert(0, 'frame', frame)
    emg.insert(0, 'unix_ms', [f'{v:.1f}' for v in ms])           # as TrignoBridge: F1, not the float format
    return emg, pd.DataFrame(ops, columns=['unix_ms', 'command', 'accepted']), pd.DataFrame(task)[COLS], rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    ap.add_argument('--out', default='build/selftest_fake')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for p in (1, 2, 3):
        for d in (1, 2):
            rng = np.random.default_rng(p * 10 + d)
            emg, ops, task, rate = session(args.data, p, d, rng)
            name = f'F{p:02d}_d{d}_A'
            emg.to_csv(os.path.join(args.out, f'{name}_emg.csv'), index=False, float_format='%.7g')
            ops.to_csv(os.path.join(args.out, f'{name}_ops.csv'), index=False, float_format='%.1f')
            task.to_csv(os.path.join(args.out, f'{name}_task.csv'), index=False)
            print(f'{name}: {len(emg)} frames at {rate:.1f} Hz = {len(emg) / rate / 60:.1f} min, {len(task)} task rows', flush=True)


if __name__ == '__main__':
    main()
