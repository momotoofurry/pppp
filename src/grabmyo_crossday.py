"""GrabMyo (PhysioNet 1.1.0): per-donning short calibration, accumulation across donnings and task soft labels
across three days (Day 1, 8, 29) for the directional gestures it has (report 35.51, 2026-11-17).

GrabMyo: 43 participants, 3 sessions on different days, 16 gestures + REST, 7 trials of 5 s per gesture and session,
2048 Hz (resampled to 2000 Hz for the board's feature code), forearm: two rings of 8 bipolar channels.
Gesture mapping to the self-test (GrabMyo has no radial / ulnar deviation; the user chose supination / pronation as
the stand-ins for left / right, 2026-11-17):
  12 wrist extension -> WristExt, 11 wrist flexion -> WristFlex, 13 forearm supination -> left, 14 forearm pronation
  -> right, 9 index finger extension -> Point, 10 thumb extension -> ThumbUp (closest), 15 hand open -> HandOpen,
  16 hand close -> Fist, 17 REST -> Rest.
Sets as the self-test: G9 all 9; G7 without Point and ThumbUp; G5 the 4 directions + Rest.
Sensors (fed as 8 channels to features.c like the self-test): ring8 = the 8 channels of forearm ring 1; 4ch = every
other electrode of ring 1 ({1,3,5,7} and {2,4,6,8}, each repeated twice; mean of the two reported).

Each day (session), as on the board (selftest9_analysis.Model):
  cued pass  trial 1 of each gesture, windows from 0.5 s, at most 30 (one 4 s cue)
  task       trials 2-4 of each non-Rest gesture = task trials (first run of 3 equal non-Rest predictions = the
             command; soft label RTL_TASK_LABEL; no command -> no label)
  test       trials 5-7, windows from 0.5 s; balanced accuracy %
Conditions:
  fixed      the day-1 model (cue + soft labels of day 1) used on later days with its day-1 z-score, never refitted
  cue        a new model from each day's cued pass only (per-donning short calibration)
  cue_soft   each day: cued pass + that day's soft labels (nothing carried over)
  acc        running sums carried across days (no forgetting between days): each day the session z-score from its
             cued windows, its cued windows added, refit (the board's per-donning accumulation, no task labels)
  acc_soft   acc + soft labels every day (the full system)
Primary comparison (days 8 and 29): acc_soft vs cue; also acc vs cue, cue_soft vs cue.
Caveat: GrabMyo's 'Day 1' cue model meets day 8 / 29 after the electrodes were re-applied by the experimenters (not
by the user), with the same protocol each day.

usage: python src/grabmyo_crossday.py --dir /grabmyo --subjects 1-43 [--out results/grabmyo]
"""
import argparse
import os
import sys

import numpy as np
from scipy.signal import resample_poly

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

# class order as the self-test (Rest last). GrabMyo has no radial / ulnar deviation: forearm supination (13) and
# pronation (14) stand in for left / right (a symmetric pair with a direction, but other muscles: pronator teres,
# supinator, biceps; the count of classes matches, their accuracy does not stand for the user's deviations)
NAMES = ['WristExt', 'WristFlex', 'Left~Supination', 'Right~Pronation', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']
GM = [12, 11, 13, 14, 9, 10, 15, 16, 17]         # GrabMyo gesture number of each class
REST = 8
SETS = {'G9': list(range(9)), 'G7': [0, 1, 2, 3, 6, 7, 8], 'G5': [0, 1, 2, 3, 8]}   # as S9 / S7 / S5
CONDS = ['fixed', 'cue', 'cue_soft', 'acc', 'acc_soft']
FS, WIN, STEP, K_DC = 2000.0, 400, 200, 3


def read_wfdb(base):
    """minimal WFDB reader for format 16 records: -> (n, nsig) float physical units, channel names"""
    with open(base + '.hea') as f:
        lines = [x.strip() for x in f if x.strip() and not x.startswith('#')]
    head = lines[0].split()
    nsig = int(head[1])
    gains, bases, names = [], [], []
    for ln in lines[1:1 + nsig]:
        p = ln.split()
        assert p[1].startswith('16'), f'{base}: format {p[1]}'
        g = p[2].split('/')[0]
        if '(' in g:
            gv, bv = g.split('(')
            gains.append(float(gv))
            bases.append(float(bv.rstrip(')')))
        else:
            gains.append(float(g) if float(g) != 0 else 200.0)
            bases.append(0.0)
        names.append(p[-1] if len(p) > 8 else f'ch{len(names)}')
    raw = np.fromfile(base + '.dat', dtype='<i2')
    raw = raw[: len(raw) // nsig * nsig].reshape(-1, nsig).astype(np.float64)
    return (raw - np.array(bases)) / np.array(gains), names


def trial_features(X):
    """resample 2048 -> 2000 Hz and compute the board's 80 features on the 8 given channels"""
    Y = (resample_poly(X, 125, 128, axis=0) * 1e-3).astype(np.float32)          # mV (the .hea units) -> V
    return SA.features(Y)


def load_session(root, sess, subj, chans):
    d = os.path.join(root, f'Session{sess}', f'session{sess}_participant{subj}')
    F = {}
    for c, gm in enumerate(GM):
        for t in range(1, 8):
            X, _ = read_wfdb(os.path.join(d, f'session{sess}_participant{subj}_gesture{gm}_trial{t}'))
            F[(c, t)] = trial_features(X[:, chans])
    return F


def stack(F, keys, cap=None):
    Xs, ys = [], []
    for c, t in keys:
        f = F[(c, t)][5:]                         # windows from 0.5 s (5 x 0.1 s)
        if cap:
            f = f[:cap]
        Xs.append(f)
        ys.append(np.full(len(f), c))
    return np.concatenate(Xs), np.concatenate(ys)


class Acc(S9.Model):
    """running sums carried across sessions; each session gets its own z-score from its cued windows"""

    def __init__(self, X, y, classes):
        super().__init__(X, np.arange(len(X)), y, classes)

    def new_session(self, X, y):
        self.mu, sd = X.mean(0), X.std(0)
        self.inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
        Zq = self.z(X)
        idx = np.array([self.classes.index(c) for c in y])
        np.add.at(self.s, idx, Zq)
        self.n += np.bincount(idx, minlength=len(self.classes))
        self.G += Zq.T @ Zq
        self.fit()


def soft_pass(mdl, F, classes):
    for t in (2, 3, 4):
        for c in classes:
            if c == REST:
                continue
            X = F[(c, t)]
            pred, R = S9.decide(mdl, X)
            if pred is not None:
                mdl.soft(R, c)


def test_acc(mdl, F, classes):
    rec = []
    for c in classes:
        X, _ = stack(F, [(c, t) for t in (5, 6, 7)])
        rec.append(np.mean(mdl.predict(X) == c))
    return 100 * np.mean(rec)


def run_subject(days, classes):
    """days: three dicts of trial features -> {cond: [acc day1, day8, day29]}"""
    S9.REST = REST                                # decide() and Model.soft() use the module's Rest index
    out = {c: [] for c in CONDS}
    acc = acc_soft = fixed = None
    for di, F in enumerate(days):
        Xc, yc = stack(F, [(c, 1) for c in classes], cap=30)
        cue = S9.Model(Xc, np.arange(len(Xc)), yc, classes)
        out['cue'].append(test_acc(cue, F, classes))
        cs = S9.Model(Xc, np.arange(len(Xc)), yc, classes)
        soft_pass(cs, F, classes)
        out['cue_soft'].append(test_acc(cs, F, classes))
        if di == 0:
            acc = Acc(Xc, yc, classes)
            acc_soft = Acc(Xc, yc, classes)
            soft_pass(acc_soft, F, classes)
            fixed = cs
        else:
            acc.new_session(Xc, yc)
            acc_soft.new_session(Xc, yc)
            soft_pass(acc_soft, F, classes)
        out['acc'].append(test_acc(acc, F, classes))
        out['acc_soft'].append(test_acc(acc_soft, F, classes))
        out['fixed'].append(test_acc(fixed, F, classes))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--subjects', default='1-43')
    ap.add_argument('--out', default=None)
    ap.add_argument('--ring-offset', type=int, default=0, help='first stored column of forearm ring 1')
    args = ap.parse_args()
    a_, b_ = (args.subjects.split('-') + [None])[:2]
    subs = list(range(int(a_), int(b_ or a_) + 1))
    o = args.ring_offset
    CFG = {'ring8': [[o + i for i in range(8)]],
           '4ch': [[o + i for i in (0, 2, 4, 6)] * 2, [o + i for i in (1, 3, 5, 7)] * 2]}
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    R = {(cfg, s): {c: [] for c in CONDS} for cfg in CFG for s in SETS}
    p('subject cfg   set  ' + '  '.join(f'{c:>20s}' for c in CONDS) + '   (day1/day8/day29)')
    for subj in subs:
        for cfg, chan_sets in CFG.items():
            per = {s: {c: [] for c in CONDS} for s in SETS}
            for chans in chan_sets:
                days = [load_session(args.dir, sess, subj, chans) for sess in (1, 2, 3)]
                for s, cls in SETS.items():
                    r = run_subject(days, cls)
                    for c in CONDS:
                        per[s][c].append(r[c])
            for s in SETS:
                line = f'{subj:7d} {cfg:5s} {s}  '
                for c in CONDS:
                    v = np.mean(per[s][c], axis=0)
                    R[(cfg, s)][c].append(v)
                    line += f'  {v[0]:6.1f}/{v[1]:5.1f}/{v[2]:5.1f}'
                p(line)
    p('\nmean over subjects, balanced accuracy % on day 1 / day 8 / day 29')
    for (cfg, s), d in R.items():
        p(f'{cfg:5s} {s}: ' + '  '.join(f'{c} ' + '/'.join(f'{x:.1f}' for x in np.mean(d[c], axis=0)) for c in CONDS))
        cue = np.array(d['cue'])[:, 1:].mean(1)
        for c in ('acc', 'cue_soft', 'acc_soft'):
            diff = np.array(d[c])[:, 1:].mean(1) - cue
            p(f'      {c:8s} - cue on days 8 + 29: {diff.mean():+5.1f}, better in {int((diff > 0).sum())}/{len(diff)}')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f'grabmyo_crossday_{args.subjects}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
