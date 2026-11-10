"""Leaf refresh and anchor counters on the Kyranou 2025 recordings (external_check.py): a real re-donning (day 1 ->
day 2) and a real half-position offset (the second electrode ring). Consistency check only: this data was already
used to set rules (reports 24-27), and the conditions here were chosen on the development data (leaf_sweep.py).

Calibration as external_check.py: day 1 P5 session 1, the a-th trial of each gesture, a = the first try whose
verification passes (re-computed here with the Python one-shot model; same seeds as stress_check.model).
Anchor = the first trial of each gesture in the test stream (60 labelled windows, the cued start-up sequence of the
new session); it is removed from scoring for every condition, the rest of its block and the following blocks are
scored. There is one anchor per stream (one session start).
  A1       day 2 P5, both sessions (re-donned), channels 1-8
  A2_row1  day 1 P5 session 2, channels 1-8 (not re-donned: control)
  A2_row2  day 1 P5 session 2, channels 9-16 (the ring half a position away)
Conditions: see leaf_sweep.py (F, Z, A, Lall_w4_d1, LA_a8_za, LAonly_a8_za, LAonly_a8, R, Rcum). No start-up
alignment in any condition.
Writes results/leaf_external.csv and leaf_external_summary.csv.
Usage (container, data mounted at /data): python src/leaf_external.py [--jobs 16]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_features_c as FC  # noqa: E402
import external_check as EC  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CONDS = ['F', 'Z', 'A', 'Lall_w4_d1', 'LA_a8_za', 'LAonly_a8_za', 'LAonly_a8', 'R', 'Rcum']


def calibrate(s, p, seed, pre):
    rows, g = s.pick(5)
    yc = np.repeat(np.arange(6), EC.PER_TRIAL)
    for a in range(EC.VERIFY_TRIES):
        cal = [rows[np.flatnonzero(g == c)[a]] for c in range(6)]
        ver = [rows[np.flatnonzero(g == c)[a + 1]] for c in range(6)]
        Xc, Xv = s.features(cal, EC.ROW1, 0), s.features(ver, EC.ROW1, 0)
        np.random.seed(seed * 1000 + p)
        mu, sd = Xc.mean(0), Xc.std(0)
        mdl = LS.one_shot((Xc - mu) / sd, yc, pre)
        if np.mean(P.predict(mdl, (Xv - mu) / sd, LS.PREC) == yc) * 100 >= EC.VERIFY_PASS:
            return mdl, Xc, yc, a
    return None, None, None, -1


def with_anchor(blocks):
    out = []
    for b, (X, y) in enumerate(blocks):
        X, y = np.asarray(X, dtype=np.float64), np.asarray(y).astype(np.int64)
        if b == 0:
            a, u = LS.anchor_split(y)
        else:
            a, u = np.zeros(0, dtype=np.int64), np.arange(len(y))
        out.append((X[a], y[a], X[u], y[u]))
    return out


def job(data, p, seed):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = [EC.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    mdl, Xc, yc, a = calibrate(d1[0], p, seed, pre)
    if mdl is None:
        return []
    tests = {'A1': EC.stream(d2, 5, EC.ROW1, 0), 'A2_row1': EC.stream(d1[1:], 5, EC.ROW1, 0),
             'A2_row2': EC.stream(d1[1:], 5, EC.ROW2, 0)}
    out = []
    for comp, blocks in tests.items():
        blk = with_anchor(blocks)
        for cond in CONDS:
            np.random.seed(seed * 1000 + p + 1)
            if cond == 'A':
                rows = LS.run_retrain(mdl, Xc, yc, blk)
            elif cond == 'R':
                rows = LS.run_recal(pre, blk)
            elif cond == 'Rcum':
                rows = LS.run_recal(pre, blk, (Xc, yc))
            elif cond in LS.NEW:
                rows = LS.run_anchor(cond, mdl, Xc, blk)
            else:
                rows = LS.run_static(cond, mdl, Xc, blk)
            out += [dict(subject=p, seed=seed, comp=comp, cond=cond, cal_try=a, **r) for r in rows]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    ap.add_argument('--jobs', type=int, default=16)
    args = ap.parse_args()
    FC.lib()
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(job)(args.data, p, s) for p in EC.SUBJECTS for s in EC.SEEDS)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'leaf_external.csv'), index=False, float_format='%.4f')
    df['ok'] = df.acc * df.n
    acc = (df.groupby(['comp', 'cond', 'subject', 'seed'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100)
           .groupby(['comp', 'cond', 'subject']).acc.mean().unstack('cond'))
    rows = []
    for comp, g in acc.groupby(level='comp'):
        for cond in CONDS:
            row = dict(comp=comp, cond=cond, n=len(g), acc=g[cond].mean())
            for ref in ('F', 'R'):
                d = g[cond] - g[ref]
                m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
                row.update({f'vs{ref}': m, f'vs{ref}_lo': lo, f'vs{ref}_hi': hi, f'vs{ref}_worst': d.min(),
                            f'vs{ref}_better': int((d > 0).sum()), f'vs{ref}_worse': int((d < 0).sum())})
            rows.append(row)
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'leaf_external_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 260)
    pd.set_option('display.max_columns', 30)
    print(sm.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
