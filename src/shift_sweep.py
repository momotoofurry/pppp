"""Electrode rotation by one position (45 degrees on an 8-electrode ring): does self-calibration recover, and does it
fail like confidence-based self-training (Campbell et al., JNER 2024)?

Scenario: one-shot calibration with the original placement (day 1); every test block is recorded with the ring
rotated by `shift` electrodes (day 2 re-donning): channel c of the model now sees electrode (c + shift) mod 8, i.e.
the 10 features of each channel are moved to the neighbouring channel. The ring order is assumed to be 1..8 around
the forearm (not documented by the authors; channels 1-4 and 5-8 are each a chain of neighbours). The calibration
set kept from day 1 is not rotated (as on the device).
Setting = the recommended MCU configuration of selfcal_sweep.py with the authors' 66-participant model: 100 trees,
depth 10, int16, int16 buffer of 375, 20 new trees with <= 32 leaves per block, t-SNE 500 iterations.
Methods (each run also records the fixed one-shot model on the same blocks):
  tsne  the self-calibration of this work: upstream manifold_clustering (re-label the buffer with the original
        one-shot model, t-SNE + K-Means) -> pseudo-labels
  uhc   unsupervised high-confidence self-training (the UHC baseline of Campbell et al.): pseudo-label = the current
        self-calibrated model's own prediction, only buffer rows whose top-vote ratio >= --uhc-tau (0.6) are used;
        no update when fewer than 10 rows qualify
Both train the same 20 trees on (pseudo-labelled rows + calibration set) and replace 20 random appended trees.
Writes results/shift_sweep.csv (per subject/seed/shift/method/block) and results/shift_sweep_summary.csv.
Usage (in the container): python src/shift_sweep.py [--shifts 0 1 -1] [--seeds 0 1 2] [--jobs 19]
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
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N_FEAT = len(P.FEATS)
N, DEPTH, PREC, BUF, MLN, IT = 100, 10, 'int16', 375, 32, 500


def rotate(X, shift):
    """model channel c reads electrode (c + shift) mod 8: column f*8 + c <- f*8 + (c + shift) % 8"""
    if shift == 0:
        return X
    idx = [f * 8 + (c + shift) % 8 for f in range(N_FEAT) for c in range(8)]
    return X[:, idx]


def votes(mdl, X, precision):
    """P.predict, returning the vote counts per class (n x classes) instead of the argmax"""
    if precision == 'int16':
        Xp, thr = P.quantize(X), [P.quantize(t) for t in mdl['threshold']]
    else:
        Xp, thr = X, mdl['threshold']
    n = len(Xp)
    labels = P.leaf_labels(mdl)
    v = np.zeros((n, int(np.max(mdl['classes'])) + 1), dtype=np.int32)
    rows = np.arange(n)
    for left, right, feat, t, lab in zip(mdl['left'], mdl['right'], mdl['feature'], thr, labels):
        node = np.zeros(n, dtype=np.int64)
        active = left[node] > 0
        while active.any():
            idx = rows[active]
            nd = node[idx]
            go_left = Xp[idx, feat[nd]] < t[nd]
            node[idx] = np.where(go_left, left[nd], right[nd])
            active[idx] = left[node[idx]] > 0
        v[rows, lab[node]] += 1
    return v


def run(subject, seed, shift, method, uhc_tau):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    emg_functions.TSNE = S.tsne_with(IT, S.PERPLEXITY)
    np.random.seed(seed * 1000 + subject)
    Xc, yc, blocks = P.load_subject(subject)
    blocks = [(rotate(X, shift), y) for X, y in blocks]
    pre = P.load_pretrain()
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (X, y) in enumerate(blocks):
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rec = dict(subject=subject, seed=seed, shift=shift, method=method, block=b,
                   acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y), n_pseudo=np.nan, pseudo_acc=np.nan)
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        if method == 'tsne':
            feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
                feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding='tsne')
        else:
            v = votes(mdl_sc, feat_buf, PREC)
            ratio = v.max(axis=1) / v.sum(axis=1)
            keep = ratio >= uhc_tau
            feat_sel, lab_pseudo = feat_buf[keep], v.argmax(axis=1)[keep].astype(float)
        rec['n_pseudo'] = len(lab_pseudo)
        rows.append(rec)
        if len(lab_pseudo) < 10:
            continue
        new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH, None, MLN)
        idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
        mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shifts', type=int, nargs='+', default=[0, 1, -1])
    ap.add_argument('--methods', nargs='+', default=['tsne', 'uhc'], choices=['tsne', 'uhc'])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--uhc-tau', type=float, default=0.6)
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    tasks = [(s, seed, sh, m, args.uhc_tau) for sh in args.shifts for m in args.methods for seed in args.seeds
             for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'shift_sweep{args.suffix}.csv'), index=False, float_format='%.4f')

    # per subject (mean over seeds and blocks), in %
    ps = acc.groupby(['shift', 'method', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    out = []
    for sh in args.shifts:
        fixed = ps.loc[(sh, args.methods[0])].acc_fixed          # identical for both methods (same seed, same model)
        row = dict(shift=sh, fixed=fixed.mean())
        for m in args.methods:
            a = ps.loc[(sh, m)].acc_adapt
            d = a - fixed
            row[f'{m}'] = a.mean()
            row[f'{m}_minus_fixed'] = d.mean()
            row[f'{m}_better_than_fixed'] = int((d > 0).sum())
            row[f'{m}_p_vs_fixed'] = wilcoxon(a, fixed).pvalue if np.any(d != 0) else 1.0
            late = acc[(acc['shift'] == sh) & (acc.method == m) & (acc.block >= 8)].groupby('subject').acc_adapt.mean() * 100
            row[f'{m}_late_blocks'] = late.mean()
        if {'tsne', 'uhc'} <= set(args.methods):
            a, b = ps.loc[(sh, 'tsne')].acc_adapt, ps.loc[(sh, 'uhc')].acc_adapt
            row['tsne_minus_uhc'] = (a - b).mean()
            row['tsne_better_than_uhc'] = int((a - b > 0).sum())
            row['p_tsne_vs_uhc'] = wilcoxon(a, b).pvalue if np.any(a != b) else 1.0
        row['fixed_late_blocks'] = (acc[(acc['shift'] == sh) & (acc.method == args.methods[0]) & (acc.block >= 8)]
                                    .groupby('subject').acc_fixed.mean() * 100).mean()
        out.append(row)
    s = pd.DataFrame(out)
    s.to_csv(os.path.join(OUT, f'shift_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
