"""Collect upstream replay accuracies into results/baseline.csv and plot them.

Reads results/upstream/seed*/accuracy_*.npy written by src/run_upstream.py and
produces:
    results/baseline.csv            long format: seed, subject, group, block, position, method, accuracy
    results/baseline_by_position.csv mean accuracy per method x arm position
    results/baseline_demo.csv       demo participant, per block
    results/baseline_blocks.png     accuracy vs. testing block (arm_position, mean +- SD over subjects)

Usage: .venv/Scripts/python src/make_baseline.py
"""
import glob
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = os.path.join(ROOT, 'results', 'upstream')
OUT = os.path.join(ROOT, 'results')

# method key in file name -> label used in the table
METHODS = {
    'standard_LDA': 'LDA (calib only)',
    'standard_RF': 'RF (calib only)',
    'pretrain': 'pretrained RF (no calib)',
    'prune_append': 'fixed: one-shot RF',
    'self_calibration': 'self-calibrating RF',
}
SEQ_A = ['P5', 'P4', 'P2', 'P6', 'P8', 'P5', 'P8', 'P6', 'P2', 'P4', 'P5']  # subjects 0-9
SEQ_B = ['P5', 'P8', 'P6', 'P2', 'P4', 'P5', 'P4', 'P2', 'P6', 'P8', 'P5']  # subjects 10-19


def load(prefix):
    rows = []
    for d in sorted(glob.glob(os.path.join(UP, 'seed*'))):
        seed = int(os.path.basename(d)[4:])
        for key, name in METHODS.items():
            f = os.path.join(d, f'accuracy_{prefix}{key}_repeat0.npy')
            if not os.path.exists(f):
                continue
            acc = np.load(f)
            for s in range(acc.shape[0]):
                for b in range(acc.shape[1]):
                    rows.append(dict(seed=seed, subject=s, block=b, method=name, accuracy=acc[s, b]))
    return pd.DataFrame(rows)


def main():
    arm = load('')
    if len(arm):
        arm['group'] = np.where(arm.subject < 10, 'A', 'B')
        arm['position'] = [(SEQ_A if s < 10 else SEQ_B)[b] for s, b in zip(arm.subject, arm.block)]
        arm = arm[['seed', 'subject', 'group', 'block', 'position', 'method', 'accuracy']]
        arm.to_csv(os.path.join(OUT, 'baseline.csv'), index=False, float_format='%.4f')

        # average over seeds first, then over subjects
        per_subj = arm.groupby(['method', 'subject', 'block', 'position'], as_index=False).accuracy.mean()
        pos = per_subj.groupby(['method', 'position']).accuracy.mean().unstack('position')
        pos['all blocks'] = per_subj.groupby('method').accuracy.mean()
        pos = pos.loc[list(METHODS.values())]
        pos.to_csv(os.path.join(OUT, 'baseline_by_position.csv'), float_format='%.4f')
        print('Arm position dataset, mean accuracy over 20 subjects '
              f'(seeds: {sorted(arm.seed.unique())}):')
        print((pos * 100).round(2).to_string())

        blk = per_subj.groupby(['method', 'block']).accuracy.agg(['mean', 'std']).reset_index()
        print('\nPer-block mean (%):')
        print((blk.pivot(index='method', columns='block', values='mean').loc[list(METHODS.values())] * 100).round(1).to_string())

    demo = load('demo_')
    if len(demo):
        demo.to_csv(os.path.join(OUT, 'baseline_demo.csv'), index=False, float_format='%.4f')
        print('\nDemo participant, per block (%):')
        t = demo.groupby(['method', 'block']).accuracy.mean().unstack('block')
        t['mean'] = t.mean(axis=1)
        print((t.loc[list(METHODS.values())] * 100).round(1).to_string())

    if len(arm):
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw=dict(width_ratios=[11, 10]))
        ax = axes[0]
        n = per_subj.subject.nunique()
        for name in METHODS.values():
            m = blk[blk.method == name]
            se = m['std'] / np.sqrt(n) * 100
            ax.plot(m.block, m['mean'] * 100, marker='o', ms=4, label=name)
            ax.fill_between(m.block, m['mean'] * 100 - se, m['mean'] * 100 + se, alpha=0.15)
        ax.set_xticks(range(11))
        ax.set_xticklabels([f'{b}\nA:{SEQ_A[b]}\nB:{SEQ_B[b]}' for b in range(11)], fontsize=8)
        ax.set_xlabel('testing block (arm position, group A / B)')
        ax.set_ylabel('accuracy (%)')
        ax.set_title(f'Arm-position dataset, {n} subjects (mean ± SE, {arm.seed.nunique()} seeds)')
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc='lower left')
        if len(demo):
            ax = axes[1]
            for name in METHODS.values():
                m = demo[demo.method == name].groupby('block').accuracy
                ax.plot(m.mean().index, m.mean() * 100, marker='o', ms=4, label=name)
                ax.fill_between(m.mean().index, m.min() * 100, m.max() * 100, alpha=0.15)
            ax.axvline(4.5, color='gray', ls='--', lw=1)
            ax.text(2, 101, 'day 1', ha='center', fontsize=9)
            ax.text(7, 101, 'day 2', ha='center', fontsize=9)
            ax.set_xticks(range(10))
            ax.set_xlabel('testing block')
            ax.set_ylim(axes[0].get_ylim()[0] if axes[0].get_ylim()[0] < 30 else 30, 104)
            ax.set_title(f'Demo participant (mean, band = min–max over {demo.seed.nunique()} seeds)')
            ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, 'baseline_blocks.png'), dpi=150)


if __name__ == '__main__':
    main()
