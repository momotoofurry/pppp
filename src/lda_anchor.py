"""LDA comparators for the per-session update (report 35.9): what does the classic short re-calibration of an LDA give
on the same windows as the leaf counters? Exploratory, PC only.

Most published short re-calibrations adapt an LDA (class means from a few new samples, covariance kept or mixed).
Conditions, all scored exactly as leaf_sweep.py (anchor = first trial of each gesture of a block, never scored;
development data blocks 1..10):
  LDAfix    sklearn LDA (default solver, as upstream main_replay_arm_position.py) on the day-1 calibration (60
            windows), day-1 z-score, never updated                                   = the paper's LDA baseline
  LDAfixS   as LDAfix but with Ledoit-Wolf shrinkage (lsqr, 'auto'): is the paper's LDA baseline weak only because
            60 windows in 80 dimensions give a singular covariance?
  LDAfixSz  LDAfixS + the z-score moved towards the anchor's statistics before each block (a = 0.3, as the leaf
            counters), model unchanged
  LDAr      a new LDA from the anchor of every block (its own z-score), 60 windows   = counterpart of R
  LDAcum    LDA from the day-1 calibration + all anchors so far, each set normalised with its own statistics, the
            block with the current anchor's statistics                               = counterpart of Rcum
  LDApool   'pre-trained' LDA: within-class covariance pooled over the OTHER subjects of the data set (all their
            calibration + test windows, z-scored per subject and folder with that folder's statistics), class
            means from the user's day-1 calibration + all anchors so far (as LDAcum). Leave-one-subject-out, so
            the user's data never enters the covariance. On Kyranou the covariance comes from all 20 arm_position
            subjects.
LDA with 60-120 windows in 80 dimensions has a singular covariance: LDAr / LDAcum use sklearn's lsqr solver with
Ledoit-Wolf shrinkage ('auto'); LDAfix keeps the upstream default (svd) so that it reproduces the paper's baseline.
Writes results/lda_anchor.csv, lda_anchor_summary.csv (paired with F and the leaf / RF conditions of leaf_sweep.csv)
and lda_anchor_external.csv.
Usage (container; Kyranou at /data): python src/lda_anchor.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CONDS = ['LDAfix', 'LDAfixS', 'LDAfixSz', 'LDAr', 'LDAcum', 'LDApool']
REF = ['F', 'A', 'LAonly_a8_za', 'R', 'Rcum']
RIDGE = 1e-6


def zs(X):
    return (X - X.mean(0)) / X.std(0)


def within_cov(X, y):
    """sum of within-class scatter and its degrees of freedom"""
    S, n = np.zeros((X.shape[1], X.shape[1])), 0
    for c in np.unique(y):
        Z = X[y == c] - X[y == c].mean(0)
        S += Z.T @ Z
        n += len(Z) - 1
    return S, n


def pooled_cov(subjects, shift):
    S, n = 0.0, 0
    for s in subjects:
        Xc, yc, blocks, _ = ZW.load('arm_position', s, shift)
        for X, y in [(Xc, yc)] + list(blocks):
            a, b = within_cov(zs(X), np.asarray(y).astype(np.int64))
            S, n = S + a, n + b
    return S / n


class MeanLDA:
    """LDA with a given covariance: only the class means come from the user's labelled windows"""

    def __init__(self, cov):
        self.P = np.linalg.inv(cov + RIDGE * np.eye(len(cov)))

    def fit(self, X, y):
        self.m = np.stack([X[y == c].mean(0) for c in range(LS.K)])
        self.b = -0.5 * np.einsum('kd,de,ke->k', self.m, self.P, self.m)
        return self

    def predict(self, X):
        return np.argmax(X @ self.P @ self.m.T + self.b, axis=1)


def run(cond, Xc_raw, yc, blocks, cov=None):
    rows = []
    fixed = cond.startswith('LDAfix')
    if fixed:
        mu, var = Xc_raw.mean(0), Xc_raw.var(0)
        sd = np.sqrt(var)
        mdl = (LinearDiscriminantAnalysis() if cond == 'LDAfix' else
               LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')).fit((Xc_raw - mu) / sd, yc)
    pool = [(zs(Xc_raw), yc)]
    mdl_last = None
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        if cond == 'LDAfixSz' and len(ya):
            st = ZW.balanced_stats(Xa, ya)
            mu = (1 - LS.A_Z) * mu + LS.A_Z * st[0]
            var = (1 - LS.A_Z) * var + LS.A_Z * st[1]
            sd = np.sqrt(var)
        if not fixed:
            if len(ya):
                mu, sd = Xa.mean(0), Xa.std(0)
                pool.append(((Xa - mu) / sd, ya))
                if cond == 'LDAr':
                    mdl_last = LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto').fit(*pool[-1])
                else:
                    X = np.concatenate([x for x, _ in pool])
                    y = np.concatenate([t for _, t in pool])
                    mdl_last = (LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto') if cond == 'LDAcum'
                                else MeanLDA(cov)).fit(X, y)
            mdl = mdl_last
        acc = np.mean(mdl.predict((Xu - mu) / sd) == yu)
        rows.append(dict(block=b, acc=acc, n=len(yu)))
    return rows


def job_dev(subject, seed, shift):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    cov = pooled_cov([s for s in range(20) if s != subject], shift)
    out = []
    for stream in ('base', 'rest2'):
        blk = []
        for b, (X, y) in enumerate(blocks):
            y = y.astype(np.int64)
            a, u = LS.anchor_split(y)
            if stream == 'rest2' and b > 0:
                u = u[np.isin(y[u], LS.REST2)]
            blk.append((X[a], y[a], X[u], y[u]))
        for cond in CONDS:
            out += [dict(subject=subject, seed=seed, shift=shift, stream=stream, cond=cond, **r)
                    for r in run(cond, Xc_raw, yc, blk, cov)]
    return out


def job_ext(data, p, seed, cov):
    import external_check as EC
    import leaf_external as LE
    import selfcal_sweep as S
    from pipeline import emg_functions
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = [EC.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    mdl, Xc, yc, _ = LE.calibrate(d1[0], p, seed, P.load_pretrain(S.DATASETS['arm_position'][0]))
    if mdl is None:
        return []
    tests = {'A1': EC.stream(d2, 5, EC.ROW1, 0), 'A2_row1': EC.stream(d1[1:], 5, EC.ROW1, 0),
             'A2_row2': EC.stream(d1[1:], 5, EC.ROW2, 0)}
    out = []
    for comp, blocks in tests.items():
        blk = LE.with_anchor(blocks)
        for cond in CONDS:
            out += [dict(subject=p, seed=seed, comp=comp, cond=cond, **r) for r in run(cond, Xc, yc, blk, cov)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_anchor as M
    FC.lib()
    pd.set_option('display.width', 250)
    # LDA is deterministic: one run per subject and shift; copied to the three seeds so that it pairs with leaf_sweep
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.job_dev)(s, 0, sh) for sh in (0.0, 0.5) for s in range(20))
    one = pd.DataFrame([r for rs in res for r in rs])
    dev = pd.concat([one.assign(seed=k) for k in (0, 1, 2)], ignore_index=True)
    cov_all = pooled_cov(range(20), 0.0)
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(M.job_ext)(args.data, p, seed, cov_all) for p in range(1, 9)
                                                for seed in (0, 1, 2))
    ext = pd.DataFrame([r for rs in res for r in rs])
    dev.to_csv(os.path.join(OUT, 'lda_anchor.csv'), index=False, float_format='%.4f')
    ext.to_csv(os.path.join(OUT, 'lda_anchor_external.csv'), index=False, float_format='%.4f')

    ref = pd.read_csv(os.path.join(OUT, 'leaf_sweep.csv'))
    a = pd.concat([dev, ref[ref.cond.isin(REF)]], ignore_index=True)
    a = a[a.block >= 1]
    ps = (a.groupby(['shift', 'stream', 'cond', 'subject']).acc.mean() * 100).unstack('cond')
    rows = []
    for (sh, st), g in ps.groupby(level=[0, 1]):
        for c in REF + CONDS:
            row = dict(shift=sh, stream=st, cond=c, acc=g[c].mean())
            for r in ('F', 'LAonly_a8_za'):
                d = g[c] - g[r]
                m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
                row.update({f'vs_{r}': m, f'vs_{r}_lo': lo, f'vs_{r}_hi': hi, f'vs_{r}_worst': d.min()})
            rows.append(row)
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'lda_anchor_summary.csv'), index=False, float_format='%.4g')
    print(sm.round(2).to_string(index=False))

    refx = pd.read_csv(os.path.join(OUT, 'leaf_external.csv'))
    e = pd.concat([ext, refx[refx.cond.isin(REF)]], ignore_index=True)
    e['ok'] = e.acc * e.n
    acc = (e.groupby(['comp', 'cond', 'subject', 'seed'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100)
           .groupby(['comp', 'cond', 'subject']).acc.mean().unstack('cond'))
    rows = []
    for comp, g in acc.groupby(level='comp'):
        for c in [x for x in REF + CONDS if x in g]:
            row = dict(comp=comp, cond=c, acc=g[c].mean())
            for r in ('F', 'LAonly_a8_za'):
                d = g[c] - g[r]
                m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
                row.update({f'vs_{r}': m, f'vs_{r}_lo': lo, f'vs_{r}_hi': hi, f'vs_{r}_worst': d.min()})
            rows.append(row)
    sx = pd.DataFrame(rows)
    sx.to_csv(os.path.join(OUT, 'lda_anchor_external_summary.csv'), index=False, float_format='%.4g')
    print(sx.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
