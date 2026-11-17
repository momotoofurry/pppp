"""Self-test with the 9 directional gestures (report 35.45, 35.48, 35.49; 2026-11-17): how many gestures can 4 sensors
carry, and do task soft labels help with 9 gestures?

Recording (SOP 3B / 4A, panel gesture set "9 方向", files <subj>_d<day>_G_*): TrignoBridge run --firmware lda --classes 9
(board: rtl_task_9c2), TWO cued passes of the 9 gestures (cal 0-8 twice, 4 s each, then calibrate; 35.48, decided
before recording after the DB2 simulation 35.47), then TaskScreen --gestures nine --segments
labelled,task,labelled,task,labelled --reps 3 --n 40 --postures selftest (35.49):
  P0  labelled 1 (neutral posture): 3 x 9 cues of 2 s, random order
  T1  task 1: 40 cued arm commands (up down left right forward back grip_open grip_close, 5 each, random order)
  P1  labelled 2 (A then B)
  T2  task 2: 40 cued commands
  P2  labelled 3 (C then A)
The board is not taught during the recording; the task labels are replayed offline (as selftest_analysis).

Gestures (class order of the firmware; Rest last):
  0 WristExt (up)  1 WristFlex (down)  2 RadialDev (left)  3 UlnarDev (right)  4 Point (forward)  5 ThumbUp (back)
  6 HandOpen (gripper open)  7 Fist (gripper close)  8 Rest (stop)
Gesture sets compared on the SAME recording (each one is a separate model, as if the board had been built for it):
  S9  all 9
  S7  without Point and ThumbUp (the single-finger gestures): 4 wrist directions + HandOpen + Fist + Rest
  S5  the 4 wrist directions + Rest (a mode switch would carry the rest of the commands)

Model per set and day, as on the board (rt_lda.c): the cued windows of the set's gestures (every accepted 'cal g'
before the first segment, both passes and any redo, the last 30 windows of each = windows 9..38 after its stream reset,
like the board's buffer) give the z-score of the session (mean, population SD); Q5.10; running sums (no forgetting in
the cued pass, ld_add); OAS-shrunk pooled covariance LDA with equal priors (lda_robust.oas_solve). Test = the probe
cues whose gesture is in the set: the middle 10 windows of [cue_on + 0.5 s, cue_off] (selftest_analysis.mid / inside),
argmax over the set's classes.

Conditions (offline replay in time order):
  cue       the model of the cued pass, never changed
  cue_soft  + one soft task label per task trial whose target gesture is in the set, as RTL_TASK_LABEL: the trial's
            windows [trial_on, trial_off + 0.5 s]; the first run of 3 equal non-Rest predictions (K_DC) = the command,
            its rows = that run extended while the prediction stays; prior: expected 1 - EPS, the other commands of
            the set share EPS, Rest P0; q ~ prior x exp(BETA x mean discriminant over the rows); forget 0.97
            (ld_decay), add the rows with q (ld_add_soft), refit. EPS 0.15, P0 0.05, BETA 0.3 (rt_lda.h).

Rule 1 (35.45; the gesture set), fixed before the recording, n = 1 self-test, picks the set of the next experiment:
  A(S) = cue-condition window accuracy over all probe windows of the set (P0-P2 pooled), per day, mean over days.
  Choose the LARGEST set with A(S) >= 85 %; if none, the set with the highest A(S), and revise placement / gestures.
Rule 2 (35.49; soft labels with 9 gestures), fixed before the recording, same rule as R12 of selftest_analysis:
  D(S9) = mean over P1 and P2 of (cue_soft - cue) window accuracy, per day; D_bar = mean over days.
  GO if D_bar >= +2 points and D > 0 on at least ceil(2/3 x days) days; else NO-GO. S7 and S5 reported, not decided.
Also reported: per probe, cue-level majority accuracy, bootstrap 95 % intervals over cues (2000 resamples), per-class
recall and the 9-class confusion matrix (cue), chance 1 / |S|, offline command accuracy in the task trials, and the
same with --cal-s 2 (first 2 s of each cue).

usage: python src/selftest9_analysis.py --dir D:/selftest_data/T00 --days T00_d1_G [T00_d2_G ...] [--out ...] [--cal-s 4]
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import selftest_analysis as SA  # noqa: E402  (load_emg, features, inside, mid, q16, timing constants)

GESTURES = ['WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']
G = {g: i for i, g in enumerate(GESTURES)}
COMMAND = {'up': 'WristExt', 'down': 'WristFlex', 'left': 'RadialDev', 'right': 'UlnarDev', 'forward': 'Point',
           'back': 'ThumbUp', 'grip_open': 'HandOpen', 'grip_close': 'Fist'}
REST = G['Rest']
SETS = {
    'S9': list(range(9)),
    'S7': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'HandOpen', 'Fist', 'Rest')],
    'S5': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Rest')],
}
ORDER = ['S9', 'S7', 'S5']                      # largest first
THRESHOLD = 85.0
FS, WIN, STEP, WARMUP, REACT_S, HOLD_S, K_DC = SA.FS, SA.WIN, SA.STEP, SA.WARMUP, SA.REACT_S, SA.HOLD_S, SA.K_DC
EPS, P0, BETA, DECAY = 0.15, 0.05, 0.3, 0.97


def load_day(folder, name, cal_s):
    X, t0, rate = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    F = SA.features(X)
    nw = len(F)
    ops = pd.read_csv(os.path.join(folder, f'{name}_ops.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    first_seg = task.loc[task.event == 'seg_start', 't'].min()
    cal_nw = int(round((cal_s * FS - WIN) / STEP)) + 1 - WARMUP
    cue_rows, cue_lab = [], []
    seen = set()
    for r in ops.itertuples():
        c = str(r.command).split()
        if len(c) == 2 and c[0] == 'cal' and c[1].isdigit() and r.unix_ms < first_seg and str(r.accepted) not in ('0', 'False'):
            g = int(c[1])
            rows = SA.inside(t0, nw, float(r.unix_ms), float(r.unix_ms) + cal_s * 1000)[-cal_nw:]
            cue_rows.append(rows)
            cue_lab.append(np.full(len(rows), g))
            seen.add(g)
    assert seen == set(range(9)), f'{name}: cued pass incomplete, cal rows for {sorted(seen)}'
    runs, cur = {}, None
    for r in task.itertuples():
        if r.event == 'seg_start':
            cur = dict(idx=int(r.text), seg=r.segment, rows=[])
        elif cur is not None:
            cur['rows'].append(r)
            if r.event == 'seg_end':
                runs[cur['idx']] = cur
                cur = None
            elif r.event == 'seg_abort':
                cur = None
    probes, events = [], []                      # events: (time, 'probe', k) / (time, 'trial', (rows, class))
    for idx in sorted(runs):
        run = runs[idx]
        on = {}
        if run['seg'] == 'labelled':
            items = []
            for r in run['rows']:
                if r.event == 'cue_on':
                    on[r.step] = r
                elif r.event == 'cue_off' and r.step in on:
                    w = SA.mid(SA.inside(t0, nw, on[r.step].t + REACT_S * 1000, r.t))
                    if len(w):
                        items.append((w, G[r.target]))
            events.append((run['rows'][-1].t, 'probe', len(probes)))
            probes.append(items)
        elif run['seg'] == 'task':
            for r in run['rows']:
                if r.event == 'trial_on':
                    on[r.step] = r
                elif r.event == 'trial_off' and r.step in on and r.target in COMMAND:
                    w = SA.inside(t0, nw, on[r.step].t, r.t + HOLD_S * 1000)
                    if len(w) >= K_DC:
                        events.append((on[r.step].t, 'trial', (w, G[COMMAND[r.target]])))
    events.sort(key=lambda e: e[0])
    return dict(name=name, F=F, cal_rows=np.concatenate(cue_rows), cal_lab=np.concatenate(cue_lab), probes=probes,
                events=events, rate=rate, cal_counts=np.bincount(np.concatenate(cue_lab), minlength=9),
                trials=sum(e[1] == 'trial' for e in events))


class Model:
    """the board's running sums (ldacal.c) over the classes of one set, in the session's z-scored Q5.10 space"""

    def __init__(self, F, rows, lab, classes):
        self.classes = list(classes)
        keep = np.isin(lab, classes)
        Xc, yc = F[rows[keep]], lab[keep]
        self.mu, sd = Xc.mean(0), Xc.std(0)
        self.inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
        Zq = self.z(Xc)
        K = len(classes)
        idx = np.array([self.classes.index(c) for c in yc])
        self.n = np.bincount(idx, minlength=K).astype(float)
        self.s = np.zeros((K, Zq.shape[1]))
        np.add.at(self.s, idx, Zq)
        self.G = Zq.T @ Zq
        self.fit()

    def z(self, X):
        return SA.q16((X - self.mu) * self.inv)

    def fit(self):
        m = self.s / np.maximum(self.n, 1e-9)[:, None]
        N = self.n.sum()
        self.w, self.b = LR.oas_solve((self.G - (m.T * self.n) @ m) / N, N, m)

    def scores(self, X):
        return self.z(X) @ self.w.T + self.b

    def predict(self, X):
        return np.array(self.classes)[np.argmax(self.scores(X), 1)]

    def soft(self, X, expected):
        """one task label (RTL_TASK_LABEL): prior x exp(beta x mean discriminant), forget, add with q, refit"""
        K = len(self.classes)
        others = [c for c in self.classes if c not in (expected, REST)]
        prior = np.array([1 - EPS if c == expected else P0 if c == REST else EPS / max(len(others), 1)
                          for c in self.classes])
        s = self.scores(X).mean(0)
        q = prior * np.exp(BETA * (s - s.max()))
        q /= q.sum()
        Zq = self.z(X)
        self.G = DECAY * self.G + Zq.T @ Zq
        self.s = DECAY * self.s + np.outer(q, Zq.sum(0))
        self.n = DECAY * self.n + q * len(Zq)
        assert len(q) == K
        self.fit()


def decide(mdl, X):
    pr = mdl.predict(X)
    j = next((i for i in range(len(pr) - K_DC + 1) if pr[i] != REST and (pr[i:i + K_DC] == pr[i]).all()), None)
    if j is None:
        return None, None
    end = j
    while end + 1 < len(pr) and pr[end + 1] == pr[j]:
        end += 1
    return int(pr[j]), X[j:end + 1]


def replay(day, sname, cond):
    """-> per probe a list of (cue, true, preds); command counts in the task trials"""
    classes = SETS[sname]
    F = day['F']
    mdl = Model(F, day['cal_rows'], day['cal_lab'], classes)
    probes = {}
    cmd = dict(trials=0, cmd=0, ok=0, miss=0)
    for _, kind, pay in day['events']:
        if kind == 'probe':
            probes[pay] = [(ci, g, mdl.predict(F[w])) for ci, (w, g) in enumerate(day['probes'][pay]) if g in classes]
        elif kind == 'trial':
            w, g = pay
            if g not in classes:
                continue
            cmd['trials'] += 1
            pred, X = decide(mdl, F[w])
            if pred is None:
                cmd['miss'] += 1
                continue
            cmd['cmd'] += 1
            cmd['ok'] += int(pred == g)
            if cond == 'cue_soft':
                mdl.soft(X, g)
    return [probes[k] for k in sorted(probes)], cmd


def win_acc(items):
    return 100 * np.concatenate([pr == g for _, g, pr in items]).mean() if items else float('nan')


def summarize(items, rng):
    cue = np.array([np.mean(pr == g) for _, g, pr in items])
    maj = np.array([np.bincount(pr, minlength=9).argmax() == g for _, g, pr in items])
    boot = [cue[rng.integers(0, len(cue), len(cue))].mean() for _ in range(2000)]
    return win_acc(items), 100 * maj.mean(), 100 * np.percentile(boot, 2.5), 100 * np.percentile(boot, 97.5)


def boot_d(soft, cue, rng, n=2000):
    """bootstrap over the cues of P1 and P2: D = mean over the two probes of (acc_soft - acc_cue)"""
    ds = []
    for _ in range(n):
        v = []
        for ps, pc in zip(soft, cue):
            k = rng.integers(0, len(ps), len(ps))
            a = np.concatenate([ps[i][2] == ps[i][1] for i in k]).mean()
            b = np.concatenate([pc[i][2] == pc[i][1] for i in k]).mean()
            v.append(100 * (a - b))
        ds.append(np.mean(v))
    return np.percentile(ds, [2.5, 97.5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--cal-s', type=float, default=4.0)
    args = ap.parse_args()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    rng = np.random.default_rng(0)
    days = [load_day(args.dir, n, args.cal_s) for n in args.days]
    p(f'cued pass: first {args.cal_s:g} s of each cue; rule 1 threshold {THRESHOLD:g} %, rule 2 D_bar >= +2 (pre-registered)')
    for d in days:
        p(f"{d['name']}: rate {d['rate']:.1f} Hz, cued windows per gesture {d['cal_counts'].tolist()}, "
          f"probes {len(d['probes'])} with {[len(x) for x in d['probes']]} cues, task trials {d['trials']}")
    A = {s: [] for s in ORDER}
    D = {s: [] for s in ORDER}
    for d in days:
        p(f"\n== {d['name']}")
        p('rule 1, condition cue')
        p('set  classes  chance   window acc %   cue-majority %   95 % CI (cues)   per probe (window %)')
        res = {}
        for s in ORDER:
            res[s] = {c: replay(d, s, c) for c in ('cue', 'cue_soft')}
            pr_cue = res[s]['cue'][0]
            allc = [x for pr in pr_cue for x in pr]
            wa, ma, lo, hi = summarize(allc, rng)
            A[s].append(wa)
            p(f"{s}   {len(SETS[s]):7d}  {100 / len(SETS[s]):5.1f}   {wa:12.1f}   {ma:14.1f}   {lo:6.1f} - {hi:5.1f}    "
              + '  '.join(f'P{k} {win_acc(x):5.1f}' for k, x in enumerate(pr_cue)))
        cm = np.zeros((9, 9), int)
        for pr in res['S9']['cue'][0]:
            for _, g, pred in pr:
                np.add.at(cm[g], pred, 1)
        p('\nS9 confusion, cue (rows = cued gesture, columns = predicted; windows)')
        p(pd.DataFrame(cm, index=GESTURES, columns=[g[:6] for g in GESTURES]).to_string())
        rec = 100 * np.diag(cm) / np.maximum(cm.sum(1), 1)
        p('S9 recall %: ' + ', '.join(f'{g} {r:.0f}' for g, r in zip(GESTURES, rec)))
        p('\nrule 2: probe window accuracy % (cue -> cue_soft), D = mean over P1, P2 of (cue_soft - cue)')
        for s in ORDER:
            pc, ps = res[s]['cue'][0], res[s]['cue_soft'][0]
            if len(pc) < 3:
                p(f'{s}: fewer than 3 probes, no D')
                continue
            dd = np.mean([win_acc(ps[k]) - win_acc(pc[k]) for k in (1, 2)])
            lo, hi = boot_d([ps[1], ps[2]], [pc[1], pc[2]], rng)
            D[s].append(dd)
            p(f"{s}: " + '  '.join(f'P{k} {win_acc(pc[k]):5.1f} -> {win_acc(ps[k]):5.1f}' for k in range(len(pc)))
              + f'   D = {dd:+.2f} (bootstrap 95 % {lo:+.2f}, {hi:+.2f})')
        p('\noffline commands in the task trials (first run of 3 equal non-Rest windows)')
        for s in ORDER:
            for c in ('cue', 'cue_soft'):
                m = res[s][c][1]
                p(f"{s} {c:8s}: trials {m['trials']}, commands {m['cmd']}, right {m['ok']}, none {m['miss']}, "
                  f"command accuracy {100 * m['ok'] / max(m['cmd'], 1):.1f} %")
    mean = {s: float(np.mean(A[s])) for s in ORDER}
    ok = [s for s in ORDER if mean[s] >= THRESHOLD]
    p('\nrule 1, mean over days: ' + ', '.join(f'{s} {mean[s]:.1f} %' for s in ORDER))
    if ok:
        p(f'RULE 1 DECISION (pre-registered): {ok[0]} ({len(SETS[ok[0]])} gestures) is the largest set with A >= {THRESHOLD:g} %')
    else:
        best = max(ORDER, key=lambda s: mean[s])
        p(f'RULE 1 DECISION (pre-registered): no set reaches {THRESHOLD:g} %; best is {best} ({mean[best]:.1f} %): '
          'revise placement / gestures before the arm experiment')
    if D['S9']:
        dbar = float(np.mean(D['S9']))
        pos = sum(x > 0 for x in D['S9'])
        need = math.ceil(2 / 3 * len(D['S9']))
        verdict = 'GO' if dbar >= 2.0 and pos >= need else 'NO-GO'
        p(f'RULE 2 DECISION (pre-registered): S9 D_bar = {dbar:+.2f}, positive on {pos}/{len(D["S9"])} days '
          f'(need {need}) -> {verdict}')
        for s in ('S7', 'S5'):
            if D[s]:
                p(f'   (reported, not decided) {s} D_bar = {np.mean(D[s]):+.2f}')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f'selftest9_cal{args.cal_s:g}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
