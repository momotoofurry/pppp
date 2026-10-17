"""Stage 2.3 plot: model size (KB) vs one-shot accuracy, with Flash 512 KB / 1 MB reference lines.

Reads results/sweep_summary.csv (+ sweep_summary_app200.csv if present).
Writes results/sweep_size_vs_acc.png and results/sweep_pareto.csv.
Usage: .venv/Scripts/python src/plot_sweep.py
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
DEPTH_ORDER = ['6', '8', '10', '12', 'none']
COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4']  # categorical slots 1-5
INK, MUTED, GRID = '#1f1f1e', '#6b6a64', '#e4e3df'


def main():
    s = pd.read_csv(os.path.join(OUT, 'sweep_summary.csv'), dtype={'max_depth': str})
    b_path = os.path.join(OUT, 'sweep_summary_app200.csv')
    b = pd.read_csv(b_path, dtype={'max_depth': str}) if os.path.exists(b_path) else None
    full = s[(s.max_depth == 'none') & (s.n_trees == 400) & (s.precision == 'float32')].iloc[0]

    plt.rcParams.update({'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED,
                         'ytick.color': MUTED, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    for ax, layout, title in [(axes[0], 'compact_KB', '(a) compact layout: internal nodes only, leaves inlined'),
                              (axes[1], 'naive_KB', '(b) naive layout: every node stores feat/thr/L/R/class')]:
        for d, c in zip(DEPTH_ORDER, COLORS):
            for prec, ls, mfc in [('float32', '-', c), ('int16', '--', 'white')]:
                m = s[(s.max_depth == d) & (s.precision == prec)].sort_values('n_trees')
                ax.plot(m[layout], m.acc_mean, ls=ls, color=c, lw=2, marker='o', ms=6, mfc=mfc, mew=1.5,
                        label=f'depth {d}, {prec}' if ax is axes[0] else None)
            if d == '10':
                m = s[(s.max_depth == d) & (s.precision == 'float32')].sort_values('n_trees')
                for _, r in m.iterrows():
                    ax.annotate(f'N={r.n_trees}', (r[layout], r.acc_mean), textcoords='offset points',
                                xytext=(-6, 8), fontsize=7.5, color=MUTED, ha='right')
        if b is not None and layout == 'compact_KB':
            m = b[(b.max_depth == '10') & (b.precision == 'float32')].sort_values('n_trees')
            ax.plot(m[layout], m.acc_mean, ls=':', color=MUTED, lw=2, marker='s', ms=5,
                    label='variant B: 200 appended + 5..200 pre-trained, depth 10, float32')
        for kb, lab in [(512, 'Flash 512 KB'), (1024, 'Flash 1 MB')]:
            ax.axvline(kb, color=INK, lw=1, ls=(0, (4, 3)))
            ax.text(kb * 1.05, 67.3, lab, rotation=90, fontsize=8, color=INK, va='bottom')
        ax.axhline(full.acc_mean, color=MUTED, lw=1, ls=':')
        ax.text(1.0, full.acc_mean + 0.15, f'full model {full.acc_mean:.2f}%', fontsize=8, color=MUTED)
        ax.set_xscale('log')
        ax.set_xlabel('model size (KB, log scale)')
        ax.set_title(title, fontsize=10, color=INK)
        ax.grid(color=GRID, lw=0.8)
        ax.set_xlim(0.6, 2500)
    axes[0].set_ylabel('one-shot accuracy, 11 blocks, 20 subjects (%)')
    fig.legend(loc='lower center', ncol=4, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle('RF compression sweep: size vs. accuracy (arm_position, one-shot, no self-calibration, 5 seeds)',
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(os.path.join(OUT, 'sweep_size_vs_acc.png'), dpi=150)

    # Pareto front (compact layout): configs no other config beats in both size and accuracy
    allc = s.copy()
    allc['variant'] = 'A (half/half)'
    if b is not None:
        bb = b.copy()
        bb['variant'] = 'B (200 appended)'
        allc = pd.concat([allc, bb[bb.n_pre < 200]])
    allc = allc.sort_values('compact_KB')
    front, best = [], -1
    for _, r in allc.iterrows():
        if r.acc_mean > best:
            front.append(r)
            best = r.acc_mean
    p = pd.DataFrame(front)[['variant', 'max_depth', 'n_trees', 'n_pre', 'precision', 'compact_KB', 'compact_KB_max',
                             'naive_KB', 'acc_mean', 'acc_seed_min', 'acc_seed_max', 'acc_sd_subjects']]
    p['acc_minus_full'] = p.acc_mean - full.acc_mean
    p.to_csv(os.path.join(OUT, 'sweep_pareto.csv'), index=False, float_format='%.2f')
    print(p.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
