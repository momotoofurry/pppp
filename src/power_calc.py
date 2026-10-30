"""Sample size for the pilot / main study (PROTOCOL.md section 7): paired design, one primary endpoint.
1. Offline effect sizes on the development data (stress_check.csv, firmware vs fixed model, per subject, 3 seeds
   averaged): mean paired difference, SD, dz = mean / SD.
2. Minimal detectable dz for n = 8..24 (two-sided paired t test, alpha 0.05, power 0.8; noncentral t), and the n
   needed for the development-data dz. The closed-loop effect is unknown: these numbers only bound it.
Writes results/power_calc.csv. Usage (in the container): python src/power_calc.py
"""
import os

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')


def power(dz, n, alpha=0.05):
    df = n - 1
    t = stats.t.ppf(1 - alpha / 2, df)
    nc = dz * np.sqrt(n)
    return 1 - stats.nct.cdf(t, df, nc) + stats.nct.cdf(-t, df, nc)


def min_dz(n, target=0.8):
    lo, hi = 0.01, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if power(mid, n) < target else (lo, mid)
    return hi


def n_needed(dz, target=0.8):
    return next(n for n in range(3, 500) if power(dz, n) >= target)


def main():
    df = pd.read_csv(os.path.join(OUT, 'stress_check.csv'))
    df = df[df.block >= 1]
    acc = df.groupby(['scen', 'var', 'subject']).apply(lambda g: g.ok.sum() / g.n.sum() * 100).unstack('var')
    rows = []
    for sc in ['base', 'wrong', 'half']:
        d = (acc.loc[sc]['cls5'] - acc.loc[sc]['fixed'])
        dz = d.mean() / d.std(ddof=1)
        rows.append(dict(kind='dev effect', scen=sc, mean_diff=d.mean(), sd_diff=d.std(ddof=1), dz=dz,
                         n_needed=n_needed(dz)))
    for n in (8, 10, 12, 14, 16, 20, 24):
        rows.append(dict(kind='min detectable dz', n=n, dz=min_dz(n)))
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, 'power_calc.csv'), index=False, float_format='%.3f')
    print(out.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
