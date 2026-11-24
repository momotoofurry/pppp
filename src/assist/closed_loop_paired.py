"""35.88: wrong locks per trial, difference vs the base run, paired by session seed (closed_loop_fw.py draws the
prior from its own stream since 35.88, so every condition replays the same trials). 95 % CI: t(14) over 15 sessions."""
import pandas as pd, numpy as np
import sys
R = sys.argv[1] if len(sys.argv) > 1 else '/work/results/selftest_T00/closed_loop_fw_trials_88s_%s.csv'
b = pd.read_csv(R % 'base')
print('per-session mean wrong locks, difference vs base: mean [95% CI over 15 paired sessions]')
for c in ['all', 'ctx', 'place', 'uni', 'p95', 'p50']:
    x = pd.read_csv(R % c)
    out = []
    for (don, h), g in x.groupby(['donning', 'half']):
        gb = b[(b.donning == don) & (b.half == h)]
        d = g.groupby('session').wrong_locks.mean() - gb.groupby('session').wrong_locks.mean()
        se = d.std(ddof=1) / np.sqrt(len(d))
        out.append(f'{don[4:6]}{"AB"[h]} {d.mean():+.2f} [{d.mean()-2.145*se:+.2f},{d.mean()+2.145*se:+.2f}]')
    print(f'{c:5s}', '  '.join(out))
