"""Lower t-SNE perplexity (selfcal_sweep.py ... --tsne-iter 500 1000 --tsne-perplexity 3 5 7 --suffix _px), Docker run.

Model as in analyze_tsne_iter.py: 100 trees / depth 10 / int16, int16 buffer of 375, max_leaf_nodes 32.
Perplexity 10 (upstream) comes from the _iter run (500 and 1000 iterations). Reference = upstream
(perplexity 10, 1000 iterations). For every (perplexity, iterations): self-calibration accuracy (mean of 3
seeds, seed range), gain, paired difference vs. the reference over 20 subjects (seed-averaged, Wilcoxon),
the t-SNE neighbours (3 x perplexity + 1), the t-SNE RAM and total self-calibration RAM estimate (analyze_leaf_buffer.ram
with the neighbour table scaled; trees = largest run), and, if results/tsne_cost_px.csv exists
(tsne_cost.py --sizes 375 --iters 500 1000 --perplexities 3 5 7 10 --suffix _px), the PC single-thread t-SNE CPU time.
Writes results/tsne_px_summary.csv. Usage (in the container): python src/analyze_tsne_px.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_leaf_buffer as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
REF = (10.0, 1000)
BUF = 375


def load(sfx):
    acc = pd.read_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), keep_default_na=False)
    tr = pd.read_csv(os.path.join(OUT, f'selfcal_sweep_trees{sfx}.csv'), keep_default_na=False)
    if 'tsne_perplexity' not in acc:
        acc['tsne_perplexity'] = 10.0
    return acc, tr


def main():
    a1, t1 = load('_iter')
    a1, t1 = a1[a1.tsne_iter.isin([500, 1000])], t1[t1.config.isin(a1[a1.tsne_iter.isin([500, 1000])].config.unique())]
    a2, t2 = load('_px')
    acc, trees = pd.concat([a1, a2]), pd.concat([t1, t2])
    acc['tsne_perplexity'] = acc.tsne_perplexity.astype(float)
    ref = acc[(acc.tsne_perplexity == REF[0]) & (acc.tsne_iter == REF[1])]
    ref_subj = ref.groupby('subject').acc_selfcal.mean() * 100
    cpu = None
    if os.path.exists(os.path.join(OUT, 'tsne_cost_px.csv')):
        c = pd.read_csv(os.path.join(OUT, 'tsne_cost_px.csv'))
        cpu = c.groupby(['perplexity', 'max_iter']).agg(cpu_s=('cpu_s', 'mean'), n=('cpu_s', 'size'), k=('neighbours', 'max'))
    rows = []
    for (px, it), g in acc.groupby(['tsne_perplexity', 'tsne_iter'], sort=True):
        cfg = g.config.iloc[0]
        per_seed = g.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
        per_subj = g.groupby('subject').acc_selfcal.mean() * 100
        d = per_subj - ref_subj
        t = trees[trees.config == cfg]
        trees_B = (L.N_APP * (t.app_nodes_mean - 1) / 2 * L.NODE_B).max()
        k = int(3.0 * px + 1)
        total, parts = L.ram(BUF, True, trees_B, k)
        row = dict(config=cfg, perplexity=px, tsne_iter=it, neighbours=k, acc_selfcal=per_seed.acc_selfcal.mean(),
                   selfcal_seed_min=per_seed.acc_selfcal.min(), selfcal_seed_max=per_seed.acc_selfcal.max(),
                   gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean(),
                   diff_vs_ref=d.mean(), n_subjects_better=int((d > 0).sum()), n_subjects_worse=int((d < 0).sum()),
                   wilcoxon_p=wilcoxon(per_subj, ref_subj).pvalue if np.any(d != 0) else 1.0,
                   tsne_KB=parts['tsne'] / 1024, total_KB=total / 1024)
        if cpu is not None and (px, it) in cpu.index:
            row.update(tsne_cpu_s=cpu.loc[(px, it), 'cpu_s'], cost_subjects=int(cpu.loc[(px, it), 'n']))
        rows.append(row)
    df = pd.DataFrame(rows)
    if 'tsne_cpu_s' in df:
        df['tsne_cpu_rel_ref'] = df.tsne_cpu_s / df.loc[(df.perplexity == REF[0]) & (df.tsne_iter == REF[1]), 'tsne_cpu_s'].iloc[0]
    df.to_csv(os.path.join(OUT, 'tsne_px_summary.csv'), index=False, float_format='%.5g')
    pd.set_option('display.width', 260)
    print(df.drop(columns='config').round(3).to_string(index=False))


if __name__ == '__main__':
    main()
