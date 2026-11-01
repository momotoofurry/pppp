"""Post-hoc diagnostics of the external validation (NOT pre-registered; EXTERNAL_PLAN.md is reported as planned in
results/external_check_summary.csv): per-subject A1 table with the start-up rotation of each seed, and A - F per run
split by whether the start-up alignment returned 0 (the strap was not rotated in A1 / A3, so k != 0 is a false
rotation). Reads results/external_check.csv; writes results/external_posthoc.csv.
Usage (in the container): python src/external_posthoc.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')


def main():
    df = pd.read_csv(os.path.join(OUT, 'external_check.csv'))
    a = (df.groupby(['span', 'comp', 'var', 'subject', 'seed'])[['ok', 'n']].sum()
         .assign(acc=lambda g: g.ok / g.n * 100).reset_index())
    k = df[(df['var'] == 'A') & (df.block == 0)][['span', 'comp', 'subject', 'seed', 'k_est']]
    w = a.pivot_table(index=['span', 'comp', 'subject', 'seed'], columns='var', values='acc').reset_index().merge(k)
    w['d'] = w.A - w.F
    t = w[(w.span == '0-2s') & (w.comp == 'A1')]
    print('A1 0-2 s per subject (mean of seeds), start-up rotation per seed')
    print(t.groupby('subject').agg(F=('F', 'mean'), A=('A', 'mean'), d=('d', 'mean'),
                                   k=('k_est', lambda s: list(s))).round(2).to_string())
    rows = []
    for (sp, grp), g in w[w.comp.str.match('A1|A3')].assign(grp=lambda x: x.comp.str[:2]).groupby(['span', 'grp']):
        for kz, h in g.groupby(g.k_est == 0):
            rows.append(dict(span=sp, comp=grp, rotation='0' if kz else 'false (!= 0)', runs=len(h),
                             diff_mean=h.d.mean(), better=int((h.d > 0).sum()), worse=int((h.d < 0).sum())))
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(OUT, 'external_posthoc.csv'), index=False, float_format='%.4g')
    print(r.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
