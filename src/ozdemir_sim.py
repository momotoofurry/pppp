"""Ozdemir et al. 2022 (Data in Brief 41:107921; Mendeley 10.17632/ckwc76xr2z.2): 4 sensors on targeted forearm muscles
(extensor carpi radialis, flexor carpi radialis, extensor carpi ulnaris, flexor carpi ulnaris; BIOPAC MP36, 2 kHz, raw
.mat), 40 participants, one session of 5 cycles x 10 gestures (6 s each, every 10 s; cycles start at 4, 138, 272, 406,
540 s, the authors' EMG_gesture_segmentation.m). Report 35.52, 2026-11-17: the closest public match to the self-test's
4-muscle placement.

Gesture mapping (self-test class numbers): 1 extension -> WristExt (0), 2 flexion -> WristFlex (1), 4 radial deviation
-> RadialDev (2), 3 ulnar deviation -> UlnarDev (3), 6 abduction of all fingers -> HandOpen (6), 5 grip -> Fist (7),
0 rest -> Rest (8). No index point / thumb up: sets S7 (all 7) and S5 (4 wrist directions + Rest), as the self-test.
The 4 channels are fed twice as 8 channels to the board's features.c (as the self-test's repeated slots).
Labels follow the cue schedule: windows from 1.0 s to 5.5 s after a gesture's scheduled start (reaction time).

Designs (db2_soft_sim.run: the board's model; conditions cue, cue_soft, cue_soft30, cue_true):
  pass1  cued pass = cycle 1 (at most 30 windows per gesture = one 4 s cue), task = cycles 2-3, test = cycles 4-5
  pass2  cued pass = cycles 1-2 (at most 30 windows each = two 4 s cues, the 19th's protocol), task = cycle 3, test = 4-5
Task trial = a gesture's whole 6 s window from its scheduled start (first run of 3 equal non-Rest predictions = the
command). Balanced accuracy %. One session: no re-donning, no posture change.

usage: python src/ozdemir_sim.py --dir /oz --subjects 1-40 [--out results/ozdemir2022]
"""
import argparse
import os
import sys

import numpy as np
import scipy.io as sio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db2_soft_sim as DS  # noqa: E402
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

OZ = {1: 0, 2: 1, 4: 2, 3: 3, 6: 6, 5: 7, 0: 8}          # Ozdemir gesture -> self-test class
CYCLE0 = [4, 138, 272, 406, 540]
FS, WIN, STEP = 2000, 400, 200
SETS = {'S7': S9.SETS['S7'], 'S5': S9.SETS['S5']}
CONDS = DS.CONDS


def windows(nw, a, b):
    """windows wholly inside [a, b) seconds"""
    st = np.arange(nw) * STEP
    return np.flatnonzero((st >= a * FS) & (st + WIN <= b * FS))


def seg(nw, cycle, g, a=1.0, b=5.5):
    t = CYCLE0[cycle] + 10 * g
    return windows(nw, t + a, t + b)


def design(nw, kind):
    cal_cycles, task_cycles = ([0], [1, 2]) if kind == 'pass1' else ([0, 1], [2])
    cal, test, trials = {}, {}, []
    for og, c in OZ.items():
        cal[c] = np.concatenate([seg(nw, k, og)[:30] for k in cal_cycles])
        test[c] = np.concatenate([seg(nw, k, og) for k in (3, 4)])
        if c != S9.REST:
            for k in task_cycles:
                trials.append((CYCLE0[k] + 10 * og, seg(nw, k, og, 0.0, 6.0), c))
    trials.sort(key=lambda x: x[0])
    return cal, [(w, c) for _, w, c in trials], test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-40')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    a_, b_ = (args.subjects.split('-') + [None])[:2]
    subs = list(range(int(a_), int(b_ or a_) + 1))
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    R = {(k, s): {c: [] for c in CONDS} for k in ('pass1', 'pass2') for s in SETS}
    p('subject design set  ' + '  '.join(f'{c:>10s}' for c in CONDS))
    for subj in subs:
        m = sio.loadmat(os.path.join(args.dir, f'{subj}_raw.mat'))
        X = np.asarray(m['data'], dtype=np.float64)
        if X.shape[0] == 4:
            X = X.T
        if subj == subs[0]:
            p(f"# data {X.shape}, fs {np.ravel(m.get('fs', [0]))[0]}, units {np.ravel(m.get('units', ['?']))[0]}, "
              f"labels {[str(np.ravel(x)[0]) if np.size(x) else '' for x in np.ravel(m.get('labels', []))]}")
        F = SA.features((X[:, [0, 1, 2, 3, 0, 1, 2, 3]] * 1e-3).astype(np.float32))      # mV -> V
        for kind in ('pass1', 'pass2'):
            cal, trials, test = design(len(F), kind)
            for s, cls in SETS.items():
                vals = [DS.run(F, cal, trials, test, cls, c, np.random.default_rng(subj)) for c in CONDS]
                for c, v in zip(CONDS, vals):
                    R[(kind, s)][c].append(v)
                p(f'{subj:7d} {kind:6s} {s}  ' + '  '.join(f'{v:10.1f}' for v in vals))
    p('\nmean (SD) over subjects, balanced accuracy %')
    for (kind, s), d in R.items():
        m = {c: np.array(d[c]) for c in CONDS}
        diff = m['cue_soft'] - m['cue']
        p(f'{kind} {s}: ' + '  '.join(f'{c} {m[c].mean():5.1f} ({m[c].std():4.1f})' for c in CONDS)
          + f'   soft - cue {diff.mean():+5.1f}, better in {int((diff > 0).sum())}/{len(diff)}'
          + f'   >= 85 % (cue): {int((m["cue"] >= 85).sum())}/{len(diff)}, (soft): {int((m["cue_soft"] >= 85).sum())}/{len(diff)}')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, 'ozdemir_sim.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
