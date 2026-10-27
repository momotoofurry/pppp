"""Rotation augmentation of the day-1 calibration: does training on simulated strap offsets help at half a position?

The day-1 calibration EMG is rotated by fractional positions with the same raw-EMG model as shift_sweep.py --raw
(electrode at s = k + f records (1 - f) * electrode (c + k) + f * electrode (c + k + 1)), features from the C
extraction, normalised with the unrotated calibration statistics (the device keeps those). Labels are the calibration
labels. Caveat: the test offsets are simulated with the same mixing model, so this is an optimistic check of the idea,
not evidence that real strap offsets behave the same.
Pipeline otherwise = firmware v2 in Python (zscore_sweep.run with zs = 'bal0.3', embed = 'none'): start-up alignment,
pruning of 50 pre-trained trees on the unrotated calibration, 50 appended trees, self-calibration with K-Means on the
80 features, class-balanced z-score update.
Variants (--aug):
  none    no augmentation (= v2)
  app     the 50 appended trees are trained on calibration + rotations of -0.5 -0.25 0.25 0.5
  app25   as app with rotations -0.25 0.25 only (does it carry over to an unseen half position?)
  appsc   as app, and the augmented calibration is also the labelled set of every self-calibration update
          (device: the calibration set in RAM grows 5x)
Writes results/aug_sweep.csv (per run and block) and results/aug_sweep_summary.csv (paired Wilcoxon over subjects
against 'none' at the same offset).
Usage (in the container): python src/aug_sweep.py [--jobs 19]
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
AUG = {'none': ((), False), 'app': ((-0.5, -0.25, 0.25, 0.5), False), 'app25': ((-0.25, 0.25), False),
       'appsc': ((-0.5, -0.25, 0.25, 0.5), True)}
A = 0.3                                                              # z-score update rate (bal0.3)


def cal_rotated(subject, s):
    """C features of the day-1 calibration with the raw EMG rotated by s positions (cached)"""
    path = os.path.join(SH.CACHE, f'{subject}_cal{s:g}.npz')
    if not os.path.exists(path):
        X, y = SH.raw_features(subject, 'calibration', s)
        os.makedirs(SH.CACHE, exist_ok=True)
        np.savez(path + '.tmp.npz', X=X, y=y)
        os.replace(path + '.tmp.npz', path)
    z = np.load(path)
    return z['X'], z['y']


def run(subject, seed, shift, aug):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    np.random.seed(seed * 1000 + subject)                            # as zscore_sweep.run
    Xc_raw, yc, blocks, k_est = Z.load('arm_position', subject, shift)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    rots, aug_sc = AUG[aug]
    Xa, ya = [Xc], [yc]
    for s in rots:
        X, y = cal_rotated(subject, s)
        Xa.append((X - mu) / np.sqrt(var))
        ya.append(y)
    Xa, ya = np.concatenate(Xa), np.concatenate(ya)
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xa, ya, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    Xl, yl = (Xa, ya) if aug_sc else (Xc, yc)                        # labelled set of the self-calibration updates
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (X_raw, y) in enumerate(blocks):
        X = (X_raw - mu) / np.sqrt(var)
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rows.append(dict(subject=subject, seed=seed, shift=shift, aug=aug, block=b, k_est=k_est, n_cal=len(yl),
                         acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding=None)
        if len(lab_pseudo) >= 10:
            new = P.train_rf(np.concatenate([feat_sel, S.q16(Xl)]), np.concatenate([lab_pseudo, yl]), n_upd, DEPTH,
                             None, MLN)
            idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
            mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
        st = Z.balanced_stats(X_raw, lab_sc)                         # predicted classes, no labels
        if st is not None:
            mu = (1 - A) * mu + A * st[0]
            var = (1 - A) * var + A * st[1]
    return rows


def summarize(acc):
    ps = acc.groupby(['shift', 'aug', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    out = []
    for sh in sorted(set(acc['shift'])):
        base = ps.loc[(sh, 'none')]
        for aug in AUG:
            if (sh, aug) not in ps.index.droplevel(2):
                continue
            cur = ps.loc[(sh, aug)]
            row = dict(shift=sh, aug=aug, fixed=cur.acc_fixed.mean(), adapt=cur.acc_adapt.mean())
            for col, name in [('acc_fixed', 'fixed'), ('acc_adapt', 'adapt')]:
                d = cur[col] - base[col]
                row[f'{name}_vs_none'] = d.mean()
                row[f'{name}_better'] = int((d > 0).sum())
                row[f'{name}_p'] = wilcoxon(cur[col], base[col]).pvalue if np.any(d != 0) else 1.0
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--aug', nargs='+', default=list(AUG), choices=list(AUG))
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.25, 0.5, -0.5, 1])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    rots = sorted({s for a in args.aug for s in AUG[a][0]})
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    Parallel(n_jobs=args.jobs)(delayed(cal_rotated)(s, r) for r in rots for s in args.subjects)
    print(f'features ready after {time.time() - t0:.0f} s', flush=True)
    tasks = [(s, sd, sh, a) for sh in args.shifts for a in args.aug for sd in args.seeds for s in args.subjects]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'aug_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    s = summarize(acc)
    s.to_csv(os.path.join(OUT, f'aug_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print('calibration rows:', acc.groupby('aug').n_cal.mean().to_dict())
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
