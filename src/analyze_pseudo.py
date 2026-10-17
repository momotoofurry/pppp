"""Compare pseudo-labelling methods for self-calibration (results of selfcal_sweep.py --pseudo, Docker runs).

Inputs (all produced in the Docker image, so they are comparable with each other):
  results/selfcal_sweep*_pseudo_c3.csv     100 trees / depth 10 / int16  x  tsne, kmeans, none
  results/selfcal_sweep*_pseudo_full.csv   400 trees / no limit / float64  x  kmeans, none
  results/selfcal_sweep*_validation_linux.csv  400 trees / float64 / tsne (Docker)
Writes results/pseudo_label_summary.csv and prints, per config and method: self-calibration accuracy
(mean of 3 seeds, seed range), gain over one-shot, paired difference vs. t-SNE + K-Means over 20 subjects
(seed-averaged, Wilcoxon signed-rank), appended-tree size after self-calibration, and the paper's
ablation number where one exists (Front. Neurorobot. 2024, Table 1).
Usage (repo root, in the container): python src/analyze_pseudo.py
"""
import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
PAPER = {'tsne': 84.6, 'kmeans': 81.0, 'none': 82.7}   # Table 1: full model / without t-SNE / without K-Means and t-SNE
NAMES = {'tsne': 't-SNE + K-Means', 'kmeans': 'K-Means only', 'none': 'no clustering'}


def load(sfx):
    acc = pd.read_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), keep_default_na=False)
    tr = pd.read_csv(os.path.join(OUT, f'selfcal_sweep_trees{sfx}.csv'), keep_default_na=False)
    if 'pseudo_label' not in acc:
        acc['pseudo_label'] = 'tsne'
    return acc, tr


def main():
    parts = [load(s) for s in ['_pseudo_c3', '_pseudo_full', '_validation_linux']]
    acc = pd.concat([a for a, _ in parts], ignore_index=True)
    tr = pd.concat([t for _, t in parts], ignore_index=True)
    acc['base'] = acc.n_trees.astype(str) + '_' + acc.max_depth.astype(str) + '_' + acc.precision
    rows = []
    for base, g in acc.groupby('base', sort=False):
        subj = g.groupby(['pseudo_label', 'seed', 'subject'])[['acc_oneshot', 'acc_selfcal']].mean() * 100
        ref = subj.loc['tsne'].groupby('subject').acc_selfcal.mean() if 'tsne' in subj.index.get_level_values(0) else None
        for pl in ['tsne', 'kmeans', 'none']:
            if pl not in subj.index.get_level_values(0):
                continue
            s = subj.loc[pl]
            per_seed = s.groupby('seed').mean()
            per_subj = s.groupby('subject').acc_selfcal.mean()
            cfg = g[g.pseudo_label == pl].config.iloc[0]
            t = tr[tr.config == cfg]
            row = dict(config=base, pseudo_label=pl, method=NAMES[pl], n_seeds=len(per_seed),
                       acc_oneshot=per_seed.acc_oneshot.mean(), acc_selfcal=per_seed.acc_selfcal.mean(),
                       selfcal_seed_min=per_seed.acc_selfcal.min(), selfcal_seed_max=per_seed.acc_selfcal.max(),
                       gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean(),
                       sd_subjects=per_subj.std(),
                       app_nodes_mean=t.app_nodes_mean.mean(), app_nodes_max=t.app_nodes_max.max(),
                       paper_ablation=PAPER[pl] if base.startswith('400_none') else np.nan)
            if ref is not None and pl != 'tsne':
                d = per_subj - ref
                row.update(diff_vs_tsne=d.mean(), diff_sd=d.std(), n_subjects_better=int((d > 0).sum()),
                           wilcoxon_p=wilcoxon(per_subj, ref).pvalue)
            rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'pseudo_label_summary.csv'), index=False, float_format='%.4f')
    pd.set_option('display.width', 250)
    print(df.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
