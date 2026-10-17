"""Paired comparison of the self-calibration validation run: Windows (results/selfcal_sweep.csv)
vs Linux (results/selfcal_sweep_validation_linux.csv), 400 trees / no depth limit / float64.
Usage (repo root, in the container): python src/compare_selfcal_platform.py
"""
import pandas as pd, numpy as np
w = pd.read_csv('results/selfcal_sweep.csv', keep_default_na=False)
w = w[w.config == 'N400_dnone_float64']
l = pd.read_csv('results/selfcal_sweep_validation_linux.csv', keep_default_na=False)
k = ['seed', 'subject', 'block']
m = w.merge(l, on=k, suffixes=('_win', '_linux'))
print('rows', len(m), '| one-shot identical rows:', int(np.isclose(m.acc_oneshot_win, m.acc_oneshot_linux, atol=1e-4).sum()),
      '| self-cal identical rows:', int(np.isclose(m.acc_selfcal_win, m.acc_selfcal_linux, atol=1e-4).sum()))
for c in ['acc_oneshot', 'acc_selfcal']:
    s = m.groupby('seed')[[c + '_win', c + '_linux']].mean() * 100
    print(c, 'per seed (win, linux):', s.round(2).values.tolist())
ps = m.groupby(['seed', 'subject'])[['acc_selfcal_win', 'acc_selfcal_linux']].mean() * 100
d = ps.acc_selfcal_linux - ps.acc_selfcal_win
print(f'self-cal linux - win, per (seed, subject): mean {d.mean():+.2f} pp, SD {d.std():.2f}, min {d.min():+.2f}, max {d.max():+.2f}, n={len(d)}')
ws = ps.groupby('seed').mean()
print('seed-to-seed spread within Windows (max-min):', round(float(ws.acc_selfcal_win.max() - ws.acc_selfcal_win.min()), 2),
      'within Linux:', round(float(ws.acc_selfcal_linux.max() - ws.acc_selfcal_linux.min()), 2))
from scipy.stats import wilcoxon
sub = ps.groupby('subject').mean()
print('Wilcoxon over 20 subjects (seed-averaged):', wilcoxon(sub.acc_selfcal_linux, sub.acc_selfcal_win))
