"""Summary of the C implementations (pre-board work): self-calibration accuracy of every C variant vs the
sklearn run of the same setting, PC t-SNE time, and the Cortex-M7 build sizes. All Docker runs.

Setting everywhere: 100 trees / depth 10 / int16, int16 buffer of 375, max_leaf_nodes 32 (arm_position,
20 subjects x 3 seeds). Reference: sklearn with the same t-SNE iterations (selfcal_sweep_iter.csv).
Variants: C t-SNE (_tc, 500 and 1000 it), C t-SNE + C K-Means (_plc), C trees (_rc), all C (_allc),
the C firmware logic driven end to end (selfcal_c_check.csv), upstream pipeline on the C features (_fc).
Paired difference over 20 subjects (seed-averaged), Wilcoxon. Demo (two-day recording, 1 subject x 10 seeds):
full model, compressed model with upstream settings, the MCU setting in sklearn and the C firmware logic.
Writes results/c_impl_summary.csv and results/c_impl_demo.csv. Usage (in the container): python src/analyze_c_impl.py
"""
import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'results')


def rd(name, it=None):
    d = pd.read_csv(os.path.join(R, name), keep_default_na=False)
    if it is not None and 'tsne_iter' in d:
        d = d[d.tsne_iter.astype(int) == it]
    return d


def summary(d):
    per_seed = d.groupby('seed')[['acc_oneshot', 'acc_selfcal']].mean() * 100
    return dict(acc_oneshot=per_seed.acc_oneshot.mean(), acc_selfcal=per_seed.acc_selfcal.mean(),
                selfcal_seed_min=per_seed.acc_selfcal.min(), selfcal_seed_max=per_seed.acc_selfcal.max(),
                gain=(per_seed.acc_selfcal - per_seed.acc_oneshot).mean())


def paired(d, ref):
    a = d.groupby('subject').acc_selfcal.mean() * 100
    b = ref.groupby('subject').acc_selfcal.mean() * 100
    x = a - b
    return dict(diff_vs_sklearn=x.mean(), n_better=int((x > 0).sum()), n_worse=int((x < 0).sum()),
                wilcoxon_p=wilcoxon(a, b).pvalue if np.any(x != 0) else 1.0)


def main():
    rows = []
    for it in [500, 1000]:
        rows.append(dict(variant=f'sklearn (reference), {it} it', tsne_iter=it, **summary(rd('selfcal_sweep_iter.csv', it))))
    for name, f, it in [('C t-SNE', 'selfcal_sweep_tc.csv', 500), ('C t-SNE', 'selfcal_sweep_tc.csv', 1000),
                        ('C t-SNE + C K-Means', 'selfcal_sweep_plc.csv', 500), ('C trees', 'selfcal_sweep_rc.csv', 500),
                        ('all C (Python loop)', 'selfcal_sweep_allc.csv', 500),
                        ('C firmware logic (selfcal.c, end to end)', 'selfcal_c_check.csv', None),
                        ('upstream pipeline on C features', 'selfcal_sweep_fc.csv', 500)]:
        d = rd(f, it)
        ref = rd('selfcal_sweep_iter.csv', it or 500)
        rows.append(dict(variant=f'{name}, {it or 500} it', tsne_iter=it or 500, **summary(d), **paired(d, ref)))
    df = pd.DataFrame(rows)
    tc = rd('tsne_c_check.csv')
    for it in [500, 1000]:
        g = tc[tc.max_iter == it]
        m = df.tsne_iter == it
        df.loc[m & df.variant.str.startswith('sklearn'), 'pc_tsne_cpu_s'] = g.cpu_sklearn_s.mean()
        df.loc[m & df.variant.str.startswith('C t-SNE,'), 'pc_tsne_cpu_s'] = g.cpu_c_s.mean()
    fw = rd('selfcal_c_check.csv')
    df.loc[df.variant.str.startswith('C firmware'), 'pc_step_cpu_s'] = fw.update_cpu_s.astype(float).mean()
    df.to_csv(os.path.join(R, 'c_impl_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(df.round(3).to_string(index=False))

    demo = []
    if os.path.exists(os.path.join(R, 'selfcal_c_check_demo.csv')):
        ref = rd('selfcal_sweep_demo_ref.csv')
        for cfg, name in [('N400_dnone_float64', 'full model (paper), sklearn'),
                          ('N100_d10_int16', '100 trees d10 int16, upstream settings, sklearn')]:
            demo.append(dict(variant=name, **summary(ref[ref.config == cfg]), blocks=ref.block.nunique()))
        demo.append(dict(variant='MCU setting, sklearn', **summary(rd('selfcal_sweep_demo_mcu.csv'))))
        demo.append(dict(variant='MCU setting, C firmware logic', **summary(rd('selfcal_c_check_demo.csv'))))
        dd = pd.DataFrame(demo)
        # day-2 tail (blocks 7-9), as report 1.5
        tails = []
        for cfg_name, d in [('full model (paper), sklearn', ref[ref.config == 'N400_dnone_float64']),
                            ('100 trees d10 int16, upstream settings, sklearn', ref[ref.config == 'N100_d10_int16']),
                            ('MCU setting, sklearn', rd('selfcal_sweep_demo_mcu.csv')),
                            ('MCU setting, C firmware logic', rd('selfcal_c_check_demo.csv'))]:
            t = d[d.block.astype(int) >= 7]
            tails.append(dict(variant=cfg_name, oneshot_blocks7_9=t.acc_oneshot.astype(float).mean() * 100,
                              selfcal_blocks7_9=t.acc_selfcal.astype(float).mean() * 100))
        dd = dd.merge(pd.DataFrame(tails), on='variant')
        dd.to_csv(os.path.join(R, 'c_impl_demo.csv'), index=False, float_format='%.4g')
        print(dd.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
