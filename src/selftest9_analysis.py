"""Self-test with the 9 directional gestures (report 35.45, 2026-11-17): how many gestures can 4 sensors carry?

Recording (SOP 3B / 5, panel gesture set "9 方向", files <subj>_d<day>_G_*): TrignoBridge run --firmware lda --classes 9
(board: rtl_task_9c), a cued pass of the 9 gestures (cal 0-8, 4 s each, then calibrate), then TaskScreen --gestures nine
--segments labelled,labelled,labelled --reps 3 --postures selftest: three probes P0 (neutral), P1 (A then B),
P2 (C then A), each 3 x 9 cues of 2 s in a random order. Cued only: no task labels.

Gestures (class order of the firmware; Rest last):
  0 WristExt (up)  1 WristFlex (down)  2 RadialDev (left)  3 UlnarDev (right)  4 Point (forward)  5 ThumbUp (back)
  6 HandOpen (gripper open)  7 Fist (gripper close)  8 Rest (stop)
Gesture sets compared on the SAME recording (each one is a separate model, as if the board had been built for it):
  S9  all 9
  S7  without Point and ThumbUp (the single-finger gestures): 4 wrist directions + HandOpen + Fist + Rest
  S5  the 4 wrist directions + Rest (a mode switch would carry the rest of the commands)

Model per set and day, as on the board (rt_lda.c): the cued windows of the set's gestures (every accepted 'cal g' of
the cued pass, the last 30 windows of each = windows 9..38 after its stream reset; a redone gesture adds its windows
like the board's buffer) give the z-score of the session (mean, population SD); Q5.10; OAS-shrunk pooled covariance
LDA with equal priors (lda_robust.oas_solve). Test = the probe cues whose gesture is in the set: the middle 10 windows
of [cue_on + 0.5 s, cue_off] (selftest_analysis.mid / inside), argmax over the set's classes.

Primary measure: A(S) = window accuracy over all probe windows of the set's gestures (P0-P2 pooled), per day; mean over
days. Decision rule, fixed before the 9-gesture recording (2026-11-17, n = 1 self-test; picks the gesture set of the
next experiment, not a claim):
  choose the LARGEST set with A(S) >= 85 %; if none reaches 85 %, choose the set with the highest A(S) and revise the
  placement / gestures before the arm experiment.
Also reported: per probe, cue-level majority accuracy, a bootstrap 95 % interval over cues (2000 resamples), per-class
recall and the 9-class confusion matrix, chance level 1 / |S|, and the same with --cal-s 2 (first 2 s of each cue).

usage: python src/selftest9_analysis.py --dir D:/selftest_data/T00 --days T00_d1_G [T00_d2_G ...] [--out ...] [--cal-s 4]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import selftest_analysis as SA  # noqa: E402  (load_emg, features, inside, mid, q16, timing constants)

GESTURES = ['WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']
G = {g: i for i, g in enumerate(GESTURES)}
SETS = {
    'S9': list(range(9)),
    'S7': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'HandOpen', 'Fist', 'Rest')],
    'S5': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Rest')],
}
ORDER = ['S9', 'S7', 'S5']                      # largest first
THRESHOLD = 85.0
FS, WIN, STEP, WARMUP, REACT_S = SA.FS, SA.WIN, SA.STEP, SA.WARMUP, SA.REACT_S


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
    probes = []
    for idx in sorted(runs):
        run = runs[idx]
        if run['seg'] != 'labelled':
            continue
        on, items = {}, []
        for r in run['rows']:
            if r.event == 'cue_on':
                on[r.step] = r
            elif r.event == 'cue_off' and r.step in on:
                w = SA.mid(SA.inside(t0, nw, on[r.step].t + REACT_S * 1000, r.t))
                if len(w):
                    items.append((w, G[r.target]))
        probes.append(items)
    return dict(name=name, F=F, cal_rows=np.concatenate(cue_rows), cal_lab=np.concatenate(cue_lab), probes=probes,
                rate=rate, cal_counts=np.bincount(np.concatenate(cue_lab), minlength=9))


def fit(F, rows, lab, classes):
    keep = np.isin(lab, classes)
    Xc, yc = F[rows[keep]], lab[keep]
    mu, sd = Xc.mean(0), Xc.std(0)
    inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
    Zq = SA.q16((Xc - mu) * inv)
    K = len(classes)
    idx = np.array([classes.index(c) for c in yc])
    n = np.bincount(idx, minlength=K).astype(float)
    s = np.zeros((K, Zq.shape[1]))
    np.add.at(s, idx, Zq)
    m = s / n[:, None]
    N = n.sum()
    S = (Zq.T @ Zq - (m.T * n) @ m) / N
    w, b = LR.oas_solve(S, N, m)
    return dict(mu=mu, inv=inv, w=w, b=b, classes=classes)


def predict(mdl, X):
    sc = SA.q16((X - mdl['mu']) * mdl['inv']) @ mdl['w'].T + mdl['b']
    return np.array(mdl['classes'])[np.argmax(sc, 1)]


def evaluate(day, sname):
    classes = SETS[sname]
    mdl = fit(day['F'], day['cal_rows'], day['cal_lab'], classes)
    out = []                                    # (probe, cue, true, preds)
    for p, items in enumerate(day['probes']):
        for ci, (w, g) in enumerate(items):
            if g in classes:
                out.append((p, ci, g, predict(mdl, day['F'][w])))
    return out


def summarize(res, rng):
    win = np.concatenate([pr == g for _, _, g, pr in res])
    cue = np.array([np.mean(pr == g) for _, _, g, pr in res])
    maj = np.array([np.bincount(pr, minlength=9).argmax() == g for _, _, g, pr in res])
    boot = [cue[rng.integers(0, len(cue), len(cue))].mean() for _ in range(2000)]
    return 100 * win.mean(), 100 * maj.mean(), 100 * np.percentile(boot, 2.5), 100 * np.percentile(boot, 97.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--cal-s', type=float, default=4.0)
    args = ap.parse_args()
    lines = []

    def p(s=''):
        print(s)
        lines.append(s)

    rng = np.random.default_rng(0)
    days = [load_day(args.dir, n, args.cal_s) for n in args.days]
    p(f'cued pass: first {args.cal_s:g} s of each cue; threshold {THRESHOLD:g} % (pre-registered)')
    for d in days:
        p(f"{d['name']}: rate {d['rate']:.1f} Hz, cued windows per gesture {d['cal_counts'].tolist()}, "
          f"probes {len(d['probes'])} with {[len(x) for x in d['probes']]} cues")
    A = {s: [] for s in ORDER}
    for d in days:
        p(f"\n== {d['name']}")
        p('set  classes  chance   window acc %   cue-majority %   95 % CI (cues)   per probe (window %)')
        for s in ORDER:
            res = evaluate(d, s)
            wa, ma, lo, hi = summarize(res, rng)
            A[s].append(wa)
            per = [100 * np.concatenate([pr == g for pp, _, g, pr in res if pp == k]).mean()
                   for k in range(len(d['probes'])) if any(pp == k for pp, _, _, _ in res)]
            p(f"{s}   {len(SETS[s]):7d}  {100 / len(SETS[s]):5.1f}   {wa:12.1f}   {ma:14.1f}   {lo:6.1f} - {hi:5.1f}    "
              + '  '.join(f'P{k} {v:5.1f}' for k, v in enumerate(per)))
        res = evaluate(d, 'S9')
        cm = np.zeros((9, 9), int)
        for _, _, g, pr in res:
            np.add.at(cm[g], pr, 1)
        p('\nS9 confusion (rows = cued gesture, columns = predicted; windows)')
        p(pd.DataFrame(cm, index=GESTURES, columns=[g[:6] for g in GESTURES]).to_string())
        rec = 100 * np.diag(cm) / np.maximum(cm.sum(1), 1)
        p('S9 recall %: ' + ', '.join(f'{g} {r:.0f}' for g, r in zip(GESTURES, rec)))
    mean = {s: float(np.mean(A[s])) for s in ORDER}
    ok = [s for s in ORDER if mean[s] >= THRESHOLD]
    p('\nmean over days: ' + ', '.join(f'{s} {mean[s]:.1f} %' for s in ORDER))
    if ok:
        p(f'DECISION (pre-registered): {ok[0]} ({len(SETS[ok[0]])} gestures) is the largest set with A >= {THRESHOLD:g} %')
    else:
        best = max(ORDER, key=lambda s: mean[s])
        p(f'DECISION (pre-registered): no set reaches {THRESHOLD:g} %; best is {best} ({mean[best]:.1f} %): '
          'revise placement / gestures before the arm experiment')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f'selftest9_cal{args.cal_s:g}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
