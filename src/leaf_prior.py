"""Prior strength of the anchor counters (leafcal.c rule): which prior r, and how bad is the worst case? (report 35.7)

Reads results/leaf_sweep.csv (development data: arm_position 20 x 3 seeds, shifts 0 / 0.5, streams base / rest2) and
results/leaf_external.csv (Kyranou 2025, consistency check only) for the conditions LAonly_r<r>_za (leaf_sweep.PRIORS):
the one-shot class of a leaf has a prior of r labelled anchor windows; r = 1e6 never changes a leaf (z-score from the
anchor only). Per scenario, subjects with seeds averaged:
  later     blocks 1..10 (as leaf_sweep_summary): mean accuracy, difference to F with a paired t CI, worst subject
  block0    block 0 only: the windows right after the first anchor (the case seen on the board bench, report 35.6)
  harm      share of subject x block cells (blocks 0..10, seeds averaged) where the condition is > 5 points below F
LOSO: for every subject, r is chosen on the other 19 (mean over the 4 scenarios of the blocks 1..10 accuracy) and
applied to the left-out subject; reported as the left-out subject's difference to F and to r = 0.5.
Writes results/leaf_prior_summary.csv, leaf_prior_loso.csv, leaf_prior_external.csv.
Usage (in the container): python src/leaf_prior.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
PR = {LS.pname(r): r for r in LS.PRIORS}


def main():
    a = pd.read_csv(os.path.join(OUT, 'leaf_sweep.csv'))
    a = a[a.cond.isin(list(PR) + ['F', 'R', 'Rcum', 'A'])]
    cell = a.groupby(['shift', 'stream', 'cond', 'subject', 'block']).acc.mean().unstack('cond') * 100
    rows = []
    for (sh, st), g in cell.groupby(level=[0, 1]):
        later = g[g.index.get_level_values('block') >= 1].groupby(level='subject').mean()
        b0 = g[g.index.get_level_values('block') == 0].groupby(level='subject').mean()
        for c in list(PR) + ['R', 'Rcum', 'A']:
            d = later[c] - later.F
            m, lo, hi = LS.ci(d)
            d0 = b0[c] - b0.F
            m0, lo0, hi0 = LS.ci(d0)
            harm = float(np.mean((g[c] - g.F) < -5) * 100)
            rows.append(dict(shift=sh, stream=st, cond=c, r=PR.get(c, np.nan), acc=later[c].mean(), vsF=m, vsF_lo=lo,
                             vsF_hi=hi, worst=d.min(), worse=int((d < 0).sum()), block0_vsF=m0, block0_lo=lo0,
                             block0_hi=hi0, block0_worst=d0.min(), harm_cells_pct=harm))
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'leaf_prior_summary.csv'), index=False, float_format='%.4g')
    pd.set_option('display.width', 250)
    print(sm.round(2).to_string(index=False))

    # LOSO choice of r
    later = (a[a.block >= 1].groupby(['shift', 'stream', 'cond', 'subject']).acc.mean() * 100).unstack('cond')
    per_subj = later.groupby(level='subject').mean()                     # mean over the 4 scenarios
    lo_rows = []
    for s in per_subj.index:
        rest = per_subj.drop(index=s)
        best = max(PR, key=lambda c: rest[c].mean())
        lo_rows.append(dict(subject=s, chosen=best, r=PR[best], vsF=per_subj.loc[s, best] - per_subj.loc[s, 'F'],
                            vs_r05=per_subj.loc[s, best] - per_subj.loc[s, LS.pname(0.5)]))
    lo = pd.DataFrame(lo_rows)
    lo.to_csv(os.path.join(OUT, 'leaf_prior_loso.csv'), index=False, float_format='%.4g')
    print('\nLOSO choices:', lo.chosen.value_counts().to_dict())
    for col in ('vsF', 'vs_r05'):
        m, l, h = LS.ci(lo[col])
        print(f'left-out subject {col}: {m:+.2f} ({l:+.2f}, {h:+.2f}), worst {lo[col].min():+.2f}')

    # Kyranou
    e = pd.read_csv(os.path.join(OUT, 'leaf_external.csv'))
    e['ok'] = e.acc * e.n
    acc = (e.groupby(['comp', 'cond', 'subject', 'seed'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100)
           .groupby(['comp', 'cond', 'subject']).acc.mean().unstack('cond'))
    xr = []
    for comp, g in acc.groupby(level='comp'):
        for c in [x for x in list(PR) + ['R', 'Rcum'] if x in g]:
            d = g[c] - g.F
            m, l, h = LS.ci(d)
            xr.append(dict(comp=comp, cond=c, r=PR.get(c, np.nan), acc=g[c].mean(), vsF=m, vsF_lo=l, vsF_hi=h,
                           worst=d.min(), worse=int((d < 0).sum())))
    xr = pd.DataFrame(xr)
    xr.to_csv(os.path.join(OUT, 'leaf_prior_external.csv'), index=False, float_format='%.4g')
    print()
    print(xr.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
