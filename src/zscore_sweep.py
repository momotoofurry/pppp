"""Online update of the z-score statistics (label-free feature-statistics alignment) with and without self-calibration.

Today the features are z-scored with the mean / std of the day-1 calibration and never updated. Here the 80 means
and variances are updated after every test block from that block's (unlabelled) windows, and the next block is
normalised with the updated values (causal: block b is always normalised with statistics from blocks < b):
    mu <- (1 - a) mu + a mean(block),   var <- (1 - a) var + a var(block)
On the device this is two running vectors of 80 values (~640 B as int16 / float16), no labels.
Variants (--zs):
  none       day-1 statistics only (current pipeline)
  ema0.1 / ema0.3 / ema1   update rate a (ema1 = statistics of the last block only)
  ema0.3rest a = 0.3, but the statistics are taken from a Rest-heavy subset of the block (all Rest windows + a random
             subset of the others so that Rest is half of the windows) - the arm_position blocks are balanced over the
             six gestures, daily use is not; this checks how much an unbalanced gesture mix biases the update
Each run records the fixed one-shot model (acc_fixed: = "z-score update only" when zs != none) and the
self-calibrated model (acc_adapt) on the same blocks. The buffer keeps rows as they were normalised when stored
(as on the device); the calibration set used for new trees stays normalised with the day-1 statistics.
Data:
  arm_position  20 subjects x 11 blocks x 3 seeds, the authors' 66-participant model, C features, electrode-ring
                offsets --shifts (raw-EMG rotation as shift_sweep.py --raw, same cache) with the start-up alignment
                of shift_sweep.py (integer rotation from block 0) applied in every run
  demo          1 subject, 10 blocks over two days, model_pretrain.joblib (as upstream demo_replay.py), upstream
                features, 10 seeds, no offset
MCU setting as selfcal_sweep.py / shift_sweep.py: 100 trees, depth 10, int16, int16 buffer of 375, 20 new trees with
<= 32 leaves per block, t-SNE 500 iterations.
Writes results/zscore_sweep.csv (per run and block) and results/zscore_sweep_summary.csv.
Usage (in the container): python src/zscore_sweep.py [--jobs 19]
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
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
N, DEPTH, PREC, BUF, MLN, IT = SH.N, SH.DEPTH, SH.PREC, SH.BUF, SH.MLN, SH.IT
REST = 5                                                             # label_order: power lateral tripod pointer open rest
ZS = {'none': (0.0, False), 'ema0.1': (0.1, False), 'ema0.3': (0.3, False), 'ema1': (1.0, False),
      'ema0.3rest': (0.3, True)}


def load(dataset, subject, shift):
    """unnormalised calibration and blocks; arm_position with the start-up alignment applied"""
    if dataset == 'demo':
        Xc, yc = P.load_folder('demo', subject, 'calibration')
        blocks = [P.load_folder('demo', subject, f'testing_block{b}') for b in range(10)]
        return Xc, yc, blocks, 0
    z = np.load(SH.prepare(subject, shift))
    Xc, yc = z['Xc'], z['yc']
    blocks = [(z[f'X{b}'], z[f'y{b}']) for b in range(P.N_BLOCKS)]
    k = SH.estimate_rotation(Xc, blocks[0][0])
    return Xc, yc, [(SH.rotate(X, -k), y) for X, y in blocks], k


def stats_subset(X, y, rng):
    """Rest windows + random other windows so that Rest is half of the subset"""
    rest, other = np.where(y == REST)[0], np.where(y != REST)[0]
    keep = np.concatenate([rest, rng.choice(other, size=min(len(rest), len(other)), replace=False)])
    return X[keep]


def run(dataset, subject, seed, shift, zs):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), PREC), None)
    emg_functions.TSNE = S.tsne_with(IT, S.PERPLEXITY)
    np.random.seed(seed * 1000 + subject)
    rng = np.random.default_rng(seed * 7919 + subject)              # separate stream: the model RNG use is unchanged
    Xc_raw, yc, blocks, k_est = load(dataset, subject, shift)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    Xc = (Xc_raw - mu) / np.sqrt(var)
    pre = P.load_pretrain(S.DATASETS[dataset][0])
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(S.REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), DEPTH), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, DEPTH, None)
    mdl_os = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_os)
    a, rest_heavy = ZS[zs]
    feat_buf, lab_buf = np.zeros((0, Xc.shape[1])), np.zeros((0,))
    rows = []
    for b, (X_raw, y) in enumerate(blocks):
        X = (X_raw - mu) / np.sqrt(var)
        lab_os, lab_sc = P.predict(mdl_os, X, PREC), P.predict(mdl_sc, X, PREC)
        rows.append(dict(dataset=dataset, subject=subject, seed=seed, shift=shift, zs=zs, block=b, k_est=k_est,
                         acc_fixed=np.mean(lab_os == y), acc_adapt=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUF, feat_buf, lab_buf, S.q16(X), lab_sc)
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(S.LABELS), S.MIN_SAMPLE_CLASS, mdl_os, 'kmeans', embedding='tsne')
        if len(lab_pseudo) >= 10:
            new = P.train_rf(np.concatenate([feat_sel, S.q16(Xc)]), np.concatenate([lab_pseudo, yc]), n_upd, DEPTH,
                             None, MLN)
            idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
            mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)
        if a > 0:                                                    # statistics for the next block
            Xs = stats_subset(X_raw, y, rng) if rest_heavy else X_raw
            mu = (1 - a) * mu + a * Xs.mean(0)
            var = (1 - a) * var + a * Xs.var(0)
    return rows


def summarize(acc):
    ps = acc.groupby(['dataset', 'shift', 'zs', 'subject'])[['acc_fixed', 'acc_adapt']].mean() * 100
    out = []
    for (ds, sh), g in ps.groupby(level=[0, 1]):
        base = g.xs('none', level='zs').droplevel([0, 1])
        for zs in ZS:
            if zs not in g.index.get_level_values('zs'):
                continue
            cur = g.xs(zs, level='zs').droplevel([0, 1])
            row = dict(dataset=ds, shift=sh, zs=zs, n_subjects=len(cur), fixed=cur.acc_fixed.mean(),
                       adapt=cur.acc_adapt.mean())
            for col, name in [('acc_fixed', 'fixed'), ('acc_adapt', 'adapt')]:
                d = cur[col] - base[col]
                row[f'{name}_vs_none'] = d.mean()
                row[f'{name}_better'] = int((d > 0).sum())
                row[f'{name}_p'] = wilcoxon(cur[col], base[col]).pvalue if len(d) > 5 and np.any(d != 0) else np.nan
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zs', nargs='+', default=list(ZS), choices=list(ZS))
    ap.add_argument('--shifts', type=float, nargs='+', default=[0, 0.25, 0.5, 1])
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--demo-seeds', type=int, default=10)
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--no-demo', action='store_true')
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--suffix', default='')
    args = ap.parse_args()
    t0 = time.time()
    import check_features_c as FC
    FC.lib()
    Parallel(n_jobs=args.jobs)(delayed(SH.prepare)(s, sh) for sh in args.shifts for s in args.subjects)
    tasks = [('arm_position', s, seed, sh, zs) for sh in args.shifts for zs in args.zs for seed in args.seeds
             for s in args.subjects]
    if not args.no_demo:
        tasks += [('demo', 0, seed, 0.0, zs) for zs in args.zs for seed in range(args.demo_seeds)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run)(*t) for t in tasks)
    acc = pd.DataFrame([r for rows in res for r in rows])
    acc.to_csv(os.path.join(OUT, f'zscore_sweep{args.suffix}.csv'), index=False, float_format='%.4f')
    # demo: one subject, so the "subject" mean is over seeds; no paired test
    s = summarize(acc)
    s.to_csv(os.path.join(OUT, f'zscore_sweep_summary{args.suffix}.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(s.round(3).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
