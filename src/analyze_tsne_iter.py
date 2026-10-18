"""Fewer t-SNE iterations (selfcal_sweep.py ... --tsne-iter 250 500 1000 --suffix _iter, then
--tsne-iter 300 350 400 750 --suffix _iter2), Docker runs.

Model: 100 trees / depth 10 / int16, int16 buffer of 375, self-calibration trees with max_leaf_nodes 32 (the
setting below 256 KB). Reference = the 1000-iteration (upstream) variant of the same run; it is also checked
against the earlier _combo run of the same setting (must be identical: same code path, same seeds).
For every iteration count: self-calibration accuracy (mean of 3 seeds, seed range), gain over one-shot,
paired difference vs. 1000 iterations over 20 subjects (seed-averaged, Wilcoxon), and, if
results/tsne_cost_iter.csv exists (tsne_cost.py --sizes 375 --iters ... --suffix _iter), the PC single-thread
t-SNE CPU time and its ratio to 1000 iterations. t-SNE iterations do not change the RAM estimate.
Writes results/tsne_iter_summary.csv. Usage (in the container): python src/analyze_tsne_iter.py
"""
import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
REF_ITER = 1000
COMBO_CFG = 'N100_d10_int16_mln32_buf375_bq16'
SUFFIXES = ['_iter', '_iter2']     # 250 500 1000, then 300 350 400 750


def main():
    acc = pd.concat([pd.read_csv(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'), keep_default_na=False)
                     for sfx in SUFFIXES if os.path.exists(os.path.join(OUT, f'selfcal_sweep{sfx}.csv'))])
    ref = acc[acc.tsne_iter == REF_ITER]
    combo = pd.read_csv(os.path.join(OUT, 'selfcal_sweep_combo.csv'), keep_default_na=False)
    combo = combo[combo.config == COMBO_CFG]
    key = ['seed', 'subject', 'block']
    m = ref.merge(combo, on=key, suffixes=('', '_combo'))
    same = len(m) == len(ref) == len(combo) and np.allclose(m.acc_selfcal, m.acc_selfcal_combo, atol=1e-4, rtol=0)
    print(f'1000 iterations vs _combo run: {len(m)} rows, identical = {same}')

    cost = None
    if os.path.exists(os.path.join(OUT, 'tsne_cost_iter.csv')):
        cost = pd.read_csv(os.path.join(OUT, 'tsne_cost_iter.csv')).groupby('max_iter')
        cpu = cost.cpu_s.mean()
    ref_subj = ref.groupby('subject').acc_selfcal.mean() * 100
    rows = []
    for it, g in acc.groupby('tsne_iter', sort=False):
        per_seed = g.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
        per_subj = g.groupby('subject').acc_selfcal.mean() * 100
        d = per_subj - ref_subj
        row = dict(config=g.config.iloc[0], tsne_iter=it, acc_oneshot=per_seed.acc_oneshot.mean(),
                   acc_selfcal=per_seed.acc_selfcal.mean(), selfcal_seed_min=per_seed.acc_selfcal.min(),
                   selfcal_seed_max=per_seed.acc_selfcal.max(),
                   gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean(),
                   gain_seed_min=(per_seed.acc_selfcal - per_seed.acc_oneshot).min(),
                   gain_seed_max=(per_seed.acc_selfcal - per_seed.acc_oneshot).max(),
                   diff_vs_1000=d.mean(), n_subjects_better=int((d > 0).sum()), n_subjects_worse=int((d < 0).sum()),
                   wilcoxon_p=wilcoxon(per_subj, ref_subj).pvalue if np.any(d != 0) else 1.0,
                   same_as_combo=same if it == REF_ITER else np.nan)
        if cost is not None and it in cpu.index:
            row.update(tsne_cpu_s=cpu[it], tsne_cpu_rel_1000=cpu[it] / cpu[REF_ITER],
                       tsne_n_iter_run=cost.n_iter.mean()[it], cost_subjects=int(cost.size()[it]))
        rows.append(row)
    df = pd.DataFrame(rows).sort_values('tsne_iter')
    df.to_csv(os.path.join(OUT, 'tsne_iter_summary.csv'), index=False, float_format='%.5g')
    pd.set_option('display.width', 260)
    print(df.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
