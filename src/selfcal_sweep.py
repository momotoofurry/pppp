"""Self-calibration accuracy of compressed RF configurations (arm_position, 20 subjects x 11 blocks).

Re-implements the self-calibration loop of upstream main_replay_arm_position.py with the fast
helpers in pipeline.py; buffer_update / manifold_clustering / replace are the upstream
emg_functions functions, called unchanged. For a config (N trees, max_depth, precision):
  1. truncate the 66-participant pre-trained forest to max_depth, prune it with the calibration
     data, keep the first N//2 trees
  2. append N - N//2 trees trained on the calibration data (same max_depth) -> one-shot model
  3. for every test block: predict with the self-calibrating model, push block + predictions into
     the 1500-sample buffer, pseudo-label with t-SNE (3-D, perplexity 10) + K-Means
     (min_sample_class 10), train round(0.4 * n_app) new trees (same max_depth) on
     pseudo-labelled buffer + calibration data and replace that many randomly chosen appended trees
     (pre-trained part is never replaced). N = 400: 200 appended, 80 replaced, as upstream.
All predictions, including the ones manifold_clustering makes internally, use the config's
precision (int16 = Q5.10 features and thresholds). New trees are trained in float64.

Randomness follows upstream: RandomForestClassifier / TSNE / permutation all draw from numpy's
global RNG, seeded per (seed, subject) with np.random.seed.

Writes results/selfcal_sweep.csv (per subject/block), results/selfcal_sweep_summary.csv and
results/selfcal_sweep_trees.csv (node counts of the appended trees after the last block).
Usage: .venv/Scripts/python src/selfcal_sweep.py [--seeds 0 1 2] [--jobs 20] [--configs 0 1 2 ...] [--suffix _x]
       .venv/Scripts/python src/selfcal_sweep.py --merge _validation _compressed   (summary only)
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
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
# (N trees, max_depth, precision); the first one is the upstream model, used for validation
CONFIGS = [(400, None, 'float64'), (400, None, 'float32'), (400, 10, 'int16'), (100, 10, 'int16'),
           (50, 8, 'int16'), (20, 10, 'int16')]
BUFFER = 30 * 10 * 5        # max_sample_buffer
MIN_SAMPLE_CLASS = 10
LABELS = [0, 1, 2, 3, 4, 5]
REPLACE_FRAC = 0.4          # upstream: 80 of 200 appended trees


def cfg_name(N, d, prec):
    return f'N{N}_d{d if d else "none"}_{prec}'


def run_subject(subject, N, d, prec, seed):
    # manifold_clustering calls emg_functions.get_predictions internally; replace it (in this worker
    # process only, upstream file untouched) with the vectorised version at this config's precision.
    # manifold_clustering only uses the label, so no score is returned.
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), prec), None)
    np.random.seed(seed * 1000 + subject)
    Xc, yc, blocks = P.load_subject(subject)
    pre = P.load_pretrain()
    n_pre, n_app = N // 2, N - N // 2
    n_upd = int(round(REPLACE_FRAC * n_app))
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), d), Xc, yc)
    app = P.train_rf(Xc, yc, n_app, d, None)          # random_state=None -> global RNG, as upstream
    mdl_prune_append = emg_functions.append(P.subset(pruned, range(n_pre)), app)
    mdl_sc = copy.deepcopy(mdl_prune_append)

    feat_buf = np.zeros((0, Xc.shape[1]))
    lab_buf = np.zeros((0,))
    rows = []
    for b, (X, y) in enumerate(blocks):
        lab_os = P.predict(mdl_prune_append, X, prec)
        lab_sc = P.predict(mdl_sc, X, prec)
        rows.append(dict(config=cfg_name(N, d, prec), n_trees=N, max_depth=d if d else 'none', precision=prec,
                         seed=seed, subject=subject, block=b, acc_oneshot=np.mean(lab_os == y),
                         acc_selfcal=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUFFER, feat_buf, lab_buf, X, lab_sc)
        # Upstream behaviour (kept on purpose): the pseudo-labels that seed the K-Means centres come
        # from the ORIGINAL one-shot model mdl_prune_append, not from the current self-calibrated
        # model. The buffer itself holds the self-calibrated model's predictions, but
        # manifold_clustering re-predicts the whole buffer with the model it is given.
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(LABELS), MIN_SAMPLE_CLASS, mdl_prune_append, 'kmeans', embedding='tsne')
        new = P.train_rf(np.concatenate([feat_sel, Xc]), np.concatenate([lab_pseudo, yc]), n_upd, d, None)
        idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
        mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)

    st_app = rf_size.forest_stats(P.subset(mdl_sc, range(n_pre, N)))
    st_all = rf_size.forest_stats(mdl_sc)
    st_os = rf_size.forest_stats(P.subset(mdl_prune_append, range(n_pre, N)))
    thr = 'int16' if prec == 'int16' else 'float32'
    tree = dict(config=cfg_name(N, d, prec), seed=seed, subject=subject,
                app_nodes_mean=np.mean([s['nodes'] for s in st_app]),
                app_nodes_max=max(s['nodes'] for s in st_app),
                app_internal_mean=np.mean([s['internal'] for s in st_app]),
                app_depth_max=max(s['depth'] for s in st_app),
                oneshot_app_nodes_mean=np.mean([s['nodes'] for s in st_os]),
                total_nodes=sum(s['nodes'] for s in st_all),
                compact_B=rf_size.forest_bytes(st_all, thr)['compact'],
                oneshot_compact_B=rf_size.forest_bytes(rf_size.forest_stats(mdl_prune_append), thr)['compact'])
    return rows, tree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    ap.add_argument('--jobs', type=int, default=20)
    ap.add_argument('--subjects', type=int, nargs='+', default=list(range(20)))
    ap.add_argument('--configs', type=int, nargs='+', default=list(range(len(CONFIGS))))
    ap.add_argument('--suffix', default='')
    ap.add_argument('--merge', nargs='+', default=None,
                    help='no run: concatenate selfcal_sweep<suffix>.csv files with these suffixes, write --suffix')
    args = ap.parse_args()
    t0 = time.time()
    sfx = args.suffix
    if args.merge:
        def rd(name):
            return pd.concat([pd.read_csv(os.path.join(OUT, f'{name}{m}.csv'), keep_default_na=False)
                              for m in args.merge])
        acc, trees = rd('selfcal_sweep'), rd('selfcal_sweep_trees')
    else:
        tasks = [(s, *CONFIGS[c], seed) for c in args.configs for seed in args.seeds for s in args.subjects]
        res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run_subject)(*t) for t in tasks)
        acc = pd.DataFrame([r for rows, _ in res for r in rows])
        trees = pd.DataFrame([t for _, t in res])
    acc.to_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), index=False, float_format='%.4f')
    trees.to_csv(os.path.join(OUT, f'selfcal_sweep_trees{sfx}.csv'), index=False, float_format='%.2f')

    key = ['config', 'n_trees', 'max_depth', 'precision']
    per_seed = acc.groupby(key + ['seed'], sort=False)[['acc_oneshot', 'acc_selfcal']].mean().reset_index()
    per_seed['gain'] = per_seed.acc_selfcal - per_seed.acc_oneshot
    g = per_seed.groupby(key, sort=False)
    s = pd.concat([g[['acc_oneshot', 'acc_selfcal', 'gain']].mean(),
                   g.acc_oneshot.min().rename('oneshot_seed_min'), g.acc_oneshot.max().rename('oneshot_seed_max'),
                   g.acc_selfcal.min().rename('selfcal_seed_min'), g.acc_selfcal.max().rename('selfcal_seed_max'),
                   g.gain.min().rename('gain_seed_min'), g.gain.max().rename('gain_seed_max')], axis=1) * 100
    s['n_seeds'] = g.size()
    t = trees.groupby('config', sort=False)
    for c in ['app_nodes_mean', 'oneshot_app_nodes_mean', 'app_internal_mean']:
        s[c] = t[c].mean().values
    s['app_nodes_max'] = t.app_nodes_max.max().values
    s['app_depth_max'] = t.app_depth_max.max().values
    s['compact_KB'] = t.compact_B.mean().values / 1024
    s['compact_KB_max'] = t.compact_B.max().values / 1024
    s['oneshot_compact_KB'] = t.oneshot_compact_B.mean().values / 1024
    s = s.reset_index()
    s.to_csv(os.path.join(OUT, f'selfcal_sweep_summary{sfx}.csv'), index=False, float_format='%.3f')
    pd.set_option('display.width', 250)
    print(s.round(2).to_string(index=False))
    print(f'took {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
