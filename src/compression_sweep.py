"""Stage 2.3: compression sweep on the arm_position dataset (one-shot calibration, fixed model).

For every subject, max_depth d and total tree count N:
  1. truncate the 66-participant pre-trained forest to depth d
  2. prune it with the subject's calibration data (upstream emg_functions.prune)
  3. keep the first N//2 pruned trees (all 200 when N = 400)
  4. append N - N//2 trees trained on the calibration data with max_depth = d
  5. predict all 11 testing blocks with float32 and int16 (Q5.10) thresholds/features
"N = 400" is the paper's full model (200 pruned + 200 appended).

With --n-app K (variant B) the appended part is fixed at K trees and N_TREES instead lists the number
of pruned pre-trained trees kept (5..200); outputs get the suffix _app<K>.

Also records the size of trees trained on a self-calibration-like set (calibration + 1500 buffered
test samples labelled by the one-shot model's predictions; no t-SNE/K-Means), to estimate how big
the 80 replaced trees get after self-calibration. This is an approximation of the real pseudo-labels.

Writes results/sweep_acc.csv (per block), results/sweep_summary.csv, results/sweep_selfcal_trees.csv
Usage: .venv/Scripts/python src/compression_sweep.py [--seeds 0 1 2 3 4] [--jobs 20] [--n-app 200]
"""
import argparse
import copy
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import rf_size  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
DEPTHS = [6, 8, 10, 12, None]
N_TREES = [5, 10, 20, 50, 100, 400]
N_TREES_PRE = [5, 10, 20, 50, 100, 200]  # variant B: pre-trained trees kept
PRECISIONS = ['float32', 'int16']
N_SELFCAL_TREES = 80
BUFFER = 1500


def run_subject(subject, seeds, n_app_fixed=None):
    Xc, yc, blocks = P.load_subject(subject)
    Xt = np.concatenate([b[0] for b in blocks])
    yt = np.concatenate([b[1] for b in blocks])
    blk = np.concatenate([np.full(len(b[1]), i) for i, b in enumerate(blocks)])
    pre = P.load_pretrain()
    acc_rows, tree_rows = [], []
    for d in DEPTHS:
        pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), d), Xc, yc)
        for N in (N_TREES_PRE if n_app_fixed else N_TREES):
            if n_app_fixed:
                n_pre, N = N, N + n_app_fixed
            else:
                n_pre = 200 if N == 400 else N // 2
            pre_part = P.subset(pruned, range(n_pre))
            pre_stats = rf_size.forest_stats(pre_part)
            for seed in seeds:
                app = P.train_rf(Xc, yc, N - n_pre, d, seed * 100000 + subject * 100 + (d or 0))
                app_stats = rf_size.forest_stats(app)
                mdl = {k: pre_part[k] + app[k] for k in ['left', 'right', 'feature', 'threshold', 'value']}
                mdl['classes'] = pre['classes']
                for prec in PRECISIONS:
                    pred = P.predict(mdl, Xt, prec)
                    size = rf_size.forest_bytes(pre_stats + app_stats, prec)
                    size_pre = rf_size.forest_bytes(pre_stats, prec)
                    for b in range(len(blocks)):
                        m = blk == b
                        acc_rows.append(dict(
                            subject=subject, max_depth=d if d else 'none', n_trees=N, n_pre=n_pre, seed=seed,
                            precision=prec, block=b, accuracy=np.mean(pred[m] == yt[m]),
                            nodes=sum(s['nodes'] for s in pre_stats + app_stats),
                            internal=sum(s['internal'] for s in pre_stats + app_stats),
                            depth_max=max(s['depth'] for s in pre_stats + app_stats),
                            mean_leaf_depth=np.mean([s['mean_leaf_depth'] for s in pre_stats + app_stats]),
                            compact_B=size['compact'], naive_B=size['naive'],
                            compact_pre_B=size_pre['compact'], compact_app_B=size['compact'] - size_pre['compact']))
                if N == 400 and seed == seeds[0] and not n_app_fixed:
                    # self-calibration-like training set: calib + first 5 blocks with one-shot predictions
                    Xs = np.concatenate([Xt[:BUFFER], Xc])
                    ys = np.concatenate([P.predict(mdl, Xt[:BUFFER]), yc])
                    sc = rf_size.forest_stats(P.train_rf(Xs, ys, N_SELFCAL_TREES, d, seed + 7))
                    tree_rows.append(dict(
                        subject=subject, max_depth=d if d else 'none',
                        calib_tree_nodes=np.mean([s['nodes'] for s in app_stats]),
                        calib_tree_internal=np.mean([s['internal'] for s in app_stats]),
                        selfcal_tree_nodes=np.mean([s['nodes'] for s in sc]),
                        selfcal_tree_internal=np.mean([s['internal'] for s in sc]),
                        selfcal_tree_depth_max=max(s['depth'] for s in sc),
                        pruned_pre_tree_nodes=np.mean([s['nodes'] for s in pre_stats])))
    return acc_rows, tree_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--jobs', type=int, default=20)
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--n-app', type=int, default=None, help='variant B: fixed number of appended trees')
    args = ap.parse_args()
    sfx = f'_app{args.n_app}' if args.n_app else ''
    t0 = time.time()
    res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run_subject)(s, args.seeds, args.n_app) for s in args.subjects)
    acc = pd.DataFrame([r for a, _ in res for r in a])
    trees = pd.DataFrame([r for _, t in res for r in t])
    acc.to_csv(os.path.join(OUT, f'sweep_acc{sfx}.csv'), index=False, float_format='%.4f')
    if len(trees):
        trees.to_csv(os.path.join(OUT, 'sweep_selfcal_trees.csv'), index=False, float_format='%.2f')

    # summary: mean over blocks -> subjects -> seeds; size is averaged over subjects/seeds
    key = ['max_depth', 'n_trees', 'n_pre', 'precision']
    per = acc.groupby(key + ['seed', 'subject']).agg(accuracy=('accuracy', 'mean'), compact_B=('compact_B', 'first'),
                                                     naive_B=('naive_B', 'first'), nodes=('nodes', 'first'),
                                                     internal=('internal', 'first'), depth_max=('depth_max', 'first'),
                                                     mean_leaf_depth=('mean_leaf_depth', 'first'),
                                                     compact_pre_B=('compact_pre_B', 'first'),
                                                     compact_app_B=('compact_app_B', 'first')).reset_index()
    per_seed = per.groupby(key + ['seed']).agg(acc=('accuracy', 'mean')).reset_index()
    s = per.groupby(key).agg(acc_mean=('accuracy', 'mean'), acc_sd_subjects=('accuracy', 'std'),
                             compact_KB=('compact_B', 'mean'), compact_KB_max=('compact_B', 'max'),
                             naive_KB=('naive_B', 'mean'), naive_KB_max=('naive_B', 'max'),
                             compact_pre_KB=('compact_pre_B', 'mean'), compact_app_KB=('compact_app_B', 'mean'),
                             nodes=('nodes', 'mean'), internal=('internal', 'mean'),
                             depth_max=('depth_max', 'max'), mean_leaf_depth=('mean_leaf_depth', 'mean'))
    s['acc_seed_min'] = per_seed.groupby(key).acc.min()
    s['acc_seed_max'] = per_seed.groupby(key).acc.max()
    for c in [c for c in s.columns if c.endswith('KB') or c.endswith('KB_max')]:
        s[c] = s[c] / 1024
    for c in ['acc_mean', 'acc_sd_subjects', 'acc_seed_min', 'acc_seed_max']:
        s[c] = s[c] * 100
    s = s.reset_index()
    s.to_csv(os.path.join(OUT, f'sweep_summary{sfx}.csv'), index=False, float_format='%.3f')
    pd.set_option('display.width', 250)
    print(s[key + ['acc_mean', 'acc_seed_min', 'acc_seed_max', 'compact_KB', 'compact_KB_max', 'naive_KB',
                   'nodes', 'depth_max']].round(2).to_string(index=False))
    if len(trees):
        print('\nTree sizes (mean nodes per tree):')
        print(trees.groupby('max_depth', sort=False).mean(numeric_only=True).drop(columns='subject').round(1).to_string())
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
