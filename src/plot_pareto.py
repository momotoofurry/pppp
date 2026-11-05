"""Thesis figure (report 27.4): why 100 trees / depth 10 / int16 and a 375-row buffer with <= 32-leaf new trees.
Only existing results, nothing re-run, nothing re-chosen (the setting was chosen in report 3; this figure explains it).
  (a) results/selfcal_sweep_summary_compressed.csv: self-calibrated accuracy vs. model size after
      self-calibration (compact layout, KB) for the compressed forests (PC, sklearn, t-SNE pseudo-labels)
  (b) results/leaf_buffer_summary.csv: self-calibrated accuracy vs. ESTIMATED self-calibration RAM (KB, report 3.6
      model incl. t-SNE work memory), 100 trees / depth 10 / int16; the 256 KB line is the H7 budget.
      The final firmware does not run t-SNE; its measured static RAM upper bound is 176.5 KB (report 20.1).
Writes results/pareto.png and results/pareto.csv.
Usage (container): python src/plot_pareto.py
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')
BLUE, ORANGE, INK, MUTED, GRID = '#2a78d6', '#eb6834', '#1f1f1e', '#6b6a64', '#e4e3df'


def main():
    c = pd.read_csv(os.path.join(OUT, 'selfcal_sweep_summary_compressed.csv')).sort_values('compact_KB')
    lb = pd.read_csv(os.path.join(OUT, 'leaf_buffer_summary.csv'))
    lb = lb[lb.buffer_int16 == True].copy()                                         # noqa: E712
    lb['leaf32'] = lb.max_leaf_nodes.astype(str) == '32'
    plt.rcParams.update({'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED,
                         'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 9})
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)

    a = ax[0]
    a.plot(c.compact_KB, c.acc_selfcal, '-', color=BLUE, lw=2, zorder=2)
    a.scatter(c.compact_KB, c.acc_selfcal, s=40, color=BLUE, edgecolor='white', lw=2, zorder=3)
    off = {'N20_d10_int16': (6, -4), 'N50_d8_int16': (6, -12), 'N100_d10_int16': (8, -16),
           'N400_d10_int16': (-20, -26), 'N400_dnone_float32': (-60, 8)}
    for _, r in c.iterrows():
        pick = r.config == 'N100_d10_int16'
        a.annotate(f"{r.n_trees} trees, d {r.max_depth}, {r.precision}: {r.acc_selfcal:.2f}%",
                   (r.compact_KB, r.acc_selfcal), xytext=off.get(r.config, (6, 6)), textcoords='offset points',
                   fontsize=7.5, color=INK if pick else MUTED, fontweight='bold' if pick else 'normal')
        if pick:
            a.scatter([r.compact_KB], [r.acc_selfcal], s=120, facecolor='none', edgecolor=ORANGE, lw=2, zorder=4)
    a.set_xscale('log')
    a.set_xticks([20, 50, 100, 200, 500, 1000])
    a.set_xticklabels(['20', '50', '100', '200', '500', '1000'])
    a.minorticks_off()
    a.set_xlabel('model size after self-calibration (KB, log)')
    a.set_ylabel('self-calibrated accuracy (%)')
    a.set_title('(a) forest compression', loc='left', fontsize=10, color=INK)

    b = ax[1]
    b.axvline(256, color=MUTED, lw=1, ls='--')
    b.text(262, 82.05, '256 KB', fontsize=7.5, color=MUTED)
    for leaf, col, name in ((False, BLUE, 'new trees unlimited'), (True, ORANGE, 'new trees <= 32 leaves')):
        g = lb[lb.leaf32 == leaf].sort_values('buffer')
        b.plot(g.total_KB, g.acc_selfcal, '-', color=col, lw=2, zorder=2, label=name)
        b.scatter(g.total_KB, g.acc_selfcal, s=40, color=col, edgecolor='white', lw=2, zorder=3)
        for _, r in g.iterrows():
            pick = r.config == 'N100_d10_int16_mln32_buf375_bq16'
            b.annotate(f"{r.buffer}" + (f": {r.acc_selfcal:.2f}%" if pick else ''), (r.total_KB, r.acc_selfcal),
                       xytext=(5, -13) if leaf else (4, 6), textcoords='offset points', fontsize=7.5,
                       color=INK if pick else MUTED, fontweight='bold' if pick else 'normal')
            if pick:
                b.scatter([r.total_KB], [r.acc_selfcal], s=120, facecolor='none', edgecolor=INK, lw=1.5, zorder=4)
    b.legend(frameon=False, fontsize=8, loc='lower right', title='number = buffer rows', title_fontsize=7.5)
    b.set_xlabel('self-calibration RAM, estimate incl. t-SNE (KB)')
    b.set_title('(b) buffer and new-tree size (100 trees, d 10, int16)', loc='left', fontsize=10, color=INK)
    for x in ax:
        x.grid(True, color=GRID, lw=0.8)
        x.set_axisbelow(True)
    fig.text(0.01, 0.01, '20 subjects x 3 seeds, PC (sklearn, t-SNE pseudo-labels). (b) RAM is the report 3.6 estimate; '
             'the final firmware has no t-SNE and its measured static RAM bound is 176.5 KB.', fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(os.path.join(OUT, 'pareto.png'), dpi=180)
    pd.concat([c.assign(panel='a', x_KB=c.compact_KB)[['panel', 'config', 'x_KB', 'acc_selfcal', 'gain']],
               lb.assign(panel='b', x_KB=lb.total_KB)[['panel', 'config', 'x_KB', 'acc_selfcal', 'gain']]]
              ).to_csv(os.path.join(OUT, 'pareto.csv'), index=False, float_format='%.3f')
    print('wrote results/pareto.png')


if __name__ == '__main__':
    main()
