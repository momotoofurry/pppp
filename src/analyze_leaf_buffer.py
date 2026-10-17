"""Tree-size limits (selfcal_sweep.py ... --suffix _leaf) and buffer size / int16 buffer (--suffix _buffer),
100 trees / depth 10 / int16 with t-SNE + K-Means, Docker runs.

Baseline = the same model with upstream settings from the _pseudo_c3 run (Docker, t-SNE + K-Means, float
buffer of 1500). For every variant: self-calibration accuracy (mean of 3 seeds, seed range), gain over
one-shot, paired difference vs. baseline over 20 subjects (seed-averaged, Wilcoxon), the largest
replaceable-tree region seen (50 appended trees x (mean nodes - 1) / 2 x 7 B, max over subject x seed),
and the total self-calibration RAM estimate, computed exactly as in ram_estimate.py but with the
buffer-size-dependent items (buffer, pseudo-labels, RF training scratch, K-Means, t-SNE) scaled to the
variant's buffer. For max_leaf_nodes = L the tree region also has a hard bound: 50 x (L - 1) x 7 B.
Writes results/leaf_buffer_summary.csv. Usage (in the container): python src/analyze_leaf_buffer.py
"""
import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
N_FEAT, N_CLS, N_CALIB, NODE_B, N_APP = 80, 6, 60, 7, 50
INFER = 552                                   # arm_size.csv: d10_n100_i16 table, static RAM + stack
FEAT = 400 * 8 * 4 + 4 * 2 * 8 * 4 + 2 * 512 * 4 + 257 * 4   # feature extraction (ram_estimate.py)


def ram(buf, int16_buffer, trees_B):
    b = 2 if int16_buffer else 4
    n_train = buf + N_CALIB
    parts = dict(
        infer_feat=INFER + FEAT,
        buffer=buf * N_FEAT * b + N_CALIB * N_FEAT * b,
        pseudo_labels=buf,
        training=n_train * 2 + n_train * 4 + n_train * 2 + (2 ** 11) * NODE_B,
        kmeans=buf + 2 * N_CLS * N_FEAT * 4,
        tsne=buf * 31 * 6 + 4 * buf * 3 * 4 + buf * 40,
        trees=trees_B)
    return sum(parts.values()), parts


def load(sfx):
    acc = pd.read_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), keep_default_na=False)
    tr = pd.read_csv(os.path.join(OUT, f'selfcal_sweep_trees{sfx}.csv'), keep_default_na=False)
    return acc, tr


def main():
    base_acc, base_tr = load('_pseudo_c3')
    base_acc = base_acc[base_acc.config == 'N100_d10_int16']
    base_tr = base_tr[base_tr.config == 'N100_d10_int16']
    parts = [('baseline', base_acc, base_tr)]
    for sfx in ['_leaf', '_buffer']:
        if os.path.exists(os.path.join(OUT, f'selfcal_sweep{sfx}.csv')):
            a, t = load(sfx)
            parts.append((sfx[1:], a, t))
    ref = base_acc.groupby('subject').acc_selfcal.mean() * 100
    rows = []
    for exp, acc, tr in parts:
        for cfg, g in acc.groupby('config', sort=False):
            if exp == 'buffer' and cfg == 'N100_d10_int16':
                continue
            per_seed = g.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
            per_subj = g.groupby('subject').acc_selfcal.mean() * 100
            t = tr[tr.config == cfg]
            trees_B = (N_APP * (t.app_nodes_mean - 1) / 2 * NODE_B).max()
            buf = int(g['buffer'].iloc[0]) if 'buffer' in g and g['buffer'].iloc[0] != '' else 1500
            bq16 = str(g['buffer_int16'].iloc[0]) == 'True' if 'buffer_int16' in g else False
            mln = g['new_max_leaf_nodes'].iloc[0] if 'new_max_leaf_nodes' in g else 'none'
            msl = g['new_min_samples_leaf'].iloc[0] if 'new_min_samples_leaf' in g else 1
            total, pr = ram(buf, bq16, trees_B)
            row = dict(experiment=exp, config=cfg, max_leaf_nodes=mln, min_samples_leaf=msl, buffer=buf,
                       buffer_int16=bq16, acc_oneshot=per_seed.acc_oneshot.mean(), acc_selfcal=per_seed.acc_selfcal.mean(),
                       selfcal_seed_min=per_seed.acc_selfcal.min(), selfcal_seed_max=per_seed.acc_selfcal.max(),
                       gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean(),
                       app_internal_max=t.app_internal_max.max() if 'app_internal_max' in t else np.nan,
                       trees_KB=trees_B / 1024,
                       trees_bound_KB=(N_APP * (int(mln) - 1) * NODE_B / 1024) if str(mln) not in ('none', '') else np.nan,
                       tsne_KB=pr['tsne'] / 1024, buffer_KB=pr['buffer'] / 1024, total_KB=total / 1024)
            if exp != 'baseline':
                d = per_subj - ref
                row.update(diff_vs_baseline=d.mean(), n_subjects_better=int((d > 0).sum()),
                           wilcoxon_p=wilcoxon(per_subj, ref).pvalue if np.any(d != 0) else 1.0)
            rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'leaf_buffer_summary.csv'), index=False, float_format='%.5g')
    pd.set_option('display.width', 260)
    cols = ['experiment', 'config', 'acc_selfcal', 'selfcal_seed_min', 'selfcal_seed_max', 'gain', 'diff_vs_baseline',
            'n_subjects_better', 'wilcoxon_p', 'app_internal_max', 'trees_KB', 'trees_bound_KB', 'buffer_KB', 'tsne_KB',
            'total_KB']
    print(df[[c for c in cols if c in df]].round(3).to_string(index=False))


if __name__ == '__main__':
    main()
