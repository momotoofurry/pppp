"""NinaPro DB2 Exercise B: do task soft labels help the 9 directional gestures after a short cued pass?
(report 35.50, 2026-11-17; the 9-gesture self-test's rule 2 in simulation)

Per subject and sensor configuration (as db2_wrist_sim.py: 4ch = FDS + EDC + 2 ring electrodes repeated, all 28 ring
pairs, median reported; ring8), per gesture set S9 / S7 / S5, in time order:
  cued pass   repetitions 1-2 of each gesture, windows from 0.5 s after onset, at most 30 (one 4 s cue); Rest 30
              windows >= 1 s from any movement. The board's model (selftest9_analysis.Model: session z-score, Q5.10,
              running sums, OAS LDA).
  task        repetitions 3-4 of each non-Rest gesture of the set = task trials (the task knows the gesture): windows
              from the onset; the command = first run of 3 equal non-Rest predictions (K_DC), its rows = that run
              extended while the prediction stays; no command -> no label.
  test        repetitions 5-6 (windows from 0.5 s after onset) and up to 150 later Rest windows; balanced accuracy %.
Conditions:
  cue         the cued-pass model, never changed
  cue_soft    + one soft label per command (selftest9_analysis.Model.soft = RTL_TASK_LABEL: prior expected 1 - EPS, the
              other commands share EPS, Rest P0; q ~ prior exp(BETA x mean discriminant); forget 0.97; add; refit)
  cue_soft30  the same with 30 % wrong task expectations (the task names another command of the set at random)
  cue_true    + the command's rows with the TRUE gesture as a hard label (forget 0.97) = what a perfect label would give
Caveat: one donning, the task repetitions follow the cued pass within minutes: this measures how much the labels of
use add to a short cued pass, not drift across days.

usage: python src/db2_soft_sim.py --dir /db2 --subjects 1-10 [--out results/db2_wrist]
"""
import argparse
import itertools
import os
import sys

import numpy as np
import scipy.io as sio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db2_wrist_sim as W  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

SETS, ORDER, REST = S9.SETS, S9.ORDER, S9.REST
CONDS = ['cue', 'cue_soft', 'cue_soft30', 'cue_true']


def split(a, ra, same, since, rest_ok):
    cal, trials, test = {}, [], {}
    rest = np.flatnonzero(rest_ok)
    cal[REST] = rest[:30]
    later = rest[30:]
    test[REST] = later[np.linspace(0, len(later) - 1, min(150, len(later))).astype(int)] if len(later) else later
    for g, mv in enumerate(W.DB2_MOVE):
        if mv == 0:
            continue
        ok = (a == mv) & same & (since >= 0.5)
        cal[g] = np.flatnonzero(ok & (ra >= 1) & (ra <= 2))[:30]
        test[g] = np.flatnonzero(ok & (ra >= 5))
        for r in (3, 4):
            w = np.flatnonzero((a == mv) & same & (ra == r))
            if len(w) >= S9.K_DC:
                trials.append((w[0], w, g))
    trials.sort(key=lambda x: x[0])
    return cal, [(w, g) for _, w, g in trials], test


def run(X, cal, trials, test, classes, cond, rng):
    rows = np.concatenate([cal[c] for c in classes])
    lab = np.concatenate([np.full(len(cal[c]), c) for c in classes])
    mdl = S9.Model(X, rows, lab, classes)
    cmds = [c for c in classes if c != REST]
    for w, g in trials:
        if g not in classes or cond == 'cue':
            continue
        pred, R = S9.decide(mdl, X[w])
        if pred is None:
            continue
        if cond == 'cue_true':
            Zq = mdl.z(R)
            k = classes.index(g)
            mdl.G = S9.DECAY * mdl.G + Zq.T @ Zq
            mdl.s = S9.DECAY * mdl.s
            mdl.n = S9.DECAY * mdl.n
            mdl.s[k] += Zq.sum(0)
            mdl.n[k] += len(Zq)
            mdl.fit()
        else:
            exp = g
            if cond == 'cue_soft30' and rng.random() < 0.3:
                exp = int(rng.choice([c for c in cmds if c != g]))
            mdl.soft(R, exp)
    rec = [np.mean(mdl.predict(X[test[c]]) == c) for c in classes if len(test[c])]
    return 100 * np.mean(rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-10')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    a_, b_ = (args.subjects.split('-') + [None])[:2]
    subs = list(range(int(a_), int(b_ or a_) + 1))
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    pairs = list(itertools.combinations(range(8), 2))
    R = {cfg: {s: {c: [] for c in CONDS} for s in ORDER} for cfg in ('4ch', 'ring8')}
    p('subject cfg   set   ' + '  '.join(f'{c:>10s}' for c in CONDS) + '   task trials')
    for subj in subs:
        d = sio.loadmat(W.find_mat(args.dir, subj))
        emg = d['emg'].astype(np.float64)
        lab = d['restimulus'].ravel().astype(int)
        rep = d['rerepetition'].ravel().astype(int)
        CF = W.channel_features(emg)
        cal, trials, test = split(*W.window_labels(lab, rep, CF.shape[0]))
        for cfg in ('4ch', 'ring8'):
            mats = ([W.config_matrix(CF, [W.FDS, W.EDC, i, j] * 2) for i, j in pairs] if cfg == '4ch'
                    else [W.config_matrix(CF, list(range(8)))])
            for s in ORDER:
                vals = {}
                for c in CONDS:
                    accs = [run(X, cal, trials, test, SETS[s], c, np.random.default_rng(subj * 100 + k))
                            for k, X in enumerate(mats)]
                    vals[c] = float(np.median(accs))
                    R[cfg][s][c].append(vals[c])
                nt = sum(g in SETS[s] for _, g in trials)
                p(f'{subj:7d} {cfg:5s} {s}   ' + '  '.join(f'{vals[c]:10.1f}' for c in CONDS) + f'   {nt}')
    p('\nmean (SD) over subjects, balanced accuracy % (4ch: median over the 28 ring pairs per subject)')
    for cfg in ('4ch', 'ring8'):
        for s in ORDER:
            m = {c: np.array(R[cfg][s][c]) for c in CONDS}
            d_soft = m['cue_soft'] - m['cue']
            p(f'{cfg:5s} {s}: ' + '  '.join(f'{c} {m[c].mean():5.1f} ({m[c].std():4.1f})' for c in CONDS)
              + f'   soft - cue {d_soft.mean():+5.1f}, better in {int((d_soft > 0).sum())}/{len(d_soft)}')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, 'db2_soft_sim.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
