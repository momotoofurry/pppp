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

--max-leaf-nodes / --min-samples-leaf limit the size of the trees trained in step 3 (the
self-calibration trees only; the one-shot appended trees of step 2 are unchanged, so one-shot
accuracy is identical to the unlimited run). Each value is run as its own variant, named
<config>_mln<L> / <config>_msl<k>; with max_leaf_nodes = L a new tree has at most L - 1 internal nodes.

--pseudo selects how the buffer is pseudo-labelled (each value is its own variant, named <config>_pl<mode>;
'tsne' is the upstream method and keeps the old names). All three call the unchanged upstream
manifold_clustering, using branches it already has:
  tsne    t-SNE (3-D) + K-Means                        embedding='tsne'           (paper: full model)
  kmeans  K-Means on the 80-D features, no t-SNE       embedding=None             (paper ablation "without t-SNE")
  none    no clustering: the model's predictions, class-balanced
          min_sample_class = inf, so manifold_clustering always takes its no-clustering branch
          (paper ablation "without K-Means and t-SNE")
As upstream, the model that labels the buffer is the original one-shot model (mdl_prune_append).

Randomness follows upstream: RandomForestClassifier / TSNE / permutation all draw from numpy's
global RNG, seeded per (seed, subject) with np.random.seed.

Writes results/selfcal_sweep.csv (per subject/block), results/selfcal_sweep_summary.csv and
results/selfcal_sweep_trees.csv (node counts of the appended trees after the last block).
Usage: .venv/Scripts/python src/selfcal_sweep.py [--seeds 0 1 2] [--jobs 20] [--configs 0 1 2 ...] [--suffix _x]
       .venv/Scripts/python src/selfcal_sweep.py --configs 3 --max-leaf-nodes 32 64 128 --min-samples-leaf 5 10 --suffix _leaf
       python src/selfcal_sweep.py --configs 0 3 --pseudo tsne kmeans none --suffix _pseudo
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
# pseudo-label mode -> (embedding, min_sample_class) passed to the upstream manifold_clustering
PSEUDO = {'tsne': ('tsne', MIN_SAMPLE_CLASS), 'kmeans': (None, MIN_SAMPLE_CLASS), 'none': (None, np.inf)}


def cfg_name(N, d, prec, mln=None, msl=1, pl='tsne'):
    return (f'N{N}_d{d if d else "none"}_{prec}' + (f'_mln{mln}' if mln else '') + (f'_msl{msl}' if msl > 1 else '')
            + (f'_pl{pl}' if pl != 'tsne' else ''))


def run_subject(subject, N, d, prec, seed, mln=None, msl=1, pl='tsne'):
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
        rows.append(dict(config=cfg_name(N, d, prec, mln, msl, pl), n_trees=N, max_depth=d if d else 'none',
                         precision=prec, new_max_leaf_nodes=mln if mln else 'none', new_min_samples_leaf=msl,
                         pseudo_label=pl,
                         seed=seed, subject=subject, block=b, acc_oneshot=np.mean(lab_os == y),
                         acc_selfcal=np.mean(lab_sc == y)))
        feat_buf, lab_buf = emg_functions.buffer_update(BUFFER, feat_buf, lab_buf, X, lab_sc)
        # Upstream behaviour (kept on purpose): the pseudo-labels that seed the K-Means centres come
        # from the ORIGINAL one-shot model mdl_prune_append, not from the current self-calibrated
        # model. The buffer itself holds the self-calibrated model's predictions, but
        # manifold_clustering re-predicts the whole buffer with the model it is given.
        embedding, min_class = PSEUDO[pl]
        feat_sel, lab_pseudo, lab_buf = emg_functions.manifold_clustering(
            feat_buf, list(LABELS), min_class, mdl_prune_append, 'kmeans', embedding=embedding)
        new = P.train_rf(np.concatenate([feat_sel, Xc]), np.concatenate([lab_pseudo, yc]), n_upd, d, None, mln, msl)
        idx_remain = np.concatenate([np.arange(n_pre), np.random.permutation(range(n_pre, N))[:n_app - n_upd]])
        mdl_sc = emg_functions.replace(mdl_sc, new, idx_remain)

    st_app = rf_size.forest_stats(P.subset(mdl_sc, range(n_pre, N)))
    st_all = rf_size.forest_stats(mdl_sc)
    st_os = rf_size.forest_stats(P.subset(mdl_prune_append, range(n_pre, N)))
    thr = 'int16' if prec == 'int16' else 'float32'
    tree = dict(config=cfg_name(N, d, prec, mln, msl, pl), seed=seed, subject=subject,
                app_nodes_mean=np.mean([s['nodes'] for s in st_app]),
                app_nodes_max=max(s['nodes'] for s in st_app),
                app_internal_mean=np.mean([s['internal'] for s in st_app]),
                app_internal_max=max(s['internal'] for s in st_app),
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
    ap.add_argument('--max-leaf-nodes', type=int, nargs='+', default=[],
                    help='one variant per value: limit self-calibration trees to this many leaves')
    ap.add_argument('--min-samples-leaf', type=int, nargs='+', default=[],
                    help='one variant per value: min_samples_leaf of self-calibration trees')
    ap.add_argument('--pseudo', nargs='+', default=['tsne'], choices=list(PSEUDO),
                    help='one variant per value: pseudo-labelling method (default: upstream t-SNE + K-Means)')
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
        variants = [(m, 1) for m in args.max_leaf_nodes] + [(None, k) for k in args.min_samples_leaf] or [(None, 1)]
        tasks = [(s, *CONFIGS[c], seed, *v, pl) for c in args.configs for pl in args.pseudo for v in variants
                 for seed in args.seeds for s in args.subjects]
        res = Parallel(n_jobs=args.jobs, verbose=5)(delayed(run_subject)(*t) for t in tasks)
        acc = pd.DataFrame([r for rows, _ in res for r in rows])
        trees = pd.DataFrame([t for _, t in res])
    acc.to_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), index=False, float_format='%.4f')
    trees.to_csv(os.path.join(OUT, f'selfcal_sweep_trees{sfx}.csv'), index=False, float_format='%.2f')

    for c, v in [('new_max_leaf_nodes', 'none'), ('new_min_samples_leaf', 1), ('pseudo_label', 'tsne')]:
        acc[c] = acc[c].fillna(v).replace('', v) if c in acc else v   # files from before the option
    key = ['config', 'n_trees', 'max_depth', 'precision', 'new_max_leaf_nodes', 'new_min_samples_leaf', 'pseudo_label']
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
    if 'app_internal_max' in trees:
        s['app_internal_max'] = t.app_internal_max.max().values
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
