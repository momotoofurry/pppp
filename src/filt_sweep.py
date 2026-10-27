"""Pseudo-label filtering: train the new trees only on buffer rows where the K-Means label agrees with the forest.

Pipeline = firmware v2 in Python (as aug_sweep.py with no augmentation: start-up alignment, class-balanced z-score
update a = 0.3, self-calibration with K-Means on the 80 features, upstream manifold_clustering). After clustering,
the selected buffer rows are filtered before the 20 new trees are trained (no update if fewer than 10 rows are left):
  none   all selected rows (= v2)
  os     K-Means label == the one-shot model's vote on the row (the model that re-labels the buffer upstream)
  sc     K-Means label == the current self-calibrated model's vote
  both   K-Means == one-shot == self-calibrated
Device cost: one more forest pass over the <= 375 selected rows per block (no extra RAM beyond a 375-byte mask).
Also recorded per block: share of selected rows kept, and the accuracy of the kept pseudo-labels (true labels are
carried next to the buffer for this diagnostic only).
Writes results/filt_sweep.csv (per run and block) and results/filt_sweep_summary.csv (paired Wilcoxon over subjects
against 'none' at the same offset).
Usage (in the container): python src/filt_sweep.py [--jobs 19]
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
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import shift_sweep as SH  # noqa: E402
import zscore_sweep as Z  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC, BUF, MLN = SH.N, SH.DEPTH, SH.PREC, SH.BUF, SH.MLN
FILTERS = ['none', 'os', 'sc', 'both']
A = 0.3                                                              # z-score update rate (bal0.3)


def truth_of(feat_sel, truth):
    """true label of every selected row (rows are copied unchanged from the buffer, which is not a FIFO: upstream
    buffer_update evicts rows of the most frequent label, so rows are looked up by content)"""
    return np.array([truth[r.tobytes()] for r in feat_sel])


def run(subject, seed, shift, filt):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as zscore_sweep.run
    Xc_raw, yc, blocks, k_est = Z.load('arm_position', subject, shift)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    truth = {}                                                       # row bytes -> true label (diagnostic only)
    rows = []
    for b, (X_raw, y) in enumerate(blocks):
        X = (X_raw - mu) / np.sqrt(var)
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rec = dict(subject=subject, seed=seed, shift=shift, filt=filt, block=b, k_est=k_est,
                   acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y))
        Xq = S.q16(X)
        truth.update({r.tobytes(): t for r, t in zip(Xq, y)})
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, Xq, lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding=None)
        keep = np.ones(len(lab_pseudo), bool)
        if filt in ('os', 'both'):
            keep &= P.predict(mdl_os, feat_sel, PREC) == lab_pseudo
        if filt in ('sc', 'both'):
            keep &= P.predict(mdl_sc, feat_sel, PREC) == lab_pseudo
        tr = truth_of(feat_sel, truth)
        rec.update(n_selected=len(lab_pseudo), kept=keep.mean() if len(keep) else np.nan,
                   pseudo_acc_all=np.mean(lab_pseudo == tr) if len(tr) else np.nan,
                   pseudo_acc_kept=np.mean(lab_pseudo[keep] == tr[keep]) if keep.any() else np.nan)
        rows.append(rec)
        if keep.sum() >= 10:
            new = P.train_rf(np.concatenate([feat_sel[keep], S.q16(Xc)]), np.concatenate([lab_pseudo[keep], yc]),
                             n_upd, DEPTH, None, MLN)
            idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
            mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
        st = Z.balanced_stats(X_raw, lab_sc)                         # predicted classes, no labels
        if st is not None:
            mu = (1 - A) * mu + A * st[0]
            var = (1 - A) * var + A * st[1]
    return rows


def summarize(acc):
    ps = acc.groupby(['shift', 'filt', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    diag = acc.groupby(['shift', 'filt'])[['kept', 'pseudo_acc_all', 'pseudo_acc_kept']].mean()
    out = []
    for sh in sorted(set(acc['shift'])):
        base = ps.loc[(sh, 'none')]
        for f in FILTERS:
            if (sh, f) not in diag.index:
                continue
            cur = ps.loc[(sh, f)]
            d = cur.acc_adapt - base.acc_adapt
            out.append(dict(shift=sh, filt=f, adapt=cur.acc_adapt.mean(), adapt_vs_none=d.mean(),
                            adapt_better=int((d > 0).sum()),
                            adapt_p=wilcoxon(cur.acc_adapt, base.acc_adapt).pvalue if np.any(d != 0) else 1.0,
                            late=acc[(acc['shift'] == sh) & (acc.filt == f) & (acc.block >= 8)].acc_adapt.mean() * 100,
                            **(diag.loc[(sh, f)] * 100).to_dict()))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filters', nargs='+', default=FILTERS, choices=FILTERS)
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
    tasks = [(s, sd, sh, f) for sh in args.shifts for f in args.filters for sd in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'filt_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    s = summarize(acc)
    s.to_csv(os.path.join(OUT, f'filt_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
