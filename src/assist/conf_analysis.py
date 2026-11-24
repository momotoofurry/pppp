"""35.94: does the board's own confidence tell a right direction command from a wrong one?
Steps where the latched command is a direction (the arm moves). Right = the simulated user wanted that direction.
Features from the board's PRED of each 100 ms window (top class, accepted, LDA margin x100):
  margin   : this window's margin if its top class is the latched command, else 0
  agree5   : share of the last 5 windows whose accepted top class is the latched command
  margin5  : mean of margin over the last 5 windows (0 for windows of another class)
AUC (right vs wrong) per donning / half, and what share of wrong steps vs right steps falls below thresholds."""
import sys

import numpy as np
import pandas as pd

d = pd.read_csv(sys.argv[1])
DIRS = ('up', 'down', 'left', 'right')
d['own'] = ((d.top == d.cmd) & (d.acc == 1)).astype(float)
d['mg'] = np.where(d.own > 0, d.margin / 100.0, 0.0)
g = d.groupby(['donning', 'seed', 'half', 'trial'], sort=False)
d['agree5'] = g.own.transform(lambda s: s.rolling(5, min_periods=1).mean())
d['margin5'] = g.mg.transform(lambda s: s.rolling(5, min_periods=1).mean())
mv = d[d.cmd.isin(DIRS)].copy()
mv['right'] = mv.want == mv.cmd


def auc(score, y):
    s1, s0 = score[y], score[~y]
    if len(s1) == 0 or len(s0) == 0:
        return float('nan')
    r = pd.Series(np.concatenate([s1, s0])).rank().values
    return (r[:len(s1)].sum() - len(s1) * (len(s1) + 1) / 2) / (len(s1) * len(s0))


print('moving steps; wrong = the user did not want that direction (other direction, or rest)')
for (don, h), x in mv.groupby(['donning', 'half']):
    y = x.right.values
    print(f'  {don[4:6]}{"AB"[h]}: steps {len(x)}, wrong {100 * (~y).mean():.1f} %;  AUC margin '
          f'{auc(x.mg.values, y):.2f}  agree5 {auc(x.agree5.values, y):.2f}  margin5 {auc(x.margin5.values, y):.2f}')
y = mv.right.values
print(f'  all: wrong {100 * (~y).mean():.1f} %; AUC margin {auc(mv.mg.values, y):.2f} agree5 '
      f'{auc(mv.agree5.values, y):.2f} margin5 {auc(mv.margin5.values, y):.2f}')
print('\nwhat a threshold on agree5 would catch (all donnings):')
for th in (0.2, 0.4, 0.6, 0.8):
    lo = mv.agree5 < th
    print(f'  agree5 < {th}: {100 * lo[~mv.right].mean():5.1f} % of wrong steps, {100 * lo[mv.right].mean():5.1f} % of right steps')
print('\nwrong steps by what the user wanted:', mv[~mv.right].want.value_counts().to_dict())
