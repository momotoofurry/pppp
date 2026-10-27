"""Larger pre-trained pool: keep more pre-trained trees in Flash and pick the 50 that suit the user at one-shot time.

The authors' 66-participant model has 200 trees (all truncated to depth 10). Today the first 50 are pruned with the
calibration and used. Here a pool of the first --pool trees is scored with the calibration only and the 50 best are
pruned and used; the 50 appended trees, self-calibration (K-Means without embedding) and class-balanced z-score
update are the v2 Python pipeline (as aug_sweep.py / zscore_sweep.run(zs = 'bal0.3', embed = 'none')).
Pruning re-labels nodes with the calibration rows, so the calibration accuracy after pruning hardly separates trees;
two scores are compared:
  raw  accuracy of the unpruned (depth-10) tree on the calibration rows
  cv   2-fold: per class the calibration rows are split into the first and second half in time; prune on one half,
       accuracy on the other, mean of both directions
Ties keep the original tree order. Variants: first (= v2), raw<pool>, cv<pool> for each --pools.
Flash of the pool (our table format, export_c.table_arrays, unpruned depth-10 trees) is written to the summary.
Writes results/pool_sweep.csv (per run and block) and results/pool_sweep_summary.csv (paired Wilcoxon over subjects
against 'first' at the same offset).
Usage (in the container): python src/pool_sweep.py [--jobs 19]
"""
import argparse
import copy
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_c  # noqa: E402
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
import zscore_sweep as Z  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC, BUF, MLN = SH.N, SH.DEPTH, SH.PREC, SH.BUF, SH.MLN
A = 0.3                                                              # z-score update rate (bal0.3)


def halves(yc):
    """per class: first half of its rows (in time) -> fold 0, second half -> fold 1"""
    fold = np.zeros(len(yc), int)
    for c in np.unique(yc):
        i = np.where(yc == c)[0]
        fold[i[len(i) // 2:]] = 1
    return fold


def tree_acc(mdl, X, y):
    """accuracy of every tree of mdl on (X, y), int16 as on the device"""
    return np.array([np.mean(P.predict(P.subset(mdl, [t]), X, PREC) == y) for t in range(len(mdl['left']))])


def score(trunc, pool, Xc, yc, how):
    sub = P.subset(trunc, range(pool))
    if how == 'raw':
        return tree_acc(sub, Xc, yc)
    fold = halves(yc)
    s = np.zeros(pool)
    for f in (0, 1):
        tr, te = fold == f, fold != f
        s += tree_acc(P.prune(sub, Xc[tr], yc[tr]), Xc[te], yc[te]) / 2
    return s


def run(subject, seed, shift, variant):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as zscore_sweep.run
    Xc_raw, yc, blocks, k_est = Z.load('arm_position', subject, shift)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    trunc = rf_size.truncate_depth(copy.deepcopy(pre), DEPTH)
    if variant == 'first':
        idx = np.arange(n_pre)
    else:
        how = 'raw' if variant.startswith('raw') else 'cv'
        pool = int(variant[len(how):])
        sc = score(trunc, pool, Xc, yc, how)
        idx = np.sort(np.argsort(-sc, kind='stable')[:n_pre])
    pruned = P.prune(P.subset(trunc, idx), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(pruned, app)
    mdl_sc = copy.deepcopy(mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    n_first = int(np.sum(idx < n_pre))                               # chosen trees that are also in the first 50
    for b, (X_raw, y) in enumerate(blocks):
        X = (X_raw - mu) / np.sqrt(var)
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rows.append(dict(subject=subject, seed=seed, shift=shift, variant=variant, block=b, k_est=k_est,
                         n_in_first50=n_first, acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding=None)
        if len(lab_pseudo) >= 10:
            new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH,
                             None, MLN)
            idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
            mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
        st = Z.balanced_stats(X_raw, lab_sc)                         # predicted classes, no labels
        if st is not None:
            mu = (1 - A) * mu + A * st[0]
            var = (1 - A) * var + A * st[1]
    return rows


def pool_flash_kb(pool):
    trunc = rf_size.truncate_depth(P.load_pretrain(S.DATASETS['arm_position'][0]), DEPTH)
    arrs = export_c.table_arrays(rf_size.compact_forest(P.subset(trunc, range(pool))), 'int16')
    types = [np.uint32, np.uint8, np.int16, np.uint16, np.uint16]   # as check_oneshot_c.pre_trees / pre_model.h
    return sum(np.asarray(a, dtype=t).nbytes for a, t in zip(arrs, types)) / 1024


def summarize(acc, flash):
    ps = acc.groupby(['shift', 'variant', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    nf = acc[acc.block == 0].groupby(['shift', 'variant']).n_in_first50.mean()
    out = []
    for sh in sorted(set(acc['shift'])):
        base = ps.loc[(sh, 'first')]
        for v in sorted(set(acc.variant), key=lambda v: (v != 'first', v)):
            cur = ps.loc[(sh, v)]
            pool = 50 if v == 'first' else int(v.lstrip('rawcv'))  # raw200 -> 200
            row = dict(shift=sh, variant=v, pool=pool, pool_flash_KB=flash[pool], in_first50=nf.loc[(sh, v)],
                       fixed=cur.acc_fixed.mean(), adapt=cur.acc_adapt.mean())
            for col, name in [('acc_fixed', 'fixed'), ('acc_adapt', 'adapt')]:
                d = cur[col] - base[col]
                row[f'{name}_vs_first'] = d.mean()
                row[f'{name}_better'] = int((d > 0).sum())
                row[f'{name}_p'] = wilcoxon(cur[col], base[col]).pvalue if np.any(d != 0) else 1.0
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pools', type=int, nargs='+', default=[100, 200])
    ap.add_argument('--scores', nargs='+', default=['raw', 'cv'], choices=['raw', 'cv'])
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.25, 0.5])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    variants = ['first'] + [f'{h}{p}' for h in args.scores for p in args.pools]
    flash = {p: pool_flash_kb(p) for p in [50] + args.pools}
    print('pool Flash KB (unpruned, depth 10):', {p: round(v, 1) for p, v in flash.items()}, flush=True)
    tasks = [(s, sd, sh, v) for sh in args.shifts for v in variants for sd in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'pool_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    s = summarize(acc, flash)
    s.to_csv(os.path.join(OUT, f'pool_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
